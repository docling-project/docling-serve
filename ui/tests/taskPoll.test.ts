// SPDX-License-Identifier: MIT

import { afterEach, beforeEach, describe, expect, test } from "bun:test";

import { DoclingResponseSchemaMismatchError, DoclingTimeoutError } from "@docling/docling-client";

import {
  JOB_TIMEOUT_MS,
  POLL_INTERVAL_MS,
  pollTaskStatus,
  type WatchedTaskStatus,
} from "../src/lib/taskPoll";

const BASE = "https://example.test/root";
const KEY = "secret-key";

function statusPayload(task_status: string, extra: Record<string, unknown> = {}) {
  return {
    task_id: "task-1",
    task_type: "convert",
    task_status,
    task_position: task_status === "pending" ? 2 : undefined,
    ...extra,
  };
}

function mockFetchSequence(payloads: unknown[], opts?: { calls?: string[] }) {
  let i = 0;
  const calls: string[] = opts?.calls ?? [];
  const original = globalThis.fetch;
  // @ts-expect-error - test double replaces global fetch
  globalThis.fetch = async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    calls.push(url);
    const headers = new Headers(init?.headers as HeadersInit);
    calls.push(`key:${headers.get("X-Api-Key") ?? ""}`);
    const payload = payloads[Math.min(i, payloads.length - 1)];
    i += 1;
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  return { calls, restore: () => { globalThis.fetch = original; } };
}

let restoreFetch: (() => void) | null = null;
beforeEach(() => { restoreFetch = null; });
afterEach(() => { restoreFetch?.(); restoreFetch = null; });

function statusCalls(calls: string[]): string[] {
  return calls.filter((call) => !call.startsWith("key:"));
}

describe("taskPoll constants", () => {
  test("keeps 2s interval and 24h timeout defaults", () => {
    expect(POLL_INTERVAL_MS).toBe(2000);
    expect(JOB_TIMEOUT_MS).toBe(24 * 3600 * 1000);
  });
});

describe("pollTaskStatus delegates to the SDK watcher", () => {
  test("pending->started->cancelled delivers every status and returns cancelled", async () => {
    const seen: string[] = [];
    const calls: string[] = [];
    const h = mockFetchSequence(
      [statusPayload("pending"), statusPayload("started"), statusPayload("cancelled")],
      { calls },
    );
    restoreFetch = h.restore;

    const terminal = await pollTaskStatus("task-1", new AbortController().signal, {
      baseUrl: BASE,
      apiKey: KEY,
      pollIntervalMs: 1,
      timeoutMs: 5000,
      onStatus: (status) => seen.push(status.task_status),
    });

    expect(terminal.task_status).toBe("cancelled");
    expect(seen).toEqual(["pending", "started", "cancelled"]);
    // Only status-poll URLs are requested, never a result URL.
    const urls = statusCalls(calls);
    expect(urls).toHaveLength(3);
    for (const url of urls) {
      expect(url.startsWith(`${BASE}/v1/status/poll/task-1`)).toBe(true);
      expect(url).not.toContain("/result");
    }
  });

  test("propagates the root path and the api key header", async () => {
    const calls: string[] = [];
    const h = mockFetchSequence([statusPayload("success")], { calls });
    restoreFetch = h.restore;

    const terminal: WatchedTaskStatus = await pollTaskStatus("abc", new AbortController().signal, {
      baseUrl: BASE,
      apiKey: KEY,
      pollIntervalMs: 1,
      timeoutMs: 1000,
    });

    expect(terminal.task_status).toBe("success");
    expect(calls[0]?.startsWith(`${BASE}/v1/status/poll/abc`)).toBe(true);
    expect(calls[1]).toBe(`key:${KEY}`);
  });

  test("omits the api key header when no key is configured", async () => {
    const calls: string[] = [];
    const h = mockFetchSequence([statusPayload("success")], { calls });
    restoreFetch = h.restore;

    await pollTaskStatus("abc", new AbortController().signal, {
      baseUrl: BASE,
      apiKey: "",
      pollIntervalMs: 1,
      timeoutMs: 1000,
    });

    expect(calls[1]).toBe("key:");
  });

  test("rejects an unknown status instead of treating it as terminal", async () => {
    const h = mockFetchSequence([statusPayload("bogus-value")]);
    restoreFetch = h.restore;

    await expect(
      pollTaskStatus("t", new AbortController().signal, {
        baseUrl: BASE,
        apiKey: KEY,
        pollIntervalMs: 1,
        timeoutMs: 1000,
      }),
    ).rejects.toBeInstanceOf(DoclingResponseSchemaMismatchError);
  });

  test("fails with a timeout when the task never reaches a terminal status", async () => {
    const h = mockFetchSequence([statusPayload("pending")]);
    restoreFetch = h.restore;

    await expect(
      pollTaskStatus("t", new AbortController().signal, {
        baseUrl: BASE,
        apiKey: KEY,
        pollIntervalMs: 1,
        timeoutMs: 15,
      }),
    ).rejects.toBeInstanceOf(DoclingTimeoutError);
  });
});

describe("pollTaskStatus abort handling", () => {
  test("an already-aborted signal rejects without a completed request", async () => {
    let settled = 0;
    const original = globalThis.fetch;
    // @ts-expect-error - test double honours the passed AbortSignal
    globalThis.fetch = (_input: unknown, init?: RequestInit) => {
      const signal = init?.signal as AbortSignal | undefined;
      settled += 1;
      if (signal?.aborted) {
        return Promise.reject(new DOMException("Aborted", "AbortError"));
      }
      return new Promise<Response>((_resolve, reject) => {
        signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    };
    restoreFetch = () => { globalThis.fetch = original; };

    const controller = new AbortController();
    controller.abort();

    await expect(
      pollTaskStatus("t", controller.signal, { baseUrl: BASE, apiKey: KEY, timeoutMs: 5000 }),
    ).rejects.toThrow();
    expect(settled).toBeLessThanOrEqual(1);
  });

  test("abort while polling rejects and does not start another request", async () => {
    let calls = 0;
    const original = globalThis.fetch;
    // @ts-expect-error - test double honours the passed AbortSignal
    globalThis.fetch = (_input: unknown, init?: RequestInit) => {
      calls += 1;
      const signal = init?.signal as AbortSignal | undefined;
      return new Promise<Response>((_resolve, reject) => {
        signal?.addEventListener(
          "abort",
          () => reject(new DOMException("Aborted", "AbortError")),
          { once: true },
        );
      });
    };
    restoreFetch = () => { globalThis.fetch = original; };

    const controller = new AbortController();
    const pending = pollTaskStatus("t", controller.signal, {
      baseUrl: BASE,
      apiKey: KEY,
      pollIntervalMs: 1,
      timeoutMs: 5000,
    });
    await Bun.sleep(20);
    controller.abort();

    await expect(pending).rejects.toThrow();
    expect(calls).toBe(1);
  });
});

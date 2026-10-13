// SPDX-License-Identifier: MIT

import { afterEach, beforeEach, describe, expect, test } from "bun:test";

import {
  abortAwareDelay,
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

function mockFetchSequence(payloads: unknown[], opts?: { status?: number; calls?: string[] }) {
  let i = 0;
  const calls: string[] = opts?.calls ?? [];
  const original = globalThis.fetch;
  // @ts-expect-error - test double replaces global fetch
  globalThis.fetch = async (input: string | URL | Request, init?: RequestInit) => {
    const url = String(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
    calls.push(url);
    const headers = new Headers(init?.headers as HeadersInit);
    // Record api-key propagation for assertion via a side channel header echo.
    calls.push(`key:${headers.get("X-Api-Key") ?? ""}`);
    const payload = payloads[Math.min(i, payloads.length - 1)];
    i += 1;
    return new Response(JSON.stringify(payload), {
      status: opts?.status ?? 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  return { calls, restore: () => { globalThis.fetch = original; } };
}

let restoreFetch: (() => void) | null = null;
beforeEach(() => { restoreFetch = null; });
afterEach(() => { restoreFetch?.(); restoreFetch = null; });

async function expectAbort(promise: Promise<unknown>) {
  try {
    await promise;
  } catch (e) {
    expect(e instanceof DOMException && (e as DOMException).name === "AbortError").toBe(true);
    return;
  }
  throw new Error("expected AbortError, promise resolved");
}

describe("taskPoll constants", () => {
  test("keeps 2s interval and 24h timeout defaults", () => {
    expect(POLL_INTERVAL_MS).toBe(2000);
    expect(JOB_TIMEOUT_MS).toBe(24 * 3600 * 1000);
  });
});

describe("pollTaskStatus intermediate delivery", () => {
  test("pending->started->cancelled delivers every status and returns cancelled", async () => {
    const seen: string[] = [];
    const calls: string[] = [];
    const h = mockFetchSequence(
      [statusPayload("pending"), statusPayload("started"), statusPayload("cancelled")],
      { calls },
    );
    restoreFetch = h.restore;
    const controller = new AbortController();
    const terminal = await pollTaskStatus("task-1", controller.signal, {
      baseUrl: BASE,
      apiKey: KEY,
      pollIntervalMs: 1,
      timeoutMs: 5000,
      onStatus: (s) => seen.push(s.task_status as string),
    });
    expect(terminal.task_status).toBe("cancelled");
    expect(seen).toEqual(["pending", "started", "cancelled"]);
    // Only status-poll URLs are requested, never a result URL.
    const urls = calls.filter((c) => !c.startsWith("key:"));
    expect(urls).toHaveLength(3);
    for (const url of urls) {
      expect(url).toBe(`${BASE}/v1/status/poll/task-1`);
      expect(url).not.toContain("/result");
    }
  });

  test("pending->success terminates and pending->failure terminates", async () => {
    for (const terminalStatus of ["success", "failure"] as const) {
      const seen: string[] = [];
      const calls: string[] = [];
      const h = mockFetchSequence([statusPayload("pending"), statusPayload(terminalStatus)], { calls });
      restoreFetch = h.restore;
      const controller = new AbortController();
      const terminal = await pollTaskStatus("t", controller.signal, {
        baseUrl: BASE,
        apiKey: KEY,
        pollIntervalMs: 1,
        timeoutMs: 5000,
        onStatus: (s: WatchedTaskStatus) => seen.push(s.task_status as string),
      });
      expect(terminal.task_status).toBe(terminalStatus);
      expect(seen).toEqual(["pending", terminalStatus]);
      h.restore();
      restoreFetch = null;
    }
  });

  test("propagates root path and api key headers", async () => {
    const calls: string[] = [];
    const h = mockFetchSequence([statusPayload("success")], { calls });
    restoreFetch = h.restore;
    await pollTaskStatus("abc", new AbortController().signal, {
      baseUrl: BASE,
      apiKey: KEY,
      pollIntervalMs: 1,
      timeoutMs: 1000,
    });
    expect(calls[0]).toBe(`${BASE}/v1/status/poll/abc`);
    expect(calls[1]).toBe(`key:${KEY}`);
  });

  test("omits api-key header when no key", async () => {
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

  test("defaults derive proxy root and api key from window/sessionStorage", async () => {
    const calls: string[] = [];
    const h = mockFetchSequence([statusPayload("success")], { calls });
    restoreFetch = h.restore;
    const prevWindow = (globalThis as Record<string, unknown>)["window"];
    const prevStorage = (globalThis as Record<string, unknown>)["sessionStorage"];
    (globalThis as Record<string, unknown>)["window"] = {
      location: { origin: "https://proxy.test", pathname: "/root/ui/" },
    };
    (globalThis as Record<string, unknown>)["sessionStorage"] = {
      getItem: (key: string) =>
        key === "docling-serve-ui:api-key" ? "default-secret" : null,
    };
    try {
      await pollTaskStatus("abc", new AbortController().signal, {
        pollIntervalMs: 1,
        timeoutMs: 1000,
      });
    } finally {
      if (prevWindow === undefined) delete (globalThis as Record<string, unknown>)["window"];
      else (globalThis as Record<string, unknown>)["window"] = prevWindow;
      if (prevStorage === undefined)
        delete (globalThis as Record<string, unknown>)["sessionStorage"];
      else (globalThis as Record<string, unknown>)["sessionStorage"] = prevStorage;
    }
    expect(calls[0]).toBe("https://proxy.test/root/v1/status/poll/abc");
    expect(calls[1]).toBe("key:default-secret");
  });

  test("defaults without proxy root or key use origin and no header", async () => {
    const calls: string[] = [];
    const h = mockFetchSequence([statusPayload("success")], { calls });
    restoreFetch = h.restore;
    const prevWindow = (globalThis as Record<string, unknown>)["window"];
    const prevStorage = (globalThis as Record<string, unknown>)["sessionStorage"];
    (globalThis as Record<string, unknown>)["window"] = {
      location: { origin: "https://direct.test", pathname: "/" },
    };
    (globalThis as Record<string, unknown>)["sessionStorage"] = {
      getItem: (_key: string) => null,
    };
    try {
      await pollTaskStatus("abc", new AbortController().signal, {
        pollIntervalMs: 1,
        timeoutMs: 1000,
      });
    } finally {
      if (prevWindow === undefined) delete (globalThis as Record<string, unknown>)["window"];
      else (globalThis as Record<string, unknown>)["window"] = prevWindow;
      if (prevStorage === undefined)
        delete (globalThis as Record<string, unknown>)["sessionStorage"];
      else (globalThis as Record<string, unknown>)["sessionStorage"] = prevStorage;
    }
    expect(calls[0]).toBe("https://direct.test/v1/status/poll/abc");
    expect(calls[1]).toBe("key:");
  });
});

describe("pollTaskStatus abort and timeout", () => {
  test("already-aborted signal never fetches", async () => {
    let fetched = false;
    const original = globalThis.fetch;
    // @ts-expect-error - test double
    globalThis.fetch = async () => {
      fetched = true;
      return new Response("{}", { status: 200 });
    };
    restoreFetch = () => { globalThis.fetch = original; };
    const controller = new AbortController();
    controller.abort();
    await expectAbort(
      pollTaskStatus("t", controller.signal, { baseUrl: BASE, apiKey: KEY }),
    );
    expect(fetched).toBe(false);
  });

  test("abort during delay stops without extra request", async () => {
    const h = mockFetchSequence([statusPayload("pending"), statusPayload("success")]);
    restoreFetch = h.restore;
    const controller = new AbortController();
    const pending = pollTaskStatus("t", controller.signal, {
      baseUrl: BASE,
      apiKey: KEY,
      pollIntervalMs: 5000,
      timeoutMs: 60000,
    });
    // Let the first poll resolve and the helper enter the delay.
    await Bun.sleep(20);
    controller.abort();
    await expectAbort(pending);
    const urls = h.calls.filter((c) => !c.startsWith("key:"));
    expect(urls).toHaveLength(1);
  });

  test("in-flight abort propagates with one fetch and no next poll", async () => {
    let calls = 0;
    let notified = 0;
    const original = globalThis.fetch;
    // @ts-expect-error - test double respects the passed AbortSignal
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
      onStatus: () => { notified += 1; },
    });
    await Bun.sleep(20);
    controller.abort();
    await expectAbort(pending);
    expect(calls).toBe(1);
    expect(notified).toBe(0);
  });

  test("abortAwareDelay rejects when already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    await expectAbort(abortAwareDelay(10, controller.signal));
  });

  test("configured timeout fails without hanging", async () => {
    const h = mockFetchSequence([statusPayload("pending")]);
    restoreFetch = h.restore;
    await expect(
      pollTaskStatus("t", new AbortController().signal, {
        baseUrl: BASE,
        apiKey: KEY,
        pollIntervalMs: 1,
        timeoutMs: 15,
      }),
    ).rejects.toThrow("Timed out waiting for conversion.");
  });
});

describe("pollTaskStatus errors", () => {
  test("non-2xx poll throws without onStatus terminal", async () => {
    let notified = 0;
    const h = mockFetchSequence([statusPayload("pending")], { status: 500 });
    restoreFetch = h.restore;
    await expect(
      pollTaskStatus("t", new AbortController().signal, {
        baseUrl: BASE,
        apiKey: KEY,
        pollIntervalMs: 1,
        timeoutMs: 1000,
        onStatus: () => { notified += 1; },
      }),
    ).rejects.toThrow("Status poll failed: 500");
    expect(notified).toBe(0);
  });

  test("unknown status is rejected, not treated as success", async () => {
    const h = mockFetchSequence([{ task_id: "t", task_status: "bogus-value" }]);
    restoreFetch = h.restore;
    await expect(
      pollTaskStatus("t", new AbortController().signal, {
        baseUrl: BASE,
        apiKey: KEY,
        pollIntervalMs: 1,
        timeoutMs: 1000,
      }),
    ).rejects.toThrow("Invalid task status: bogus-value");
  });

  test("missing status is rejected", async () => {
    const h = mockFetchSequence([{ task_id: "t" }]);
    restoreFetch = h.restore;
    await expect(
      pollTaskStatus("t", new AbortController().signal, {
        baseUrl: BASE,
        apiKey: KEY,
        pollIntervalMs: 1,
        timeoutMs: 1000,
      }),
    ).rejects.toThrow("Invalid task status:");
  });
});

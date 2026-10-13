// SPDX-License-Identifier: MIT

import type { TaskStatusResponse } from "@docling/docling-client";

import { apiBaseUrl, getApiKey } from "@/lib/api";

/**
 * Task status as seen over the wire. The pinned client types predate the
 * server's terminal `cancelled` status, so the local type widens the SDK
 * status union instead of updating the dependency. Values are compared as
 * raw strings from the poll response; the typed client parser is bypassed.
 */
export type WatchedTaskStatus = Omit<TaskStatusResponse, "task_status"> & {
  task_status: TaskStatusResponse["task_status"] | "cancelled";
};

export const POLL_INTERVAL_MS = 2000;
export const JOB_TIMEOUT_MS = 24 * 3600 * 1000;

const TERMINAL_STATUSES = new Set([
  "success",
  "failure",
  "cancelled",
  "partial_success",
  "skipped",
]);

export interface PollStatusOptions {
  onStatus?: (status: WatchedTaskStatus) => void;
  pollIntervalMs?: number;
  timeoutMs?: number;
  baseUrl?: string;
  apiKey?: string | null;
}

export function abortError(): DOMException {
  return new DOMException("Aborted", "AbortError");
}

export async function abortAwareDelay(ms: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) throw abortError();
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

export async function pollTaskStatus(
  taskId: string,
  signal: AbortSignal,
  options?: PollStatusOptions,
): Promise<WatchedTaskStatus> {
  const pollInterval = options?.pollIntervalMs ?? POLL_INTERVAL_MS;
  const timeoutMs = options?.timeoutMs ?? JOB_TIMEOUT_MS;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    if (signal.aborted) throw abortError();
    const base = options?.baseUrl !== undefined ? options.baseUrl : apiBaseUrl();
    const apiKey = options?.apiKey !== undefined ? options.apiKey : getApiKey();
    const response = await fetch(`${base}/v1/status/poll/${taskId}`, {
      headers: apiKey ? { "X-Api-Key": apiKey } : {},
      signal,
    });
    if (!response.ok) {
      throw new Error(`Status poll failed: ${response.status}`);
    }
    const data = (await response.json()) as WatchedTaskStatus;
    const status = (data as { task_status?: unknown }).task_status;
    if (status === "pending" || status === "started") {
      options?.onStatus?.(data);
      if (Date.now() > deadline) {
        throw new Error("Timed out waiting for conversion.");
      }
      await abortAwareDelay(pollInterval, signal);
      continue;
    }
    if (typeof status === "string" && TERMINAL_STATUSES.has(status)) {
      options?.onStatus?.(data);
      return data;
    }
    throw new Error(`Invalid task status: ${String(status)}`);
  }
}

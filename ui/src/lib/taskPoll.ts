// SPDX-License-Identifier: MIT

import { DoclingClient, type TaskStatusResponse } from "@docling/docling-client";

import { apiBaseUrl, getApiKey } from "@/lib/api";

export type WatchedTaskStatus = TaskStatusResponse;

export const POLL_INTERVAL_MS = 2000;
export const JOB_TIMEOUT_MS = 24 * 3600 * 1000;

export interface PollStatusOptions {
  onStatus?: (status: WatchedTaskStatus) => void;
  pollIntervalMs?: number;
  timeoutMs?: number;
  baseUrl?: string;
  apiKey?: string | null;
}

export async function pollTaskStatus(
  taskId: string,
  signal: AbortSignal,
  options?: PollStatusOptions,
): Promise<WatchedTaskStatus> {
  const baseUrl = options?.baseUrl !== undefined ? options.baseUrl : apiBaseUrl();
  const apiKey = options?.apiKey !== undefined ? options.apiKey : getApiKey();
  const client = new DoclingClient({
    baseUrl,
    ...(apiKey ? { apiKey } : {}),
    statusWatcher: "polling",
    pollClientIntervalMs: options?.pollIntervalMs ?? POLL_INTERVAL_MS,
    jobTimeoutMs: options?.timeoutMs ?? JOB_TIMEOUT_MS,
  });
  try {
    return await client.waitForCompletion(taskId, {
      signal,
      ...(options?.onStatus === undefined ? {} : { onStatus: options.onStatus }),
    });
  } finally {
    await client.close();
  }
}

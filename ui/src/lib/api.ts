import { DoclingClient } from "@docling/docling-client";

import type { Capabilities } from "./capabilities";
import type { OpenApiDocument } from "./schema";

/**
 * Base URL of the docling-serve API. The UI is served at `<root>/ui/`, so the
 * API root is everything before the `/ui` segment. This keeps the UI working
 * behind a reverse proxy with a root path.
 */
export function apiBaseUrl(): string {
  const { origin, pathname } = window.location;
  const index = pathname.lastIndexOf("/ui");
  const root = index >= 0 ? pathname.slice(0, index) : "";
  return `${origin}${root}`;
}

const API_KEY_STORAGE = "docling-serve-ui:api-key";

export function getApiKey(): string {
  try {
    return sessionStorage.getItem(API_KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}

export function setApiKey(value: string): void {
  try {
    if (value) sessionStorage.setItem(API_KEY_STORAGE, value);
    else sessionStorage.removeItem(API_KEY_STORAGE);
  } catch {
    // Storage can be unavailable (private mode); the key then lasts per page load.
  }
}

export class HttpError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

async function getJson<T>(path: string): Promise<T> {
  const apiKey = getApiKey();
  const response = await fetch(`${apiBaseUrl()}${path}`, {
    headers: apiKey ? { "X-Api-Key": apiKey } : {},
  });
  if (!response.ok) {
    throw new HttpError(response.status, `${path}: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

/** Returns null when the deployment disabled the capabilities endpoint. */
export async function fetchCapabilities(): Promise<Capabilities | null> {
  try {
    return await getJson<Capabilities>("/v1/capabilities");
  } catch (error) {
    if (error instanceof HttpError && error.status === 404) return null;
    throw error;
  }
}

/** Returns null when the deployment disabled the API docs. */
export async function fetchOpenApi(): Promise<OpenApiDocument | null> {
  try {
    return await getJson<OpenApiDocument>("/openapi.json");
  } catch (error) {
    if (error instanceof HttpError && error.status === 404) return null;
    throw error;
  }
}

export async function fetchReady(): Promise<boolean> {
  try {
    const response = await fetch(`${apiBaseUrl()}/ready`);
    return response.ok;
  } catch {
    return false;
  }
}

export function createClient(): DoclingClient {
  const apiKey = getApiKey();
  return new DoclingClient({
    baseUrl: apiBaseUrl(),
    apiKey: apiKey || undefined,
    // docling-client 0.3.0 calls a stored `fetch` reference, which browsers
    // reject as an illegal invocation; a wrapper keeps it bound to window.
    fetch: (input, init) => globalThis.fetch(input, init),
    statusWatcher: "websocket",
    webSocketFallbackToPoll: true,
    jobTimeoutMs: 24 * 3600 * 1000,
  });
}

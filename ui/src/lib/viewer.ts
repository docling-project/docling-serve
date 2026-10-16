import type { ResultFile } from "./results";

/**
 * The DocLang viewer: a static page that renders `.dclx` archives. Override at
 * build time with `VITE_DCLX_VIEWER_URL`.
 */
export const DCLX_VIEWER_URL: string =
  import.meta.env.VITE_DCLX_VIEWER_URL ?? "https://doclang.ai/viewer/";

const PREFIX = "doclang-viewer";
const HANDSHAKE_TIMEOUT_MS = 30_000;

/**
 * Opens the viewer in a new window and hands it the `.dclx` file.
 *
 * The file only exists in this page (zip and inline results have no URL the
 * viewer could fetch), so it is sent with `postMessage`:
 *
 * 1. The viewer opens with `?source=opener`.
 * 2. This page posts `{type: "doclang-viewer:ping"}` until the viewer answers
 *    `{type: "doclang-viewer:ready"}` to `window.opener`.
 * 3. This page posts `{type: "doclang-viewer:open", name, mimeType, buffer}`,
 *    transferring the ArrayBuffer.
 *
 * Must be called from a click handler: browsers only allow pop-ups opened
 * directly in response to a user gesture.
 */
export async function openInDclxViewer(file: ResultFile): Promise<void> {
  const target = new URL(DCLX_VIEWER_URL, window.location.href);
  target.searchParams.set("source", "opener");
  const viewer = window.open(target, "_blank");
  if (!viewer) {
    throw new Error("The browser blocked the viewer window. Allow pop-ups for this page and retry.");
  }

  let bytes: Uint8Array;
  try {
    bytes = await file.bytes();
  } catch (error) {
    viewer.close();
    throw error;
  }
  await waitUntilReady(viewer, target.origin);

  // Send a copy, so the transfer does not detach the bytes this page still shows.
  const buffer = bytes.slice().buffer;
  viewer.postMessage(
    { type: `${PREFIX}:open`, name: file.name, mimeType: file.mimeType, buffer },
    target.origin,
    [buffer],
  );
}

function waitUntilReady(viewer: Window, origin: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const started = Date.now();

    const cleanup = () => {
      clearInterval(timer);
      window.removeEventListener("message", onMessage);
    };
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== origin || event.source !== viewer) return;
      if (event.data?.type === `${PREFIX}:ready`) {
        cleanup();
        resolve();
      }
    };
    const timer = setInterval(() => {
      if (viewer.closed) {
        cleanup();
        reject(new Error("The viewer window was closed before the document was sent."));
      } else if (Date.now() - started > HANDSHAKE_TIMEOUT_MS) {
        cleanup();
        reject(new Error(`The viewer at ${origin} did not respond.`));
      } else {
        // Dropped by the browser while the window is still loading or on
        // another origin; answered once the viewer is listening.
        viewer.postMessage({ type: `${PREFIX}:ping` }, origin);
      }
    }, 250);

    window.addEventListener("message", onMessage);
  });
}

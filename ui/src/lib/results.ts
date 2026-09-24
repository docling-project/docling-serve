import type {
  ConvertDocumentResponse,
  ErrorItem,
  PresignedUrlConvertResponse,
  ProfilingItem,
  RawServiceResult,
} from "@docling/docling-client";
import { unzipSync } from "fflate";

/**
 * A single output file of a conversion, independent of how the server
 * delivered it (inline JSON, zip archive or presigned URL).
 */
export interface ResultFile {
  /** Unique per conversion run, used as cache key for previews. */
  key: string;
  /** File name, e.g. `report.md` or `report.dclx`. */
  name: string;
  /** Output format key: md, json, html, text, doctags, doclang, dclx, … */
  format: string;
  mimeType: string;
  /** Present for presigned artifacts: the direct download URL. */
  url?: string;
  expiresAt?: string | null;
  bytes: () => Promise<Uint8Array>;
}

export interface ResultDocument {
  filename: string;
  status: string;
  errors: ErrorItem[];
  timings: Record<string, ProfilingItem>;
  files: ResultFile[];
}

export interface ConversionOutcome {
  target: string;
  processingTime?: number;
  documents: ResultDocument[];
  /** The raw zip, when the server returned one (for "download all"). */
  archive?: { name: string; bytes: Uint8Array };
  /** Images referenced by the Markdown/HTML outputs (`artifacts/…`), by zip path. */
  resources?: Record<string, Uint8Array>;
}

const EXTENSION_FORMATS: Record<string, string> = {
  md: "md",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  html: "html",
  txt: "text",
  doctags: "doctags",
  dt: "doctags",
  doclang: "doclang",
  dclg: "doclang",
  dclx: "dclx",
  vtt: "vtt",
  tex: "latex",
};

const FORMAT_MIME: Record<string, string> = {
  md: "text/markdown",
  json: "application/json",
  yaml: "application/yaml",
  html: "text/html",
  text: "text/plain",
  doctags: "text/plain",
  doclang: "application/xml",
  dclx: "application/zip",
  vtt: "text/vtt",
  latex: "application/x-tex",
};

const ARTIFACT_FORMATS: Record<string, string> = {
  markdown: "md",
  json: "json",
  html: "html",
  text: "text",
  doctags: "doctags",
  doclang: "doclang",
  dclx: "dclx",
  resource_bundle: "bundle",
};

let fileCounter = 0;
const nextKey = () => `file-${++fileCounter}`;

const TEXT_ENCODER = new TextEncoder();
const TEXT_DECODER = new TextDecoder();

export const decodeText = (bytes: Uint8Array) => TEXT_DECODER.decode(bytes);

function stem(filename: string): string {
  const base = filename.split("/").pop() ?? filename;
  const dot = base.lastIndexOf(".");
  return dot > 0 ? base.slice(0, dot) : base;
}

function extensionOf(path: string): string {
  return path.split(".").pop()?.toLowerCase() ?? "";
}

function formatOfPath(path: string): string | undefined {
  return EXTENSION_FORMATS[extensionOf(path)];
}

const IMAGE_MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  webp: "image/webp",
  gif: "image/gif",
  svg: "image/svg+xml",
};

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

/**
 * Replaces references to zip resources (e.g. `artifacts/image_000.png` from
 * the "referenced" image mode) with data URLs, so previews show the images.
 */
export function inlineResources(text: string, resources?: Record<string, Uint8Array>): string {
  if (!resources) return text;
  let result = text;
  for (const [path, bytes] of Object.entries(resources)) {
    if (!result.includes(path)) continue;
    const dataUrl = `data:${IMAGE_MIME[extensionOf(path)]};base64,${toBase64(bytes)}`;
    result = result.split(path).join(dataUrl);
  }
  return result;
}

function staticFile(name: string, format: string, bytes: Uint8Array): ResultFile {
  return {
    key: nextKey(),
    name,
    format,
    mimeType: FORMAT_MIME[format] ?? "application/octet-stream",
    bytes: async () => bytes,
  };
}

export function fromInBody(response: ConvertDocumentResponse): ConversionOutcome {
  const document = response.document;
  const name = stem(document.filename);
  const files: ResultFile[] = [];
  const add = (format: string, extension: string, content: unknown) => {
    if (content === null || content === undefined) return;
    const text = typeof content === "string" ? content : JSON.stringify(content, null, 2);
    files.push(staticFile(`${name}.${extension}`, format, TEXT_ENCODER.encode(text)));
  };
  add("md", "md", document.md_content);
  add("json", "json", document.json_content);
  add("html", "html", document.html_content);
  add("text", "txt", document.text_content);
  add("doctags", "doctags", document.doctags_content);
  add("doclang", "doclang", document.doclang_content);

  return {
    target: "inbody",
    processingTime: response.processing_time,
    documents: [
      {
        filename: document.filename,
        status: response.status,
        errors: response.errors,
        timings: response.timings,
        files,
      },
    ],
  };
}

export function fromZip(result: RawServiceResult, sourceName: string): ConversionOutcome {
  const entries = unzipSync(result.content);
  const byDocument = new Map<string, ResultFile[]>();
  const resources: Record<string, Uint8Array> = {};

  for (const [path, bytes] of Object.entries(entries)) {
    if (path.endsWith("/")) continue;
    const format = formatOfPath(path);
    if (!format) {
      if (IMAGE_MIME[extensionOf(path)]) resources[path] = bytes;
      continue;
    }
    const fileName = path.split("/").pop() ?? path;
    const key = stem(fileName);
    const files = byDocument.get(key) ?? [];
    files.push(staticFile(fileName, format, bytes));
    byDocument.set(key, files);
  }

  const documents: ResultDocument[] = [...byDocument.entries()].map(([name, files]) => ({
    filename: name,
    status: "success",
    errors: [],
    timings: {},
    files,
  }));

  return {
    target: "zip",
    documents,
    archive: {
      name: result.filename ?? `${stem(sourceName)}.zip`,
      bytes: result.content,
    },
    resources,
  };
}

export function fromPresigned(response: PresignedUrlConvertResponse): ConversionOutcome {
  return {
    target: "presigned_url",
    processingTime: response.processing_time,
    documents: response.documents.map((item) => {
      const name = stem(item.filename);
      return {
        filename: item.filename,
        status: item.status,
        errors: item.errors,
        timings: item.timings,
        files: item.artifacts.map((artifact) => {
          const format = ARTIFACT_FORMATS[artifact.artifact_type] ?? artifact.artifact_type;
          const urlName = new URL(artifact.uri).pathname.split("/").pop() ?? "";
          let cached: Promise<Uint8Array> | undefined;
          return {
            key: nextKey(),
            name: urlName.includes(".") ? decodeURIComponent(urlName) : `${name}.${format}`,
            format,
            mimeType: artifact.mime_type,
            url: artifact.uri,
            expiresAt: artifact.url_expires_at,
            bytes: () => {
              cached ??= fetch(artifact.uri).then(async (response) => {
                if (!response.ok) {
                  throw new Error(`Download failed: ${response.status} ${response.statusText}`);
                }
                return new Uint8Array(await response.arrayBuffer());
              });
              return cached;
            },
          } satisfies ResultFile;
        }),
      };
    }),
  };
}

export function downloadBytes(bytes: Uint8Array, name: string, mimeType: string): void {
  const blob = new Blob([bytes as BlobPart], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function downloadFile(file: ResultFile): Promise<void> {
  if (file.url) {
    // Presigned URLs are downloaded directly: this needs no CORS on the bucket.
    const link = document.createElement("a");
    link.href = file.url;
    link.download = file.name;
    link.rel = "noopener";
    link.click();
    return;
  }
  downloadBytes(await file.bytes(), file.name, file.mimeType);
}

/** Lists the entries of a `.dclx` archive (a zip of DocLang XML and resources). */
export function inspectDclx(bytes: Uint8Array): { path: string; bytes: Uint8Array }[] {
  const entries = unzipSync(bytes);
  return Object.entries(entries)
    .filter(([path]) => !path.endsWith("/"))
    .map(([path, content]) => ({ path, bytes: content }))
    .sort((a, b) => a.path.localeCompare(b.path));
}

/** Minimal view of a DoclingDocument, for what the UI inspects itself. */
export interface DoclingDocumentJson {
  schema_name?: string;
  pages?: Record<string, { image?: { uri?: string } | null }>;
  [key: string]: unknown;
}

const IMAGE_MIME: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  webp: "image/webp",
  gif: "image/gif",
};

/**
 * Points image URIs of the document (`artifacts/page_000001_….png` with the
 * "referenced" image mode) at object URLs of the images unpacked from the zip
 * result. Returns the rewritten document and the URLs to revoke later.
 */
export function resolveDocumentImages(
  document: DoclingDocumentJson,
  resources?: Record<string, Uint8Array>,
): { document: DoclingDocumentJson; objectUrls: string[] } {
  const objectUrls: string[] = [];
  if (!resources || Object.keys(resources).length === 0) return { document, objectUrls };

  const urls = new Map<string, string>();
  const urlFor = (path: string) => {
    let url = urls.get(path);
    if (!url) {
      const type = IMAGE_MIME[path.split(".").pop()?.toLowerCase() ?? ""] ?? "application/octet-stream";
      url = URL.createObjectURL(new Blob([resources[path] as BlobPart], { type }));
      urls.set(path, url);
      objectUrls.push(url);
    }
    return url;
  };

  const visit = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(visit);
    if (value === null || typeof value !== "object") return value;
    const result: Record<string, unknown> = {};
    for (const [key, child] of Object.entries(value)) {
      result[key] = key === "uri" && typeof child === "string" && child in resources ? urlFor(child) : visit(child);
    }
    return result;
  };

  return { document: visit(document) as DoclingDocumentJson, objectUrls };
}

export function hasPageImages(document: DoclingDocumentJson): boolean {
  return Object.values(document.pages ?? {}).some((page) => Boolean(page.image?.uri));
}

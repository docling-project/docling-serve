import { apiBaseUrl } from "./api";

export interface RequestDescription {
  source: { kind: "file"; filename: string } | { kind: "http"; url: string };
  options: Record<string, unknown>;
  target: string;
  apiKeyRequired: boolean;
}

function shellQuote(value: string): string {
  return `'${value.replace(/'/g, `'\\''`)}'`;
}

function formFields(options: Record<string, unknown>): [string, string][] {
  const fields: [string, string][] = [];
  for (const [key, value] of Object.entries(options)) {
    if (value === undefined || value === null) continue;
    const values = Array.isArray(value) ? value : [value];
    for (const item of values) {
      fields.push([key, typeof item === "string" ? item : JSON.stringify(item)]);
    }
  }
  return fields;
}

export function curlSnippet(request: RequestDescription): string {
  const base = apiBaseUrl();
  const auth = request.apiKeyRequired ? ["  -H 'X-Api-Key: $DOCLING_SERVE_API_KEY'"] : [];

  if (request.source.kind === "file") {
    const lines = [
      `curl -X POST ${shellQuote(`${base}/v1/convert/file`)}`,
      ...auth,
      `  -F ${shellQuote(`files=@${request.source.filename}`)}`,
      ...formFields(request.options).map(([k, v]) => `  -F ${shellQuote(`${k}=${v}`)}`),
      `  -F ${shellQuote(`target_type=${request.target}`)}`,
    ];
    if (request.target === "zip") lines.push("  -o result.zip");
    return lines.join(" \\\n");
  }

  const body = {
    options: request.options,
    sources: [{ kind: "http", url: request.source.url }],
    target: { kind: request.target },
  };
  const lines = [
    `curl -X POST ${shellQuote(`${base}/v1/convert/source`)}`,
    ...auth,
    "  -H 'Content-Type: application/json'",
    `  -d ${shellQuote(JSON.stringify(body, null, 2))}`,
  ];
  if (request.target === "zip") lines.push("  -o result.zip");
  return lines.join(" \\\n");
}

function pythonLiteral(value: unknown, indent = 0): string {
  const pad = " ".repeat(indent);
  if (value === null || value === undefined) return "None";
  if (typeof value === "boolean") return value ? "True" : "False";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map((v) => pythonLiteral(v, indent)).join(", ")}]`;
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return "{}";
  const inner = entries
    .map(([k, v]) => `${pad}    ${JSON.stringify(k)}: ${pythonLiteral(v, indent + 4)},`)
    .join("\n");
  return `{\n${inner}\n${pad}}`;
}

export function pythonSnippet(request: RequestDescription): string {
  const base = apiBaseUrl();
  const headers = request.apiKeyRequired
    ? `headers = {"X-Api-Key": os.environ["DOCLING_SERVE_API_KEY"]}\n`
    : "headers = {}\n";
  const options = pythonLiteral(request.options);
  const save =
    request.target === "zip"
      ? `with open("result.zip", "wb") as f:\n    f.write(response.content)`
      : "print(response.json())";

  if (request.source.kind === "file") {
    return `import json
import os

import httpx

${headers}options = ${options}
data = {k: (v if isinstance(v, (str, list)) else json.dumps(v)) for k, v in options.items()}
data["target_type"] = ${JSON.stringify(request.target)}

with open(${JSON.stringify(request.source.filename)}, "rb") as f:
    response = httpx.post(
        ${JSON.stringify(`${base}/v1/convert/file`)},
        headers=headers,
        files={"files": f},
        data=data,
        timeout=None,
    )
response.raise_for_status()
${save}
`;
  }

  return `import os

import httpx

${headers}payload = {
    "options": ${pythonLiteral(request.options, 4)},
    "sources": [{"kind": "http", "url": ${JSON.stringify(request.source.url)}}],
    "target": {"kind": ${JSON.stringify(request.target)}},
}
response = httpx.post(
    ${JSON.stringify(`${base}/v1/convert/source`)},
    headers=headers,
    json=payload,
    timeout=None,
)
response.raise_for_status()
${save}
`;
}

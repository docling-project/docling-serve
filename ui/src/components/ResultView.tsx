import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Clock, Download, FileArchive, Package } from "lucide-react";
import { useState } from "react";
import ReactMarkdown, { defaultUrlTransform } from "react-markdown";
import remarkGfm from "remark-gfm";

import { DclxInspector } from "@/components/DclxInspector";
import { JsonTree } from "@/components/JsonTree";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  decodeText,
  downloadBytes,
  downloadFile,
  type ConversionOutcome,
  type ResultDocument,
  type ResultFile,
} from "@/lib/results";

const FORMAT_LABELS: Record<string, string> = {
  dclx: "DCLX",
  md: "Markdown",
  html: "HTML",
  json: "JSON",
  doclang: "DocLang",
  doctags: "DocTags",
  text: "Text",
  yaml: "YAML",
  vtt: "VTT",
  latex: "LaTeX",
};

// Viewer tab order: the dclx archive first.
const FORMAT_ORDER = ["dclx", "md", "html", "json", "doclang", "doctags", "text", "yaml", "latex", "vtt"];

const orderOf = (format: string) => {
  const index = FORMAT_ORDER.indexOf(format);
  return index === -1 ? FORMAT_ORDER.length : index;
};

interface Props {
  outcome: ConversionOutcome;
  requestedFormats: string[];
}

export function ResultView({ outcome, requestedFormats }: Props) {
  const [documentIndex, setDocumentIndex] = useState(0);
  const document = outcome.documents[documentIndex];

  if (!document) {
    return (
      <Alert>
        <AlertTriangle className="size-4" />
        <AlertTitle>No documents in the result</AlertTitle>
      </Alert>
    );
  }

  const files = [...document.files].sort((a, b) => orderOf(a.format) - orderOf(b.format));
  const missingDclx = requestedFormats.includes("dclx") && !files.some((f) => f.format === "dclx");

  return (
    <div className="space-y-4">
      {outcome.documents.length > 1 && (
        <div className="flex flex-wrap gap-1.5">
          {outcome.documents.map((doc, index) => (
            <Button
              key={doc.filename}
              size="sm"
              variant={index === documentIndex ? "default" : "outline"}
              onClick={() => setDocumentIndex(index)}
            >
              {doc.filename}
            </Button>
          ))}
        </div>
      )}

      <Summary outcome={outcome} document={document} />

      {missingDclx && (
        <Alert>
          <FileArchive className="size-4" />
          <AlertTitle>No DCLX archive in this result</AlertTitle>
          <AlertDescription>
            {outcome.target === "inbody"
              ? "Inline JSON results cannot carry the binary .dclx archive. Choose the zip or presigned URL delivery to get it."
              : "The server did not return a .dclx file for this document."}
          </AlertDescription>
        </Alert>
      )}

      <Downloads outcome={outcome} files={files} />

      {files.length > 0 && (
        <Tabs defaultValue={files[0].name}>
          <TabsList className="h-auto flex-wrap justify-start">
            {files.map((file) => (
              <TabsTrigger key={file.name} value={file.name}>
                {FORMAT_LABELS[file.format] ?? file.format}
              </TabsTrigger>
            ))}
          </TabsList>
          {files.map((file) => (
            <TabsContent key={file.name} value={file.name} className="mt-3">
              <FileViewer file={file} />
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
  );
}

function Summary({ outcome, document }: { outcome: ConversionOutcome; document: ResultDocument }) {
  const timings = Object.entries(document.timings)
    .map(([name, item]) => [name, item.times.reduce((sum, time) => sum + time, 0)] as const)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6);
  const statusVariant = document.status === "success" ? "default" : document.status === "failure" ? "destructive" : "secondary";

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">{document.filename}</span>
        <Badge variant={statusVariant}>{document.status}</Badge>
        {outcome.processingTime !== undefined && (
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Clock className="size-3.5" /> {outcome.processingTime.toFixed(2)} s
          </span>
        )}
      </div>
      {timings.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {timings.map(([name, seconds]) => (
            <Badge key={name} variant="outline" className="font-mono text-[11px] font-normal">
              {name}: {seconds.toFixed(2)} s
            </Badge>
          ))}
        </div>
      )}
      {document.errors.length > 0 && (
        <Alert variant="destructive">
          <AlertTriangle className="size-4" />
          <AlertTitle>Conversion reported {document.errors.length} error(s)</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {document.errors.map((error, index) => (
                <li key={index}>
                  {error.module_name}: {error.error_message}
                  {error.page_no ? ` (page ${error.page_no})` : ""}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}
    </div>
  );
}

function Downloads({ outcome, files }: { outcome: ConversionOutcome; files: ResultFile[] }) {
  const dclx = files.find((file) => file.format === "dclx");
  const others = files.filter((file) => file !== dclx);
  const expiresAt = files.find((file) => file.expiresAt)?.expiresAt;

  return (
    <div className="space-y-2 rounded-lg border bg-muted/40 p-3">
      <div className="flex flex-wrap items-center gap-2">
        {dclx && (
          <Button onClick={() => void downloadFile(dclx)}>
            <Download className="size-4" /> Download .dclx
          </Button>
        )}
        {others.map((file) => (
          <Button key={file.name} variant="outline" size="sm" onClick={() => void downloadFile(file)}>
            <Download className="size-3.5" /> {FORMAT_LABELS[file.format] ?? file.format}
          </Button>
        ))}
        {outcome.archive && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => downloadBytes(outcome.archive!.bytes, outcome.archive!.name, "application/zip")}
          >
            <Package className="size-3.5" /> All (.zip)
          </Button>
        )}
      </div>
      {expiresAt && (
        <p className="text-xs text-muted-foreground">
          Download links expire at {new Date(expiresAt).toLocaleString()}.
        </p>
      )}
    </div>
  );
}

function FileViewer({ file }: { file: ResultFile }) {
  if (file.format === "dclx") return <DclxInspector file={file} />;
  return <TextViewer file={file} />;
}

function TextViewer({ file }: { file: ResultFile }) {
  const [raw, setRaw] = useState(false);
  const query = useQuery({
    queryKey: ["result-file", file.key],
    queryFn: async () => decodeText(await file.bytes()),
    staleTime: Infinity,
  });

  if (query.isPending) return <p className="p-4 text-sm text-muted-foreground">Loading…</p>;
  if (query.isError) {
    return (
      <Alert>
        <AlertTriangle className="size-4" />
        <AlertTitle>Preview unavailable</AlertTitle>
        <AlertDescription>
          {file.url
            ? "The browser could not fetch the file from storage (the bucket may not allow cross-origin requests). The download button still works."
            : (query.error as Error).message}
        </AlertDescription>
      </Alert>
    );
  }

  const text = query.data;
  const renderable = file.format === "md" || file.format === "html" || file.format === "json";

  return (
    <div className="space-y-2">
      {renderable && (
        <div className="flex justify-end">
          <Button variant="ghost" size="sm" onClick={() => setRaw((value) => !value)}>
            {raw ? "Rendered" : "Source"}
          </Button>
        </div>
      )}
      <div className="max-h-[70vh] overflow-auto rounded-md border bg-card">
        {!raw && file.format === "md" ? (
          <div className="markdown p-5">
            <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={markdownUrl}>
              {text}
            </ReactMarkdown>
          </div>
        ) : !raw && file.format === "html" ? (
          // Sandboxed: no scripts, no same-origin access.
          <iframe title={file.name} sandbox="" srcDoc={text} className="h-[70vh] w-full bg-white" />
        ) : !raw && file.format === "json" ? (
          <div className="p-3">
            <JsonView text={text} />
          </div>
        ) : (
          <pre className="p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">{text}</pre>
        )}
      </div>
    </div>
  );
}

// Embedded page images come as data URIs, which react-markdown drops by default.
function markdownUrl(url: string): string {
  return url.startsWith("data:image/") ? url : defaultUrlTransform(url);
}

function JsonView({ text }: { text: string }) {
  try {
    return <JsonTree value={JSON.parse(text)} />;
  } catch {
    return <pre className="font-mono text-xs whitespace-pre-wrap">{text}</pre>;
  }
}

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ImageOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { type DoclingDocumentJson, hasPageImages, resolveDocumentImages } from "@/lib/document";
import { decodeText, type ResultFile } from "@/lib/results";
import { cn } from "@/lib/utils";

// Loaded on first use, so the web components stay out of the main bundle.
const loadComponents = () => import("@docling/docling-components");

const FILTERS = [
  { label: "All items", items: "" },
  { label: "Text", items: "#/texts" },
  { label: "Tables", items: "#/tables" },
  { label: "Pictures", items: "#/pictures" },
];

type Mode = "pages" | "items";

/** The converted DoclingDocument, rendered with the docling-components web components. */
export function DocumentView({
  file,
  resources,
}: {
  file: ResultFile;
  resources?: Record<string, Uint8Array>;
}) {
  const components = useQuery({ queryKey: ["docling-components"], queryFn: loadComponents, staleTime: Infinity });
  const json = useQuery({
    queryKey: ["document-json", file.key],
    queryFn: async () => JSON.parse(decodeText(await file.bytes())) as DoclingDocumentJson,
    staleTime: Infinity,
  });

  const resolved = useMemo(
    () => (json.data ? resolveDocumentImages(json.data, resources) : undefined),
    [json.data, resources],
  );
  useEffect(() => () => resolved?.objectUrls.forEach((url) => URL.revokeObjectURL(url)), [resolved]);

  const withPages = resolved ? hasPageImages(resolved.document) : false;
  const [mode, setMode] = useState<Mode | null>(null);
  const [filter, setFilter] = useState("");
  const activeMode: Mode = mode ?? (withPages ? "pages" : "items");

  if (json.isPending || components.isPending) {
    return <p className="p-4 text-sm text-muted-foreground">Rendering document…</p>;
  }
  if (json.isError || components.isError || !resolved) {
    return (
      <Alert>
        <AlertTriangle className="size-4" />
        <AlertTitle>Cannot render the document</AlertTitle>
        <AlertDescription>{((json.error ?? components.error) as Error | null)?.message}</AlertDescription>
      </Alert>
    );
  }

  const filtered = filter !== "";

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg bg-muted p-0.5">
          {(["pages", "items"] as const).map((value) => (
            <button
              key={value}
              type="button"
              disabled={value === "pages" && !withPages}
              aria-pressed={activeMode === value}
              onClick={() => setMode(value)}
              className={cn(
                "rounded-md px-3 py-1 text-sm transition-colors disabled:opacity-50",
                activeMode === value ? "bg-background font-medium shadow-sm" : "text-muted-foreground",
              )}
            >
              {value === "pages" ? "Pages" : "Items"}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-1">
          {FILTERS.map((option) => (
            <Button
              key={option.label}
              size="sm"
              variant={filter === option.items ? "secondary" : "ghost"}
              onClick={() => setFilter(option.items)}
            >
              {option.label}
            </Button>
          ))}
        </div>
      </div>

      {!withPages && (
        <Alert>
          <ImageOff className="size-4" />
          <AlertTitle>No page images in this result</AlertTitle>
          <AlertDescription>
            To see the items on the original pages, enable “Include page images”, use an image export mode other than
            “placeholder”, and choose the zip delivery.
          </AlertDescription>
        </Alert>
      )}

      {/* The components draw on white page renderings, so the area stays "paper" in both themes. */}
      <div className="max-h-[75vh] overflow-auto rounded-md border bg-white p-3 text-neutral-900 [color-scheme:light]">
        {activeMode === "pages" ? (
          <docling-img
            key={`pages-${filter}`}
            className="docling-document"
            src={resolved.document}
            items={filter || undefined}
            pagenumbers
            backdrop={filtered}
            trim={filtered ? "pages" : undefined}
          >
            <docling-tooltip />
          </docling-img>
        ) : (
          <docling-table
            key={`items-${filter}`}
            className="docling-document"
            src={resolved.document}
            items={filter || undefined}
          />
        )}
      </div>
    </div>
  );
}

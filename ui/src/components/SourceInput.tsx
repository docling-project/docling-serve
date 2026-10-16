import { FileUp, Link2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";

export type Source = { kind: "file"; file: File } | { kind: "http"; url: string };

interface Props {
  source: Source | null;
  onChange: (source: Source | null) => void;
  maxFileSize?: number | null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`;
}

export function SourceInput({ source, onChange, maxFileSize }: Props) {
  const [mode, setMode] = useState<"file" | "http">(source?.kind ?? "file");
  const [url, setUrl] = useState(source?.kind === "http" ? source.url : "");
  const inputRef = useRef<HTMLInputElement>(null);

  // Follow sources set from outside (example links, files dropped on the page).
  useEffect(() => {
    if (!source) return;
    setMode(source.kind);
    if (source.kind === "http") setUrl(source.url);
  }, [source]);
  const file = source?.kind === "file" ? source.file : null;
  const tooLarge = file && maxFileSize ? file.size > maxFileSize : false;

  const pick = (files: FileList | null) => {
    const picked = files?.[0];
    if (picked) onChange({ kind: "file", file: picked });
  };

  return (
    <Tabs
      value={mode}
      onValueChange={(value) => {
        const next = value as "file" | "http";
        setMode(next);
        onChange(next === "http" ? (url ? { kind: "http", url } : null) : null);
      }}
    >
      <TabsList className="grid w-full grid-cols-2">
        <TabsTrigger value="file">
          <FileUp className="size-4" /> File
        </TabsTrigger>
        <TabsTrigger value="http">
          <Link2 className="size-4" /> URL
        </TabsTrigger>
      </TabsList>

      <TabsContent value="file">
        <div
          role="button"
          tabIndex={0}
          onClick={() => inputRef.current?.click()}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") inputRef.current?.click();
          }}
          className="flex min-h-28 cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed border-input p-4 text-center transition-colors hover:border-brand/60 hover:bg-muted"
        >
          {file ? (
            <div className="flex w-full items-center justify-between gap-2">
              <div className="min-w-0 text-left">
                <p className="truncate text-sm font-medium">{file.name}</p>
                <p className={cn("text-xs", tooLarge ? "text-destructive" : "text-muted-foreground")}>
                  {formatBytes(file.size)}
                  {tooLarge && maxFileSize ? ` — larger than the server limit of ${formatBytes(maxFileSize)}` : ""}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Remove file"
                onClick={(event) => {
                  event.stopPropagation();
                  onChange(null);
                  if (inputRef.current) inputRef.current.value = "";
                }}
              >
                <X className="size-4" />
              </Button>
            </div>
          ) : (
            <>
              <FileUp className="size-6 text-brand" />
              <p className="text-sm font-medium">Drop a document anywhere or click to browse</p>
              <p className="text-xs text-muted-foreground">
                PDF, DOCX, PPTX, HTML, images and more
                {maxFileSize ? ` · up to ${formatBytes(maxFileSize)}` : ""}
              </p>
            </>
          )}
          <input ref={inputRef} type="file" className="hidden" onChange={(e) => pick(e.target.files)} />
        </div>
      </TabsContent>

      <TabsContent value="http">
        <Input
          type="url"
          placeholder="https://arxiv.org/pdf/2408.09869"
          value={url}
          onChange={(event) => {
            const next = event.target.value;
            setUrl(next);
            onChange(next.trim() ? { kind: "http", url: next.trim() } : null);
          }}
        />
      </TabsContent>
    </Tabs>
  );
}

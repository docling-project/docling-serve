import { useQuery } from "@tanstack/react-query";
import { FileArchive, FileCode2, Image as ImageIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { formatBytes } from "@/components/SourceInput";
import { decodeText, inspectDclx, type ResultFile } from "@/lib/results";
import { cn } from "@/lib/utils";

const IMAGE_TYPES: Record<string, string> = {
  png: "image/png",
  jpg: "image/jpeg",
  jpeg: "image/jpeg",
  gif: "image/gif",
  webp: "image/webp",
  svg: "image/svg+xml",
};

function extension(path: string) {
  return path.split(".").pop()?.toLowerCase() ?? "";
}

/** Browses the content of a `.dclx` archive (DocLang XML plus resources). */
export function DclxInspector({ file }: { file: ResultFile }) {
  const query = useQuery({
    queryKey: ["dclx", file.key],
    queryFn: async () => inspectDclx(await file.bytes()),
    staleTime: Infinity,
  });
  const entries = query.data ?? [];
  const [selected, setSelected] = useState<string | null>(null);

  useEffect(() => {
    if (!selected && entries.length > 0) {
      // The main DocLang document is the largest XML part of the package.
      const xml = entries.filter((entry) => /\.(xml|dclg)$/i.test(entry.path));
      const main = xml.sort((a, b) => b.bytes.length - a.bytes.length)[0] ?? entries[0];
      setSelected(main.path);
    }
  }, [entries, selected]);

  const current = entries.find((entry) => entry.path === selected);

  if (query.isPending) return <p className="p-4 text-sm text-muted-foreground">Opening archive…</p>;
  if (query.isError) {
    return (
      <p className="p-4 text-sm text-destructive">
        Could not open the archive: {(query.error as Error).message}. Use the download button instead.
      </p>
    );
  }

  const total = entries.reduce((sum, entry) => sum + entry.bytes.length, 0);

  return (
    <div className="grid min-h-0 gap-3 md:grid-cols-[minmax(12rem,16rem)_1fr]">
      <div className="min-w-0 space-y-2">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <FileArchive className="size-4 text-brand" />
          {entries.length} files · {formatBytes(total)}
        </div>
        <ul className="max-h-[60vh] space-y-0.5 overflow-auto">
          {entries.map((entry) => {
            const isImage = extension(entry.path) in IMAGE_TYPES;
            const Icon = isImage ? ImageIcon : FileCode2;
            return (
              <li key={entry.path}>
                <button
                  type="button"
                  onClick={() => setSelected(entry.path)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded px-2 py-1 text-left font-mono text-xs hover:bg-muted",
                    selected === entry.path && "bg-accent text-accent-foreground",
                  )}
                >
                  <Icon className="size-3.5 shrink-0" />
                  <span className="truncate">{entry.path}</span>
                  <span className="ml-auto shrink-0 text-muted-foreground">{formatBytes(entry.bytes.length)}</span>
                </button>
              </li>
            );
          })}
        </ul>
      </div>
      <div className="min-w-0 rounded-md border bg-muted/40">
        {current && <EntryPreview path={current.path} bytes={current.bytes} />}
      </div>
    </div>
  );
}

function EntryPreview({ path, bytes }: { path: string; bytes: Uint8Array }) {
  const type = IMAGE_TYPES[extension(path)];
  const url = useMemo(
    () => (type ? URL.createObjectURL(new Blob([bytes as BlobPart], { type })) : null),
    [bytes, type],
  );
  useEffect(() => () => {
    if (url) URL.revokeObjectURL(url);
  }, [url]);

  if (url) {
    return (
      <div className="flex justify-center p-4">
        <img src={url} alt={path} className="max-h-[60vh] max-w-full object-contain" />
      </div>
    );
  }
  const text = decodeText(bytes.subarray(0, 2_000_000));
  return (
    <pre className="max-h-[60vh] overflow-auto p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">{text}</pre>
  );
}

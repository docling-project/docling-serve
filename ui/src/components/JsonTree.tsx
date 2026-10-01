import { ChevronRight } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

/** A small collapsible JSON viewer. Nodes deeper than `openDepth` start closed. */
export function JsonTree({ value, openDepth = 1 }: { value: unknown; openDepth?: number }) {
  return (
    <div className="font-mono text-xs leading-relaxed">
      <Node value={value} depth={0} openDepth={openDepth} />
    </div>
  );
}

function Node({
  name,
  value,
  depth,
  openDepth,
}: {
  name?: string;
  value: unknown;
  depth: number;
  openDepth: number;
}) {
  const [open, setOpen] = useState(depth < openDepth);
  const isArray = Array.isArray(value);
  const isObject = value !== null && typeof value === "object";
  const label = name !== undefined && <span className="text-primary">{JSON.stringify(name)}: </span>;

  if (!isObject) {
    return (
      <div style={{ paddingLeft: depth ? 16 : 0 }}>
        {label}
        <Scalar value={value} />
      </div>
    );
  }

  const entries = isArray
    ? (value as unknown[]).map((item, index) => [String(index), item] as const)
    : Object.entries(value as Record<string, unknown>);
  const summary = isArray ? `[${entries.length}]` : `{${entries.length}}`;
  // Very large nodes are truncated to keep the page responsive.
  const shown = entries.slice(0, 500);

  return (
    <div style={{ paddingLeft: depth ? 16 : 0 }}>
      <button
        type="button"
        className="inline-flex items-center gap-0.5 rounded hover:bg-muted"
        onClick={() => setOpen((current) => !current)}
      >
        <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} />
        {label}
        <span className="text-muted-foreground">{summary}</span>
      </button>
      {open && (
        <div className="border-l border-border">
          {shown.map(([key, item]) => (
            <Node
              key={key}
              name={isArray ? undefined : key}
              value={item}
              depth={depth + 1}
              openDepth={openDepth}
            />
          ))}
          {entries.length > shown.length && (
            <div className="pl-4 text-muted-foreground">… {entries.length - shown.length} more</div>
          )}
        </div>
      )}
    </div>
  );
}

function Scalar({ value }: { value: unknown }) {
  if (typeof value === "string") {
    const text = value.length > 300 ? `${value.slice(0, 300)}…` : value;
    return <span className="break-all text-success">{JSON.stringify(text)}</span>;
  }
  if (typeof value === "number") return <span className="text-warning">{value}</span>;
  if (typeof value === "boolean") return <span className="text-brand">{String(value)}</span>;
  return <span className="text-muted-foreground">null</span>;
}

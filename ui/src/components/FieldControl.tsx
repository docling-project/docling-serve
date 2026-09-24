import { Info } from "lucide-react";
import { useEffect, useState } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { humanize } from "@/lib/capabilities";
import { asArray } from "@/lib/options";
import type { FieldSpec } from "@/lib/schema";
import { cn } from "@/lib/utils";

const UNSET = "__unset__";
// Pydantic's sys.maxsize page limit: shown as an empty "to" field.
const MAX_INT = 9223372036854775807;

export function FieldLabel({ field, htmlFor }: { field: FieldSpec; htmlFor?: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <Label htmlFor={htmlFor} className="text-sm font-medium">
        {humanize(field.name)}
      </Label>
      {field.description && (
        <Tooltip>
          <TooltipTrigger asChild>
            <Info className="size-3.5 cursor-help text-muted-foreground" aria-label="Description" />
          </TooltipTrigger>
          <TooltipContent className="max-w-xs text-xs leading-relaxed">{field.description}</TooltipContent>
        </Tooltip>
      )}
    </div>
  );
}

interface Props {
  field: FieldSpec;
  value: unknown;
  onChange: (value: unknown) => void;
}

export function FieldControl({ field, value, onChange }: Props) {
  const id = `field-${field.name}`;

  if (field.control === "boolean") {
    return (
      <div className="flex items-center justify-between gap-3 py-1">
        <FieldLabel field={field} htmlFor={id} />
        <Switch id={id} checked={value === true} onCheckedChange={(checked) => onChange(checked)} />
      </div>
    );
  }

  return (
    <div className="space-y-1.5">
      <FieldLabel field={field} htmlFor={id} />
      <FieldInput id={id} field={field} value={value} onChange={onChange} />
    </div>
  );
}

function FieldInput({ id, field, value, onChange }: Props & { id: string }) {
  switch (field.control) {
    case "select":
      return (
        <Select
          value={value == null ? UNSET : String(value)}
          onValueChange={(next) => onChange(next === UNSET ? null : next)}
        >
          <SelectTrigger id={id} className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {field.nullable && <SelectItem value={UNSET}>Not set</SelectItem>}
            {field.options?.map((option) => (
              <SelectItem key={option} value={option}>
                {option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      );
    case "multiselect":
      return <ChipSelect options={field.options ?? []} value={asArray(value)} onChange={onChange} />;
    case "number":
    case "integer":
      return (
        <Input
          id={id}
          type="number"
          step={field.control === "integer" ? 1 : "any"}
          min={field.minimum}
          max={field.maximum}
          value={value == null ? "" : String(value)}
          placeholder={field.nullable ? "Not set" : undefined}
          onChange={(event) => {
            const raw = event.target.value;
            if (raw === "") return onChange(field.nullable ? null : field.default);
            const number = Number(raw);
            onChange(field.maximum !== undefined ? Math.min(number, field.maximum) : number);
          }}
        />
      );
    case "text":
      return (
        <Input id={id} value={value == null ? "" : String(value)} onChange={(e) => onChange(e.target.value)} />
      );
    case "string-list":
      return (
        <Input
          id={id}
          placeholder="Comma separated"
          value={asArray(value).join(", ")}
          onChange={(event) => {
            const items = event.target.value
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean);
            onChange(items.length > 0 ? items : field.nullable ? null : []);
          }}
        />
      );
    case "range":
      return <RangeInput id={id} value={asArray(value)} onChange={onChange} />;
    default:
      return <JsonInput id={id} value={value} onChange={onChange} />;
  }
}

export function ChipSelect({
  options,
  value,
  onChange,
  highlight,
}: {
  options: string[];
  value: unknown[];
  onChange: (value: string[]) => void;
  highlight?: string;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((option) => {
        const selected = value.includes(option);
        return (
          <button
            key={option}
            type="button"
            aria-pressed={selected}
            onClick={() =>
              onChange(
                selected
                  ? value.filter((item) => item !== option).map(String)
                  : [...value.map(String), option],
              )
            }
            className={cn(
              "rounded-md border px-2.5 py-1 font-mono text-xs transition-colors",
              selected
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input bg-background text-muted-foreground hover:bg-accent hover:text-accent-foreground",
              option === highlight && !selected && "border-brand/60",
            )}
          >
            {option}
          </button>
        );
      })}
    </div>
  );
}

function RangeInput({
  id,
  value,
  onChange,
}: {
  id: string;
  value: unknown[];
  onChange: (value: unknown) => void;
}) {
  const from = Number(value[0] ?? 1);
  const to = Number(value[1] ?? MAX_INT);
  return (
    <div className="flex items-center gap-2">
      <Input
        id={id}
        type="number"
        min={1}
        value={from}
        onChange={(e) => onChange([Math.max(1, Number(e.target.value) || 1), to])}
      />
      <span className="text-sm text-muted-foreground">to</span>
      <Input
        type="number"
        min={1}
        placeholder="end"
        value={to >= MAX_INT ? "" : to}
        onChange={(e) => onChange([from, e.target.value === "" ? MAX_INT : Number(e.target.value)])}
      />
    </div>
  );
}

function JsonInput({
  id,
  value,
  onChange,
}: {
  id: string;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const [text, setText] = useState(() => (value == null ? "" : JSON.stringify(value, null, 2)));
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (value == null) setText("");
  }, [value]);

  return (
    <div className="space-y-1">
      <Textarea
        id={id}
        className="min-h-24 font-mono text-xs"
        placeholder="JSON (optional)"
        value={text}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          if (next.trim() === "") {
            setError(null);
            onChange(null);
            return;
          }
          try {
            onChange(JSON.parse(next));
            setError(null);
          } catch {
            setError("Invalid JSON");
          }
        }}
      />
      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  );
}

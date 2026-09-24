import {
  type ConvertDocumentResponse,
  DoclingHttpError,
  type PresignedUrlConvertResponse,
  type TaskStatusResponse,
} from "@docling/docling-client";
import { Copy, FileText, FileUp, Link2, Loader2, Play, RotateCcw, Square } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { OptionsForm } from "@/components/OptionsForm";
import { ResultView } from "@/components/ResultView";
import { SavedOptions } from "@/components/SavedOptions";
import { type Source, SourceInput } from "@/components/SourceInput";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { createClient } from "@/lib/api";
import {
  availableTargets,
  type Capabilities,
  type ResultTarget,
  TARGET_LABELS,
} from "@/lib/capabilities";
import { asArray, buildFormModel, type OptionValues, requestOptions } from "@/lib/options";
import { type ConversionOutcome, fromInBody, fromPresigned, fromZip } from "@/lib/results";
import type { FieldSpec } from "@/lib/schema";
import { curlSnippet, pythonSnippet, type RequestDescription } from "@/lib/snippets";
import { cn } from "@/lib/utils";

/** One-click sources shown while no conversion has run yet. */
const EXAMPLE_URLS = [
  { url: "https://arxiv.org/pdf/2501.17887", title: "Docling: An Efficient Open-Source Toolkit for AI-driven Document Conversion" },
  { url: "https://arxiv.org/pdf/2206.01062", title: "DocLayNet: A Large Human-Annotated Dataset for Document-Layout Analysis" },
];

type RunState =
  | { phase: "idle" }
  | { phase: "running"; status?: TaskStatusResponse }
  | { phase: "done"; outcome: ConversionOutcome; formats: string[] }
  | { phase: "error"; message: string };

interface Props {
  capabilities: Capabilities | null;
  fields: FieldSpec[];
}

export function ConvertView({ capabilities, fields }: Props) {
  const model = useMemo(() => buildFormModel(fields, capabilities), [fields, capabilities]);
  const targets = availableTargets(capabilities);
  const [values, setValues] = useState<OptionValues>(model.defaults);
  const [source, setSource] = useState<Source | null>(null);
  const [target, setTarget] = useState<ResultTarget>(targets[0] ?? "inbody");
  const [run, setRun] = useState<RunState>({ phase: "idle" });
  const abort = useRef<AbortController | null>(null);

  useEffect(() => setValues(model.defaults), [model]);
  const dragging = usePageFileDrop((file) => setSource({ kind: "file", file }));

  const options = requestOptions(fields, values, model);
  const description: RequestDescription | null = source && {
    source: source.kind === "file" ? { kind: "file", filename: source.file.name } : source,
    options,
    target,
    apiKeyRequired: capabilities?.features.api_key_required ?? false,
  };

  const convert = async () => {
    if (!source) return;
    const controller = new AbortController();
    abort.current = controller;
    const formats = asArray(options.to_formats).map(String);
    setRun({ phase: "running" });

    try {
      const client = createClient();
      const input =
        source.kind === "file" ? { data: source.file, filename: source.file.name } : source.url;
      const job = await client.submitSource(input, {
        options,
        target: { kind: target },
        signal: controller.signal,
      });
      let last: TaskStatusResponse = job.status;
      setRun({ phase: "running", status: last });
      for await (const status of job.watch({ signal: controller.signal })) {
        last = status;
        setRun({ phase: "running", status });
      }
      if (last.task_status === "failure") {
        throw new Error(last.failure?.message ?? last.error_message ?? "The conversion failed.");
      }

      let outcome: ConversionOutcome;
      if (target === "zip") {
        const result = await client.getBinaryResult(job.taskId, { signal: controller.signal });
        outcome = fromZip(result, source.kind === "file" ? source.file.name : source.url);
      } else if (target === "presigned_url") {
        const result = await client.getRawResult<PresignedUrlConvertResponse>(job.taskId, {
          signal: controller.signal,
        });
        outcome = fromPresigned(result);
      } else {
        const result = await client.getResult(job.taskId, { signal: controller.signal });
        outcome = fromInBody(result as ConvertDocumentResponse);
      }
      setRun({ phase: "done", outcome, formats });
    } catch (error) {
      if (controller.signal.aborted) {
        setRun({ phase: "idle" });
        return;
      }
      setRun({ phase: "error", message: errorMessage(error) });
    } finally {
      abort.current = null;
    }
  };

  const copy = async (text: string, label: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast.success(`${label} copied to the clipboard`);
    } catch {
      toast.error("Could not access the clipboard");
    }
  };

  const running = run.phase === "running";

  return (
    <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[minmax(22rem,28rem)_minmax(0,1fr)]">
      {dragging && <DropOverlay />}
      <Card className="min-w-0 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)] lg:overflow-auto">
        <CardHeader>
          <CardTitle className="text-base">Input</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <SourceInput source={source} onChange={setSource} maxFileSize={capabilities?.limits.max_file_size} />
          <Separator />
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Options</h3>
            <div className="flex items-center gap-1">
              <SavedOptions values={values} onLoad={(saved) => setValues({ ...model.defaults, ...saved })} />
              <Button variant="ghost" size="sm" onClick={() => setValues(model.defaults)}>
                <RotateCcw className="size-3.5" /> Reset
              </Button>
            </div>
          </div>
          <OptionsForm
            model={model}
            values={values}
            onChange={(name, value) => setValues((current) => ({ ...current, [name]: value }))}
          />
          <Separator />
          <div className="space-y-1.5">
            <Label htmlFor="target">Result delivery</Label>
            <Select value={target} onValueChange={(value) => setTarget(value as ResultTarget)}>
              <SelectTrigger id="target" className="w-full">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {targets.map((item) => (
                  <SelectItem key={item} value={item}>
                    {TARGET_LABELS[item]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex gap-2">
            {running ? (
              <Button className="flex-1" variant="outline" onClick={() => abort.current?.abort()}>
                <Square className="size-4" /> Stop waiting
              </Button>
            ) : (
              <Button className="flex-1" disabled={!source} onClick={() => void convert()}>
                <Play className="size-4" /> Convert
              </Button>
            )}
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              className="flex-1"
              disabled={!description}
              onClick={() => description && void copy(curlSnippet(description), "curl command")}
            >
              <Copy className="size-3.5" /> Copy as curl
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="flex-1"
              disabled={!description}
              onClick={() => description && void copy(pythonSnippet(description), "Python snippet")}
            >
              <Copy className="size-3.5" /> Copy as Python
            </Button>
          </div>
        </CardContent>
      </Card>

      <Card className="min-h-[60vh] min-w-0">
        <CardHeader>
          <CardTitle className="text-base">Result</CardTitle>
        </CardHeader>
        <CardContent>
          {run.phase === "idle" && (
            <EmptyState
              selected={source?.kind === "http" ? source.url : undefined}
              onPick={(url) => setSource({ kind: "http", url })}
            />
          )}
          {run.phase === "running" && <Progress status={run.status} />}
          {run.phase === "error" && (
            <Alert variant="destructive">
              <AlertTitle>Conversion failed</AlertTitle>
              <AlertDescription className="whitespace-pre-wrap">{run.message}</AlertDescription>
            </Alert>
          )}
          {run.phase === "done" && <ResultView outcome={run.outcome} requestedFormats={run.formats} />}
        </CardContent>
      </Card>
    </div>
  );
}

function errorMessage(error: unknown): string {
  if (error instanceof DoclingHttpError && error.status === 401) {
    return "The server rejected the request: an API key is required. Set it in the header.";
  }
  return error instanceof Error ? error.message : String(error);
}

function EmptyState({ selected, onPick }: { selected?: string; onPick: (url: string) => void }) {
  return (
    <div className="flex min-h-[45vh] flex-col items-center justify-center gap-5 text-center text-muted-foreground">
      <FileText className="size-10 text-brand-soft" />
      <p className="max-w-sm text-sm">
        Drop a file anywhere on the page, pick a URL, adjust the options and press <strong>Convert</strong>. The
        outputs, including the <code className="font-mono">.dclx</code> archive, show up here.
      </p>
      <div className="w-full max-w-lg space-y-2">
        <p className="text-xs font-medium tracking-wide uppercase">Or try an example</p>
        {EXAMPLE_URLS.map((example) => (
          <button
            key={example.url}
            type="button"
            onClick={() => onPick(example.url)}
            aria-pressed={selected === example.url}
            className={cn(
              "flex w-full items-center gap-3 rounded-lg border p-3 text-left transition-colors hover:border-brand/60 hover:bg-muted",
              selected === example.url && "border-primary bg-accent",
            )}
          >
            <Link2 className="size-4 shrink-0 text-brand" />
            <span className="min-w-0">
              <span className="block truncate text-sm font-medium text-foreground">{example.title}</span>
              <span className="block truncate font-mono text-xs">{example.url}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

/** Tracks files dragged over the whole page and hands a dropped file to `onDrop`. */
function usePageFileDrop(onDrop: (file: File) => void): boolean {
  const [dragging, setDragging] = useState(false);
  const handler = useRef(onDrop);
  handler.current = onDrop;

  useEffect(() => {
    let depth = 0;
    const hasFiles = (event: DragEvent) => event.dataTransfer?.types.includes("Files") ?? false;
    const enter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth += 1;
      setDragging(true);
    };
    const over = (event: DragEvent) => {
      if (hasFiles(event)) event.preventDefault();
    };
    const leave = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };
    const drop = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setDragging(false);
      const file = event.dataTransfer?.files[0];
      if (file) handler.current(file);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", over);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", over);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, []);

  return dragging;
}

function DropOverlay() {
  return (
    <div className="pointer-events-none fixed inset-0 z-50 flex items-center justify-center bg-background/80 p-6 backdrop-blur-sm">
      <div className="flex flex-col items-center gap-3 rounded-2xl border-2 border-dashed border-brand bg-card px-12 py-10 text-center shadow-lg">
        <FileUp className="size-10 text-brand" />
        <p className="text-lg font-semibold">Drop to convert</p>
        <p className="text-sm text-muted-foreground">The file becomes the input of the next conversion.</p>
      </div>
    </div>
  );
}

function Progress({ status }: { status?: TaskStatusResponse }) {
  const meta = status?.task_meta;
  return (
    <div className="flex min-h-[45vh] flex-col items-center justify-center gap-3 text-center">
      <Loader2 className="size-8 animate-spin text-brand" />
      <p className="text-sm font-medium">
        {status ? `Task ${status.task_status}` : "Submitting…"}
        {status?.task_position ? ` · position ${status.task_position} in queue` : ""}
      </p>
      {meta && meta.num_docs > 0 && (
        <p className="text-xs text-muted-foreground">
          {meta.num_processed} of {meta.num_docs} documents processed
        </p>
      )}
      {status && <p className="font-mono text-xs text-muted-foreground">{status.task_id}</p>}
    </div>
  );
}

import { Info } from "lucide-react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatBytes } from "@/components/SourceInput";
import { type Capabilities, stageLabel } from "@/lib/capabilities";

export function ServerPanel({ capabilities }: { capabilities: Capabilities | null }) {
  if (!capabilities) {
    return (
      <Alert>
        <Info className="size-4" />
        <AlertTitle>Capabilities are not published</AlertTitle>
        <AlertDescription>
          This deployment disabled <code>/v1/capabilities</code>. The options form is built from the API
          schema only, so some presets may be rejected by the server.
        </AlertDescription>
      </Alert>
    );
  }

  const { limits, features } = capabilities;
  const facts: [string, string][] = [
    ["Max sources per request", String(limits.max_sources_per_request)],
    ["Max file size", limits.max_file_size ? formatBytes(limits.max_file_size) : "unlimited"],
    ["Max pages", limits.max_num_pages ? String(limits.max_num_pages) : "unlimited"],
    ["Max images scale", String(limits.max_images_scale)],
    ["Max document timeout", `${Math.round(limits.max_document_timeout / 60)} min`],
    ["API key", features.api_key_required ? "required" : "not required"],
    ["Artifact storage", features.artifact_storage ? "enabled" : "disabled"],
  ];

  return (
    <div className="space-y-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Limits and features</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-sm">
              {facts.map(([label, value]) => (
                <div key={label} className="contents">
                  <dt className="text-muted-foreground">{label}</dt>
                  <dd className="text-right font-medium">{value}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Sources and targets</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3 text-sm">
            <BadgeList label="Sources" items={capabilities.sources} />
            <BadgeList
              label="Targets"
              items={capabilities.targets.allowed}
              highlight={capabilities.targets.default}
            />
            <BadgeList label="Image export modes" items={capabilities.image_export_modes} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Versions</CardTitle>
          </CardHeader>
          <CardContent>
            {capabilities.versions ? (
              <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1.5 text-sm">
                {Object.entries(capabilities.versions).map(([name, version]) => (
                  <div key={name} className="contents">
                    <dt className="text-muted-foreground">{name}</dt>
                    <dd className="text-right font-mono text-xs">{version}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <p className="text-sm text-muted-foreground">Hidden by the server configuration.</p>
            )}
          </CardContent>
        </Card>
      </div>

      <div>
        <h2 className="mb-3 text-lg font-semibold">Models and presets</h2>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {Object.entries(capabilities.stages).map(([stage, info]) => (
            <Card key={stage}>
              <CardHeader>
                <CardTitle className="text-base">{stageLabel(stage)}</CardTitle>
                <CardDescription className="font-mono text-xs">
                  {info.option} · default: {info.default}
                  {info.custom_config_option ? ` · ${info.custom_config_option} allowed` : ""}
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="space-y-2">
                  {info.presets.map((preset) => (
                    <li key={preset.id} className="text-sm">
                      <div className="flex items-center gap-2">
                        <span className="font-medium">{preset.name}</span>
                        {preset.name !== preset.id && (
                          <span className="font-mono text-xs text-muted-foreground">{preset.id}</span>
                        )}
                        {preset.source === "custom" && <Badge variant="secondary">custom</Badge>}
                      </div>
                      {preset.description && (
                        <p className="text-xs leading-relaxed text-muted-foreground">{preset.description}</p>
                      )}
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </div>
  );
}

function BadgeList({ label, items, highlight }: { label: string; items: string[]; highlight?: string }) {
  return (
    <div className="space-y-1.5">
      <p className="text-muted-foreground">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {items.map((item) => (
          <Badge key={item} variant={item === highlight ? "default" : "outline"} className="font-mono text-xs">
            {item}
            {item === highlight ? " (default)" : ""}
          </Badge>
        ))}
      </div>
    </div>
  );
}

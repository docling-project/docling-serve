import { Settings2, Sparkles } from "lucide-react";

import { ChipSelect, FieldControl, FieldLabel } from "@/components/FieldControl";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { stageLabel } from "@/lib/capabilities";
import { asArray, type FormModel, type OptionValues, type StageModel } from "@/lib/options";

interface Props {
  model: FormModel;
  values: OptionValues;
  onChange: (name: string, value: unknown) => void;
}

export function OptionsForm({ model, values, onChange }: Props) {
  const formats = model.output.find((field) => field.name === "to_formats");
  const otherOutput = model.output.filter((field) => field.name !== "to_formats");

  return (
    <div className="space-y-5">
      {formats && (
        <section className="space-y-2">
          <FieldLabel field={formats} />
          <ChipSelect
            options={formats.options ?? []}
            value={asArray(values.to_formats)}
            onChange={(next) => onChange("to_formats", next)}
            highlight="dclx"
          />
        </section>
      )}

      {otherOutput.map((field) => (
        <FieldControl
          key={field.name}
          field={field}
          value={values[field.name]}
          onChange={(value) => onChange(field.name, value)}
        />
      ))}

      {model.pipeline && (
        <FieldControl
          field={model.pipeline}
          value={values.pipeline}
          onChange={(value) => onChange("pipeline", value)}
        />
      )}

      <Accordion type="multiple" defaultValue={["models"]} className="rounded-lg border">
        <AccordionItem value="models" className="px-3">
          <AccordionTrigger className="text-sm">
            <span className="flex items-center gap-2">
              <Sparkles className="size-4 text-brand" /> Models and presets
            </span>
          </AccordionTrigger>
          <AccordionContent className="space-y-4">
            {model.stages.map((stage) => (
              <StageControl key={stage.stage} stage={stage} values={values} onChange={onChange} />
            ))}
          </AccordionContent>
        </AccordionItem>
        <AccordionItem value="advanced" className="px-3">
          <AccordionTrigger className="text-sm">
            <span className="flex items-center gap-2">
              <Settings2 className="size-4 text-muted-foreground" /> All other options
            </span>
          </AccordionTrigger>
          <AccordionContent className="space-y-4">
            {model.advanced.map((field) => (
              <FieldControl
                key={field.name}
                field={field}
                value={values[field.name]}
                onChange={(value) => onChange(field.name, value)}
              />
            ))}
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  );
}

function StageControl({
  stage,
  values,
  onChange,
}: {
  stage: StageModel;
  values: OptionValues;
  onChange: (name: string, value: unknown) => void;
}) {
  const active = stage.isActive(values);
  const option = stage.capabilities.option;
  const presets = stage.capabilities.presets;
  const selected = String(values[option] ?? "default");
  const selectedPreset = presets.find((preset) => preset.id === selected);

  return (
    <div className="space-y-2 rounded-md border border-dashed p-3 data-[active=false]:opacity-60" data-active={active}>
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold">{stageLabel(stage.stage)}</span>
        {!active && <Badge variant="outline">inactive</Badge>}
      </div>

      {stage.toggles.map((toggle) => (
        <FieldControl
          key={toggle.name}
          field={toggle}
          value={values[toggle.name]}
          onChange={(value) => onChange(toggle.name, value)}
        />
      ))}

      {stage.presetField &&
        (presets.length > 0 ? (
          <div className="space-y-1">
            <Select value={selected} onValueChange={(value) => onChange(option, value)} disabled={!active}>
              <SelectTrigger className="w-full" aria-label={`${stageLabel(stage.stage)} preset`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {presets.map((preset) => (
                  <SelectItem key={preset.id} value={preset.id}>
                    <span>{preset.name}</span>
                    {preset.source === "custom" && (
                      <span className="text-xs text-muted-foreground">custom</span>
                    )}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {selectedPreset?.description && (
              <p className="text-xs leading-relaxed text-muted-foreground">{selectedPreset.description}</p>
            )}
          </div>
        ) : (
          <Input
            aria-label={`${stageLabel(stage.stage)} preset`}
            value={selected}
            disabled={!active}
            onChange={(event) => onChange(option, event.target.value)}
          />
        ))}

      {stage.customField && active && (
        <FieldControl
          field={stage.customField}
          value={values[stage.customField.name]}
          onChange={(value) => onChange(stage.customField!.name, value)}
        />
      )}
    </div>
  );
}

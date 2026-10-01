import type { Capabilities, StageCapabilities } from "./capabilities";
import type { FieldSpec } from "./schema";

export type OptionValues = Record<string, unknown>;

export interface StageModel {
  stage: string;
  capabilities: StageCapabilities;
  presetField?: FieldSpec;
  customField?: FieldSpec;
  /** Boolean options that switch this stage on. */
  toggles: FieldSpec[];
  /** Whether the stage applies given the current values. */
  isActive: (values: OptionValues) => boolean;
}

export interface FormModel {
  output: FieldSpec[];
  pipeline?: FieldSpec;
  stages: StageModel[];
  advanced: FieldSpec[];
  defaults: OptionValues;
}

/** Output formats preselected in the UI, with the dclx archive first. */
const PREFERRED_FORMATS = ["dclx", "md", "json", "html"];

const OUTPUT_FIELDS = ["to_formats", "image_export_mode"];

// UI hints: which boolean option enables a stage. Stages without an entry are
// always shown.
const STAGE_TOGGLES: Record<string, string[]> = {
  ocr: ["do_ocr"],
  table_structure: ["do_table_structure"],
  picture_description: ["do_picture_description"],
  picture_classification: ["do_picture_classification"],
  chart_extraction: ["do_chart_extraction"],
  code_formula: ["do_code_enrichment", "do_formula_enrichment"],
};

const STAGE_CONDITIONS: Record<string, (values: OptionValues) => boolean> = {
  vlm_pipeline: (values) => values.pipeline === "vlm",
  chunking: (values) => asArray(values.to_formats).includes("chunks"),
};

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function restrict(field: FieldSpec, allowed: string[] | undefined): FieldSpec {
  if (!allowed || !field.options) return field;
  return { ...field, options: field.options.filter((option) => allowed.includes(option)) };
}

/** Stages advertised by the server, or guessed from `*_preset` fields without it. */
function stageCapabilities(
  fields: FieldSpec[],
  capabilities: Capabilities | null,
): [string, StageCapabilities][] {
  if (capabilities) return Object.entries(capabilities.stages);
  return fields
    .filter((field) => field.name.endsWith("_preset"))
    .map((field) => {
      const stage = field.name.replace(/_preset$/, "");
      const custom = `${stage}_custom_config`;
      return [
        stage,
        {
          option: field.name,
          custom_config_option: fields.some((f) => f.name === custom) ? custom : null,
          default: "default",
          presets: [],
        },
      ];
    });
}

export function buildFormModel(fields: FieldSpec[], capabilities: Capabilities | null): FormModel {
  const byName = new Map(fields.map((field) => [field.name, field]));
  const used = new Set<string>();
  const take = (name: string) => {
    const field = byName.get(name);
    if (field) used.add(name);
    return field;
  };

  const output = OUTPUT_FIELDS.map(take)
    .filter((field): field is FieldSpec => field !== undefined)
    .map((field) => {
      if (field.name === "to_formats") return restrict(field, capabilities?.output_formats);
      if (field.name === "image_export_mode") {
        return restrict(field, capabilities?.image_export_modes);
      }
      return field;
    });

  const pipeline = take("pipeline");

  const stages: StageModel[] = stageCapabilities(fields, capabilities).map(([stage, caps]) => {
    const toggles = (STAGE_TOGGLES[stage] ?? [])
      .map(take)
      .filter((field): field is FieldSpec => field !== undefined);
    const condition = STAGE_CONDITIONS[stage];
    const presetField = take(caps.option);
    // The custom config field is always hidden from "advanced"; it is only
    // offered when the server allows it.
    const customName = `${caps.option.replace(/_preset$/, "")}_custom_config`;
    const customField = byName.get(customName);
    if (customField) used.add(customName);
    return {
      stage,
      capabilities: caps,
      presetField,
      customField: caps.custom_config_option ? customField : undefined,
      toggles,
      isActive: (values) => {
        if (condition && !condition(values)) return false;
        if (toggles.length === 0) return true;
        return toggles.some((toggle) => values[toggle.name] === true);
      },
    };
  });

  const limits = capabilities?.limits;
  const advanced = fields
    .filter((field) => !used.has(field.name))
    .map((field) => {
      if (field.name === "images_scale" && limits) {
        return { ...field, maximum: limits.max_images_scale };
      }
      if (field.name === "document_timeout" && limits) {
        return { ...field, maximum: limits.max_document_timeout };
      }
      return field;
    });

  const defaults: OptionValues = {};
  for (const field of fields) {
    if (field.default !== undefined) defaults[field.name] = field.default;
  }
  const formats = output.find((field) => field.name === "to_formats")?.options ?? [];
  const preferred = PREFERRED_FORMATS.filter((format) => formats.includes(format));
  if (preferred.length > 0) defaults.to_formats = preferred;
  for (const stage of stages) {
    if (!stage.presetField) continue;
    const { presets, default: serverDefault } = stage.capabilities;
    const hasDefault = presets.length === 0 || presets.some((preset) => preset.id === "default");
    defaults[stage.capabilities.option] = hasDefault ? "default" : serverDefault;
  }
  const imageModes = output.find((field) => field.name === "image_export_mode")?.options;
  // The DocLang viewer shows the page images stored in the .dclx, which the
  // server only adds with page images on and a non-placeholder image mode.
  // "referenced" keeps the images out of the Markdown/HTML text.
  if (imageModes?.includes("referenced")) defaults.image_export_mode = "referenced";
  if (byName.has("include_page_images")) defaults.include_page_images = true;
  if (imageModes && !imageModes.includes(String(defaults.image_export_mode))) {
    defaults.image_export_mode = imageModes[0];
  }

  return { output, pipeline, stages, advanced, defaults };
}

/**
 * The options sent to the server: only values that differ from the schema
 * defaults, plus the output formats. Keeps requests (and snippets) readable.
 */
export function requestOptions(
  fields: FieldSpec[],
  values: OptionValues,
  model: FormModel,
): OptionValues {
  const schemaDefaults = new Map(fields.map((field) => [field.name, field.default]));
  const hiddenStages = new Set(
    model.stages.filter((stage) => !stage.isActive(values)).map((stage) => stage.capabilities.option),
  );
  const options: OptionValues = {};
  for (const [name, value] of Object.entries(values)) {
    if (value === undefined || value === "") continue;
    if (hiddenStages.has(name)) continue;
    if (name !== "to_formats" && JSON.stringify(value) === JSON.stringify(schemaDefaults.get(name))) {
      continue;
    }
    options[name] = value;
  }
  for (const stage of model.stages) {
    // An omitted preset (schema default null) already resolves to the server
    // default, so "default" is only sent where the schema default differs.
    const option = stage.capabilities.option;
    if (options[option] === "default" && schemaDefaults.get(option) == null) delete options[option];
    // A custom config replaces the preset: the server rejects both together.
    const custom = stage.customField?.name;
    if (custom && options[custom] != null) delete options[option];
    if (custom && !stage.isActive(values)) delete options[custom];
  }
  return options;
}

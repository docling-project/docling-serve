/** Mirrors `docling_serve.capabilities.CapabilitiesResponse`. */
export interface PresetInfo {
  id: string;
  name: string;
  description?: string | null;
  source: "default" | "docling" | "custom";
}

export interface StageCapabilities {
  option: string;
  custom_config_option?: string | null;
  default: string;
  presets: PresetInfo[];
}

export interface Capabilities {
  versions?: Record<string, string> | null;
  stages: Record<string, StageCapabilities>;
  sources: string[];
  targets: { allowed: string[]; default: string };
  output_formats: string[];
  image_export_modes: string[];
  limits: {
    max_document_timeout: number;
    max_images_scale: number;
    max_sources_per_request: number;
    max_num_pages?: number | null;
    max_file_size?: number | null;
  };
  features: {
    api_key_required: boolean;
    artifact_storage: boolean;
    websocket: boolean;
  };
}

/** Targets the UI knows how to display, in order of preference. */
export const RESULT_TARGETS = ["presigned_url", "zip", "inbody"] as const;
export type ResultTarget = (typeof RESULT_TARGETS)[number];

export const TARGET_LABELS: Record<ResultTarget, string> = {
  presigned_url: "Presigned URLs",
  zip: "Zip archive",
  inbody: "Inline JSON",
};

export function availableTargets(capabilities: Capabilities | null): ResultTarget[] {
  if (!capabilities) return [...RESULT_TARGETS];
  return RESULT_TARGETS.filter((target) => {
    if (!capabilities.targets.allowed.includes(target)) return false;
    return target !== "presigned_url" || capabilities.features.artifact_storage;
  });
}

const ACRONYMS: Record<string, string> = { ocr: "OCR", vlm: "VLM" };

export function stageLabel(stage: string): string {
  const name = stage.replace(/_pipeline$/, "");
  return ACRONYMS[name] ?? humanize(name);
}

export function humanize(name: string): string {
  const words = name.replace(/_/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

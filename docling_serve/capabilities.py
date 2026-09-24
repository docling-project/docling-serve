"""Public description of what a docling-serve deployment allows.

The capabilities document is consumed by the web UI (and any other client) to
render only the options, presets and targets the deployment accepts. It must
never leak admin configuration: custom presets are exposed by id only, and no
model repository, engine option, endpoint or credential is included.
"""

import logging
import sys
from collections.abc import Callable, Mapping
from functools import lru_cache
from typing import Any, Literal

from pydantic import BaseModel, Field

from docling.datamodel.base_models import OutputFormat

from docling_serve.policy import ServicePolicy, resolve_default_target
from docling_serve.settings import DoclingServeSettings

_log = logging.getLogger(__name__)


class PresetInfo(BaseModel):
    id: str
    name: str
    description: str | None = None
    source: Literal["default", "docling", "custom"]


class StageCapabilities(BaseModel):
    option: str = Field(description="Request option selecting the preset.")
    custom_config_option: str | None = Field(
        default=None,
        description="Request option accepting a custom config, if the admin allows it.",
    )
    default: str = Field(description="Preset id that 'default' resolves to.")
    presets: list[PresetInfo]


class TargetCapabilities(BaseModel):
    allowed: list[str]
    default: str


class LimitsCapabilities(BaseModel):
    max_document_timeout: float
    max_images_scale: float
    max_sources_per_request: int
    max_num_pages: int | None = None
    max_file_size: int | None = None


class FeatureCapabilities(BaseModel):
    api_key_required: bool
    artifact_storage: bool
    websocket: bool = True


class CapabilitiesResponse(BaseModel):
    versions: dict[str, str] | None = None
    stages: dict[str, StageCapabilities]
    sources: list[str]
    targets: TargetCapabilities
    output_formats: list[str]
    image_export_modes: list[str]
    limits: LimitsCapabilities
    features: FeatureCapabilities


class _StageSpec(BaseModel):
    registry: str
    option: str
    custom_config_option: str | None = None
    allow_custom_setting: str | None = None
    default_setting: str
    custom_setting: str
    presets_class: str | None = None


# Stage name -> where its presets live in the converter manager and which
# request options select them. Adding a stage here is enough for the UI to pick
# it up.
_STAGES: dict[str, _StageSpec] = {
    "ocr": _StageSpec(
        registry="ocr_preset_registry",
        option="ocr_preset",
        custom_config_option="ocr_custom_config",
        allow_custom_setting="allow_custom_ocr_config",
        default_setting="default_ocr_preset",
        custom_setting="custom_ocr_presets",
    ),
    "layout": _StageSpec(
        registry="layout_preset_registry",
        option="layout_preset",
        custom_config_option="layout_custom_config",
        allow_custom_setting="allow_custom_layout_config",
        default_setting="default_layout_preset",
        custom_setting="custom_layout_presets",
        presets_class="LayoutObjectDetectionOptions",
    ),
    "table_structure": _StageSpec(
        registry="table_structure_preset_registry",
        option="table_structure_preset",
        custom_config_option="table_structure_custom_config",
        allow_custom_setting="allow_custom_table_structure_config",
        default_setting="default_table_structure_preset",
        custom_setting="custom_table_structure_presets",
    ),
    "vlm_pipeline": _StageSpec(
        registry="vlm_preset_registry",
        option="vlm_pipeline_preset",
        custom_config_option="vlm_pipeline_custom_config",
        allow_custom_setting="allow_custom_vlm_config",
        default_setting="default_vlm_preset",
        custom_setting="custom_vlm_presets",
        presets_class="VlmConvertOptions",
    ),
    "picture_description": _StageSpec(
        registry="picture_description_preset_registry",
        option="picture_description_preset",
        custom_config_option="picture_description_custom_config",
        allow_custom_setting="allow_custom_picture_description_config",
        default_setting="default_picture_description_preset",
        custom_setting="custom_picture_description_presets",
        presets_class="PictureDescriptionVlmEngineOptions",
    ),
    "picture_classification": _StageSpec(
        registry="picture_classification_preset_registry",
        option="picture_classification_preset",
        custom_config_option="picture_classification_custom_config",
        allow_custom_setting="allow_custom_picture_classification_config",
        default_setting="default_picture_classification_preset",
        custom_setting="custom_picture_classification_presets",
        presets_class="DocumentPictureClassifierOptions",
    ),
    "code_formula": _StageSpec(
        registry="code_formula_preset_registry",
        option="code_formula_preset",
        custom_config_option="code_formula_custom_config",
        allow_custom_setting="allow_custom_code_formula_config",
        default_setting="default_code_formula_preset",
        custom_setting="custom_code_formula_presets",
        presets_class="CodeFormulaVlmOptions",
    ),
    "chart_extraction": _StageSpec(
        registry="chart_extraction_preset_registry",
        option="chart_extraction_preset",
        custom_config_option="chart_extraction_custom_config",
        allow_custom_setting="allow_custom_chart_extraction_config",
        default_setting="default_chart_extraction_preset",
        custom_setting="custom_chart_extraction_presets",
        presets_class="ChartExtractionVlmEngineOptions",
    ),
    "chunking": _StageSpec(
        registry="chunking_preset_registry",
        option="chunking_preset",
        default_setting="default_chunking_preset",
        custom_setting="custom_chunking_presets",
    ),
}


def _preset_describer(class_name: str | None) -> Callable[[str], dict[str, str]]:
    """Return a lookup of human-readable name/description for docling presets."""
    if class_name is None:
        return lambda _preset_id: {}

    import docling.datamodel.pipeline_options as pipeline_options

    options_cls = getattr(pipeline_options, class_name, None)
    if options_cls is None:
        return lambda _preset_id: {}

    def describe(preset_id: str) -> dict[str, str]:
        try:
            preset = options_cls.get_preset(preset_id)
        except Exception:
            return {}
        info = {}
        if name := getattr(preset, "name", None):
            info["name"] = str(name)
        if description := getattr(preset, "description", None):
            info["description"] = str(description)
        return info

    return describe


def _stage_presets(
    registry: Mapping[str, Mapping[str, Any]],
    default_preset: str,
    custom_ids: set[str],
    describe: Callable[[str], dict[str, str]],
) -> list[PresetInfo]:
    presets: list[PresetInfo] = []
    for preset_id, entry in registry.items():
        if preset_id == "default":
            presets.append(
                PresetInfo(
                    id="default",
                    name=f"Server default ({default_preset})",
                    source="default",
                )
            )
            continue
        # Custom presets carry the admin's configuration, so nothing beyond
        # their id is exposed. Only docling built-in presets are described.
        if preset_id in custom_ids:
            presets.append(PresetInfo(id=preset_id, name=preset_id, source="custom"))
        elif entry.get("source") == "docling":
            info = describe(str(entry.get("preset_id", preset_id)))
            presets.append(
                PresetInfo(
                    id=preset_id,
                    name=info.get("name", preset_id),
                    description=info.get("description"),
                    source="docling",
                )
            )
        else:
            # Built into jobkit without a docling preset (e.g. table structure).
            presets.append(PresetInfo(id=preset_id, name=preset_id, source="docling"))
    return presets


# Stages that docling-serve validates itself, on top of jobkit's registries.
_POLICY_ALLOWED: dict[str, Callable[[ServicePolicy], frozenset[str]]] = {
    "ocr": lambda policy: policy.allowed_ocr_presets,
}


def _build_stages(
    manager: Any, settings: DoclingServeSettings, policy: ServicePolicy
) -> dict[str, StageCapabilities]:
    stages: dict[str, StageCapabilities] = {}
    for stage_name, spec in _STAGES.items():
        registry = getattr(manager, spec.registry, None)
        if registry is None:
            _log.debug("Converter manager has no %s, skipping.", spec.registry)
            continue
        if policy_allowed := _POLICY_ALLOWED.get(stage_name):
            allowed = policy_allowed(policy)
            registry = {k: v for k, v in registry.items() if k in allowed}
        default_preset = str(getattr(settings, spec.default_setting))
        custom_allowed = spec.allow_custom_setting is not None and bool(
            getattr(settings, spec.allow_custom_setting, False)
        )
        stages[stage_name] = StageCapabilities(
            option=spec.option,
            custom_config_option=(
                spec.custom_config_option if custom_allowed else None
            ),
            default=default_preset,
            presets=_stage_presets(
                registry,
                default_preset,
                set(getattr(settings, spec.custom_setting, {}) or {}),
                _preset_describer(spec.presets_class),
            ),
        )
    return stages


@lru_cache(maxsize=1)
def _converter_manager() -> Any:
    # Constructing the manager only builds the preset and kind registries; no
    # model is loaded, so this is cheap also on API-only (RQ/Ray) deployments.
    from docling_jobkit.convert.manager import DoclingConverterManager

    from docling_serve.orchestrator_factory import _build_cm_config

    return DoclingConverterManager(_build_cm_config())


def _bounded(value: int) -> int | None:
    return None if value >= sys.maxsize else value


def build_capabilities(
    settings: DoclingServeSettings,
    policy: ServicePolicy,
    versions: dict[str, str] | None = None,
    manager: Any = None,
) -> CapabilitiesResponse:
    if manager is None:
        manager = _converter_manager()

    return CapabilitiesResponse(
        # Only package versions: platform details stay behind /version.
        versions=(
            {k: v for k, v in versions.items() if k.startswith("docling")}
            if versions and settings.show_version_info
            else None
        ),
        stages=_build_stages(manager, settings, policy),
        sources=sorted(policy.allowed_source_types),
        targets=TargetCapabilities(
            allowed=sorted(policy.allowed_target_types),
            default=resolve_default_target(policy).kind,
        ),
        output_formats=[fmt.value for fmt in OutputFormat],
        image_export_modes=sorted(policy.allowed_image_export_modes),
        limits=LimitsCapabilities(
            max_document_timeout=settings.max_document_timeout,
            max_images_scale=settings.max_images_scale,
            max_sources_per_request=settings.max_sources_per_request,
            max_num_pages=_bounded(settings.max_num_pages),
            max_file_size=_bounded(settings.max_file_size),
        ),
        features=FeatureCapabilities(
            api_key_required=bool(settings.api_key),
            artifact_storage=policy.artifact_storage_enabled,
        ),
    )

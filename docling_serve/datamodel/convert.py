# Define the input options for the API
from typing import Annotated, Optional

from pydantic import Field, model_validator

from docling.datamodel.layout_model_specs import (
    DOCLING_LAYOUT_EGRET_LARGE,
    DOCLING_LAYOUT_EGRET_MEDIUM,
    DOCLING_LAYOUT_EGRET_XLARGE,
    DOCLING_LAYOUT_HERON,
    DOCLING_LAYOUT_HERON_101,
    DOCLING_LAYOUT_V2,
    LayoutModelConfig,
    LayoutModelType,
)
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
)
from docling.models.factories import get_ocr_factory
from docling_jobkit.datamodel.convert import ConvertDocumentsOptions

from docling_serve.settings import docling_serve_settings

ocr_factory = get_ocr_factory(
    allow_external_plugins=docling_serve_settings.allow_external_plugins
)
ocr_engines_enum = ocr_factory.get_enum()

LAYOUT_MODEL_SPECS: dict[LayoutModelType, LayoutModelConfig] = {
    LayoutModelType.DOCLING_LAYOUT_HERON: DOCLING_LAYOUT_HERON,
    LayoutModelType.DOCLING_LAYOUT_HERON_101: DOCLING_LAYOUT_HERON_101,
    LayoutModelType.DOCLING_LAYOUT_EGRET_MEDIUM: DOCLING_LAYOUT_EGRET_MEDIUM,
    LayoutModelType.DOCLING_LAYOUT_EGRET_LARGE: DOCLING_LAYOUT_EGRET_LARGE,
    LayoutModelType.DOCLING_LAYOUT_EGRET_XLARGE: DOCLING_LAYOUT_EGRET_XLARGE,
    LayoutModelType.DOCLING_LAYOUT_V2: DOCLING_LAYOUT_V2,
}

_default_layout_model: Optional[LayoutModelType] = None
if docling_serve_settings.default_layout_model:
    _default_layout_model = LayoutModelType(
        docling_serve_settings.default_layout_model
    )


class ConvertDocumentsRequestOptions(ConvertDocumentsOptions):
    ocr_engine: Annotated[  # type: ignore
        ocr_engines_enum,
        Field(
            description=(
                "The OCR engine to use. String. "
                f"Allowed values: {', '.join([v.value for v in ocr_engines_enum])}. "
                "Optional, defaults to easyocr."
            ),
            examples=[EasyOcrOptions.kind],
        ),
    ] = ocr_engines_enum(EasyOcrOptions.kind)  # type: ignore

    layout_model: Annotated[
        Optional[LayoutModelType],
        Field(
            description=(
                "The layout analysis model to use. String. "
                f"Allowed values: {', '.join([v.value for v in LayoutModelType])}. "
                "Optional, defaults to docling_layout_heron. "
                "When set, expands into layout_custom_config automatically. "
                "Ignored if layout_custom_config is explicitly provided."
            ),
            examples=[
                LayoutModelType.DOCLING_LAYOUT_HERON.value,
                LayoutModelType.DOCLING_LAYOUT_EGRET_LARGE.value,
            ],
        ),
    ] = _default_layout_model

    document_timeout: Annotated[
        float,
        Field(
            description="The timeout for processing each document, in seconds.",
            gt=0,
            le=docling_serve_settings.max_document_timeout,
        ),
    ] = docling_serve_settings.max_document_timeout

    @model_validator(mode="before")
    @classmethod
    def expand_layout_model(cls, data: dict) -> dict:
        if not isinstance(data, dict):
            return data
        layout_model = data.get("layout_model")
        layout_custom_config = data.get("layout_custom_config")
        if layout_model is not None and layout_custom_config is None:
            model_type = LayoutModelType(layout_model)
            spec = LAYOUT_MODEL_SPECS[model_type]
            data["layout_custom_config"] = {
                "kind": "docling_layout_default",
                "model_spec": spec.model_dump(mode="json"),
            }
        return data

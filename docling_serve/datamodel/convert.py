# Define the input options for the API
from typing import Annotated

from pydantic import Field

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

    document_timeout: Annotated[
        float,
        Field(
            description="The timeout for processing each document, in seconds.",
            gt=0,
            le=docling_serve_settings.max_document_timeout,
        ),
    ] = docling_serve_settings.max_document_timeout

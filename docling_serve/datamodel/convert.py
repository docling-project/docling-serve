# Define the input options for the API
from typing import Annotated

from pydantic import Field, field_serializer

from docling.datamodel.pipeline_options import (
    OcrAutoOptions,
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
            examples=[OcrAutoOptions.kind],
        ),
    ] = ocr_engines_enum(OcrAutoOptions.kind)  # type: ignore

    document_timeout: Annotated[
        float,
        Field(
            description="The timeout for processing each document, in seconds.",
            gt=0,
            le=docling_serve_settings.max_document_timeout,
        ),
    ] = docling_serve_settings.max_document_timeout

    @field_serializer("page_range", when_used="json")
    def serialize_page_range(
        self,
        page_range: tuple[int, int] | None,
    ) -> list[int] | None:
        if page_range is None:
            return None
        return [page_range[0], page_range[1]]

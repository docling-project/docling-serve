# Define the input options for the API
from typing import Annotated, Optional

from pydantic import BaseModel, Field

from docling.datamodel.base_models import InputFormat, OutputFormat
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    PdfBackend,
    TableFormerMode,
)
from docling.models.factories import get_ocr_factory
from docling_core.types.doc import ImageRefMode

from docling_serve.settings import docling_serve_settings

ocr_factory = get_ocr_factory(allow_external_plugins=docling_serve_settings.allow_external_plugins)
ocr_engines_enum = ocr_factory.get_enum()

class ConvertDocumentsOptions(BaseModel):
    from_formats: Annotated[
        list[InputFormat],
        Field(
            description=(
                "Input format(s) to convert from. String or list of strings. "
                f"Allowed values: {', '.join([v.value for v in InputFormat])}. "
                "Optional, defaults to all formats."
            ),
            examples=[[v.value for v in InputFormat]],
        ),
    ] = list(InputFormat)

    to_formats: Annotated[
        list[OutputFormat],
        Field(
            description=(
                "Output format(s) to convert to. String or list of strings. "
                f"Allowed values: {', '.join([v.value for v in OutputFormat])}. "
                "Optional, defaults to Markdown."
            ),
            examples=[[OutputFormat.MARKDOWN]],
        ),
    ] = [OutputFormat.MARKDOWN]

    image_export_mode: Annotated[
        ImageRefMode,
        Field(
            description=(
                "Image export mode for the document (in case of JSON,"
                " Markdown or HTML). "
                f"Allowed values: {', '.join([v.value for v in ImageRefMode])}. "
                "Optional, defaults to Embedded."
            ),
            examples=[ImageRefMode.EMBEDDED.value],
            # pattern="embedded|placeholder|referenced",
        ),
    ] = ImageRefMode.EMBEDDED

    do_ocr: Annotated[
        bool,
        Field(
            description=(
                "If enabled, the bitmap content will be processed using OCR. "
                "Boolean. Optional, defaults to true"
            ),
            # examples=[True],
        ),
    ] = True

    force_ocr: Annotated[
        bool,
        Field(
            description=(
                "If enabled, replace existing text with OCR-generated "
                "text over content. Boolean. Optional, defaults to false."
            ),
            # examples=[False],
        ),
    ] = False

    ocr_engine: Annotated[
        ocr_engines_enum,  # type: ignore
        Field(
            description=(
                "The OCR engine to use. String. "
                f"Allowed values: {', '.join([v.value for v in ocr_engines_enum])}. "
                "Optional, defaults to easyocr."
            ),
            examples=[EasyOcrOptions.kind],
        ),
    ] = ocr_engines_enum(EasyOcrOptions.kind)

    ocr_lang: Annotated[
        Optional[list[str]],
        Field(
            description=(
                "List of languages used by the OCR engine. "
                "Note that each OCR engine has "
                "different values for the language names. String or list of strings. "
                "Optional, defaults to empty."
            ),
            examples=[["fr", "de", "es", "en"]],
        ),
    ] = None

    pdf_backend: Annotated[
        PdfBackend,
        Field(
            description=(
                "The PDF backend to use. String. "
                f"Allowed values: {', '.join([v.value for v in PdfBackend])}. "
                f"Optional, defaults to {PdfBackend.DLPARSE_V4.value}."
            ),
            examples=[PdfBackend.DLPARSE_V4],
        ),
    ] = PdfBackend.DLPARSE_V4

    table_mode: Annotated[
        TableFormerMode,
        Field(
            TableFormerMode.FAST,
            description=(
                "Mode to use for table structure, String. "
                f"Allowed values: {', '.join([v.value for v in TableFormerMode])}. "
                "Optional, defaults to fast."
            ),
            examples=[TableFormerMode.FAST],
            # pattern="fast|accurate",
        ),
    ] = TableFormerMode.FAST

    abort_on_error: Annotated[
        bool,
        Field(
            description=(
                "Abort on error if enabled. Boolean. Optional, defaults to false."
            ),
            # examples=[False],
        ),
    ] = False

    return_as_file: Annotated[
        bool,
        Field(
            description=(
                "Return the output as a zip file "
                "(will happen anyway if multiple files are generated). "
                "Boolean. Optional, defaults to false."
            ),
            examples=[False],
        ),
    ] = False

    do_table_structure: Annotated[
        bool,
        Field(
            description=(
                "If enabled, the table structure will be extracted. "
                "Boolean. Optional, defaults to true."
            ),
            examples=[True],
        ),
    ] = True

    include_images: Annotated[
        bool,
        Field(
            description=(
                "If enabled, images will be extracted from the document. "
                "Boolean. Optional, defaults to true."
            ),
            examples=[True],
        ),
    ] = True

    images_scale: Annotated[
        float,
        Field(
            description="Scale factor for images. Float. Optional, defaults to 2.0.",
            examples=[2.0],
        ),
    ] = 2.0

    do_code_enrichment: Annotated[
        bool,
        Field(
            description=(
                "If enabled, perform OCR code enrichment. "
                "Boolean. Optional, defaults to false."
            ),
            examples=[False],
        ),
    ] = False

    do_formula_enrichment: Annotated[
        bool,
        Field(
            description=(
                "If enabled, perform formula OCR, return Latex code. "
                "Boolean. Optional, defaults to false."
            ),
            examples=[False],
        ),
    ] = False

    do_picture_classification: Annotated[
        bool,
        Field(
            description=(
                "If enabled, classify pictures in documents. "
                "Boolean. Optional, defaults to false."
            ),
            examples=[False],
        ),
    ] = False

    do_picture_description: Annotated[
        bool,
        Field(
            description=(
                "If enabled, describe pictures in documents. "
                "Boolean. Optional, defaults to false."
            ),
            examples=[False],
        ),
    ] = False

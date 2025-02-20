# Define the input options for the API
from typing import Annotated, List, Optional

from pydantic import BaseModel, Field

from docling.datamodel.base_models import InputFormat, OutputFormat
from docling.datamodel.pipeline_options import OcrEngine, PdfBackend, TableFormerMode
from docling_core.types.doc import ImageRefMode


class ConvertDocumentsOptions(BaseModel):
    from_formats: Annotated[
        List[InputFormat],
        Field(
            description=(
                "Input format(s) to convert from. String or list of strings. "
                f"Allowed values: {', '.join([v.value for v in InputFormat])}. "
                "Optional, defaults to all formats."
            ),
            examples=[[v.value for v in InputFormat]],
        ),
    ] = [v for v in InputFormat]

    to_formats: Annotated[
        List[OutputFormat],
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

    # TODO: use a restricted list based on what is installed on the system
    ocr_engine: Annotated[
        OcrEngine,
        Field(
            description=(
                "The OCR engine to use. String. "
                "Allowed values: easyocr, tesseract, rapidocr. "
                "Optional, defaults to easyocr."
            ),
            examples=[OcrEngine.EASYOCR],
        ),
    ] = OcrEngine.EASYOCR

    ocr_lang: Annotated[
        Optional[List[str]],
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
                f"Optional, defaults to {PdfBackend.DLPARSE_V2.value}."
            ),
            examples=[PdfBackend.DLPARSE_V2],
        ),
    ] = PdfBackend.DLPARSE_V2

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
                "Abort on error if enabled. " "Boolean. Optional, defaults to false."
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

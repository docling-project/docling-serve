import hashlib
import json
import logging
from typing import Dict, Iterator, List, Optional, Tuple, Type, Union

from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
from docling.backend.docling_parse_v2_backend import DoclingParseV2DocumentBackend
from docling.backend.pdf_backend import PdfDocumentBackend
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import InputFormat, OutputFormat
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    OcrEngine,
    OcrOptions,
    PdfBackend,
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TesseractOcrOptions,
)
from docling.document_converter import DocumentConverter, FormatOption, PdfFormatOption
from docling_core.types.doc import ImageRefMode
from fastapi import HTTPException
from helper_functions import _to_list_of_strings
from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)


# Define the input options for the API
class ConvertDocumentsParameters(BaseModel):
    from_formats: Optional[Union[List[str], str]] = Field(
        ["docx", "pptx", "html", "image", "pdf", "asciidoc", "md", "xlsx"],
        description=(
            "Input format(s) to convert from. String or list of strings. "
            "Allowed values: docx, pptx, html, image, pdf, asciidoc, md, xlsx. "
            "Optional, defaults to all formats."
        ),
        examples=[["docx", "pptx", "html", "image", "pdf", "asciidoc", "md", "xlsx"]],
    )
    to_formats: Optional[Union[List[str], str]] = Field(
        ["md"],
        description=(
            "Output format(s) to convert to. String or list of strings. "
            "Allowed values: md, docling (json), html, text, doctags. "
            "Optional, defaults to Markdown."
        ),
        examples=["md"],
    )
    image_export_mode: Optional[str] = Field(
        "embedded",
        description=(
            "Image export mode for the document (in case of JSON, Markdown or HTML). "
            "Allowed values: embedded, placeholder, referenced. "
            "Optional, defaults to Embedded."
        ),
        examples=["embedded"],
        pattern="embedded|placeholder|referenced",
    )
    do_ocr: Optional[bool] = Field(
        True,
        description=(
            "If enabled, the bitmap content will be processed using OCR. "
            "Boolean. Optional, defaults to true"
        ),
        examples=[True],
    )
    force_ocr: Optional[bool] = Field(
        False,
        description=(
            "If enabled, replace existing text with OCR-generated text over content. "
            "Boolean. Optional, defaults to false."
        ),
        examples=[False],
    )
    ocr_engine: Optional[str] = Field(
        OcrEngine.EASYOCR,
        description=(
            "The OCR engine to use. String. "
            "Allowed values: easyocr, tesseract, rapidocr. "
            "Optional, defaults to easyocr."
        ),
        examples=["easyocr"],
        pattern="easyocr|tesseract|rapidocr",
    )
    ocr_lang: Optional[Union[List[str], str]] = Field(
        None,
        description=(
            "List of languages used by the OCR engine. "
            "Note that each OCR engine has "
            "different values for the language names. String or list of strings. "
            "Optional, defaults to empty."
        ),
        examples=[["fr", "de", "es", "en"]],
    )
    pdf_backend: Optional[str] = Field(
        PdfBackend.DLPARSE_V2,
        description=(
            "The PDF backend to use. String. "
            "Allowed values: pypdfium2, dlparse_v1, dlparse_v2. "
            "Optional, defaults to dlparse_v2."
        ),
        examples=["dlparse_v2"],
        pattern="pypdfium2|dlparse_v1|dlparse_v2",
    )
    table_mode: Optional[str] = Field(
        TableFormerMode.FAST,
        description=(
            "Mode to use for table structure, String. "
            "Allowed values: fast, accurate. Optional, defaults to fast."
        ),
        examples=["fast"],
        pattern="fast|accurate",
    )
    abort_on_error: Optional[bool] = Field(
        False,
        description=(
            "Abort on error if enabled. " "Boolean. Optional, defaults to false."
        ),
        examples=[False],
    )
    return_as_file: Optional[bool] = Field(
        False,
        description=(
            "Return the output as a zip file "
            "(will happen anyway if multiple files are generated). "
            "Boolean. Optional, defaults to false."
        ),
        examples=[False],
    )
    do_table_structure: Optional[bool] = Field(
        True,
        description=(
            "If enabled, the table structure will be extracted. "
            "Boolean. Optional, defaults to true."
        ),
        examples=[True],
    )
    include_images: Optional[bool] = Field(
        True,
        description=(
            "If enabled, images will be extracted from the document. "
            "Boolean. Optional, defaults to true."
        ),
        examples=[True],
    )
    images_scale: Optional[float] = Field(
        2.0,
        description="Scale factor for images. Float. Optional, defaults to 2.0.",
        examples=[2.0],
    )


class ConvertDocumentsRequest(ConvertDocumentsParameters):
    input_sources: Union[List[str], str] = Field(
        ...,
        description="Source(s) to process.",
        examples=["https://arxiv.org/pdf/2206.01062"],
    )


class DocumentResponse(BaseModel):
    filename: Optional[str] = None
    md_content: Optional[str] = None
    json_content: Optional[dict] = None
    html_content: Optional[str] = None
    text_content: Optional[str] = None
    doctags_content: Optional[str] = None


class ConvertDocumentResponse(BaseModel):
    document: Optional[DocumentResponse] = None
    processing_time: Optional[float] = None


# Document converters will be preloaded and stored in a dictionary
converters: Dict[str, DocumentConverter] = {}


# Custom serializer for PdfFormatOption
# (model_dump_json does not work with some classes)
def _serialize_pdf_format_option(pdf_format_option: PdfFormatOption) -> str:
    data = pdf_format_option.model_dump()

    # pipeline_options are not fully serialized by model_dump, dedicated pass
    if pdf_format_option.pipeline_options:
        data["pipeline_options"] = pdf_format_option.pipeline_options.model_dump()

    # Replace `pipeline_cls` with a string representation
    data["pipeline_cls"] = repr(data["pipeline_cls"])

    # Replace `backend` with a string representation
    data["backend"] = repr(data["backend"])

    # Handle `device` in `accelerator_options`
    if "accelerator_options" in data and "device" in data["accelerator_options"]:
        data["accelerator_options"]["device"] = repr(
            data["accelerator_options"]["device"]
        )

    # Serialize the dictionary to JSON with sorted keys to have consistent hashes
    return json.dumps(data, sort_keys=True)


# Computes the PDF pipeline options and returns the PdfFormatOption and its hash
def get_pdf_pipeline_opts(
    request: ConvertDocumentsParameters,
) -> Tuple[PdfFormatOption, str]:

    if request.ocr_engine == OcrEngine.EASYOCR:
        try:
            import easyocr  # noqa: F401
        except ImportError:
            raise HTTPException(
                status_code=400,
                detail="The requested OCR engine"
                f" (ocr_engine={request.ocr_engine.value})"
                " is not available on this system. Please choose another OCR engine "
                "or contact your system administrator.",
            )
        ocr_options: OcrOptions = EasyOcrOptions(force_full_page_ocr=request.force_ocr)
    elif request.ocr_engine == OcrEngine.TESSERACT:
        try:
            import tesserocr  # noqa: F401
        except ImportError:
            raise HTTPException(
                status_code=400,
                detail="The requested OCR engine"
                f" (ocr_engine={request.ocr_engine.value})"
                " is not available on this system. Please choose another OCR engine "
                "or contact your system administrator.",
            )
        ocr_options = TesseractOcrOptions(force_full_page_ocr=request.force_ocr)
    elif request.ocr_engine == OcrEngine.RAPIDOCR:
        try:
            from rapidocr_onnxruntime import RapidOCR  # noqa: F401
        except ImportError:
            raise HTTPException(
                status_code=400,
                detail="The requested OCR engine"
                f" (ocr_engine={request.ocr_engine.value})"
                " is not available on this system. Please choose another OCR engine "
                "or contact your system administrator.",
            )
        ocr_options = RapidOcrOptions(force_full_page_ocr=request.force_ocr)
    else:
        raise RuntimeError(f"Unexpected OCR engine type {request.ocr_engine}")

    if request.ocr_lang is not None:
        if isinstance(request.ocr_lang, str):
            ocr_options.lang = _to_list_of_strings(request.ocr_lang)
        else:
            ocr_options.lang = request.ocr_lang

    pipeline_options = PdfPipelineOptions(
        do_ocr=request.do_ocr,
        ocr_options=ocr_options,
        do_table_structure=request.do_table_structure,
    )
    pipeline_options.table_structure_options.do_cell_matching = True  # do_cell_matching
    pipeline_options.table_structure_options.mode = TableFormerMode(request.table_mode)

    if request.image_export_mode != ImageRefMode.PLACEHOLDER:
        pipeline_options.generate_page_images = True
        pipeline_options.generate_picture_images = (
            True  # FIXME: to be deprecated in version 3
        )
        if request.images_scale:
            pipeline_options.images_scale = request.images_scale

    if request.pdf_backend == PdfBackend.DLPARSE_V1:
        backend: Type[PdfDocumentBackend] = DoclingParseDocumentBackend
    elif request.pdf_backend == PdfBackend.DLPARSE_V2:
        backend = DoclingParseV2DocumentBackend
    elif request.pdf_backend == PdfBackend.PYPDFIUM2:
        backend = PyPdfiumDocumentBackend
    else:
        raise RuntimeError(f"Unexpected PDF backend type {request.pdf_backend}")

    pdf_format_option = PdfFormatOption(
        pipeline_options=pipeline_options,
        backend=backend,  # pdf_backend
    )

    serialized_data = _serialize_pdf_format_option(pdf_format_option)

    options_hash = hashlib.sha1(serialized_data.encode()).hexdigest()

    return pdf_format_option, options_hash


def convert_documents(
    conversion_request: ConvertDocumentsRequest,
):

    # Initialize some values if missing
    # (None, empty string, empty List, List of empty strings)
    if not conversion_request.from_formats or all(
        not item for item in conversion_request.from_formats
    ):
        conversion_request.from_formats = [e for e in InputFormat]

    if not conversion_request.to_formats or all(
        not item for item in conversion_request.to_formats
    ):
        conversion_request.to_formats = OutputFormat.MARKDOWN

    # Sanitize some parameters as they can be a string or a list
    conversion_request.input_sources = _to_list_of_strings(
        conversion_request.input_sources
    )
    conversion_request.from_formats = _to_list_of_strings(
        conversion_request.from_formats
    )
    conversion_request.to_formats = _to_list_of_strings(conversion_request.to_formats)
    if conversion_request.ocr_lang is not None:
        conversion_request.ocr_lang = _to_list_of_strings(conversion_request.ocr_lang)

    pdf_format_option, options_hash = get_pdf_pipeline_opts(conversion_request)

    if options_hash not in converters:
        format_options: Dict[InputFormat, FormatOption] = {
            InputFormat.PDF: pdf_format_option,
            InputFormat.IMAGE: pdf_format_option,
        }

        converters[options_hash] = DocumentConverter(format_options=format_options)
        _log.info(f"We now have {len(converters)} converters in memory.")

    results: Iterator[ConversionResult] = converters[options_hash].convert_all(
        conversion_request.input_sources
    )

    return results

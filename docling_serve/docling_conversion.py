import base64
import hashlib
import json
import logging
from io import BytesIO
from pathlib import Path
from typing import (
    Annotated,
    Any,
    Dict,
    Iterable,
    Iterator,
    List,
    Optional,
    Tuple,
    Type,
    Union,
)

from fastapi import HTTPException
from pydantic import BaseModel, Field

from docling.backend.docling_parse_backend import DoclingParseDocumentBackend
from docling.backend.docling_parse_v2_backend import DoclingParseV2DocumentBackend
from docling.backend.pdf_backend import PdfDocumentBackend
from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.datamodel.base_models import DocumentStream, InputFormat, OutputFormat
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

from docling_serve.helper_functions import _to_list_of_strings
from docling_serve.settings import docling_serve_settings

_log = logging.getLogger(__name__)


# Define the input options for the API
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


class DocumentsConvertBase(BaseModel):
    options: ConvertDocumentsOptions = ConvertDocumentsOptions()


class HttpSource(BaseModel):
    url: Annotated[
        str,
        Field(
            description="HTTP url to process",
            examples=["https://arxiv.org/pdf/2206.01062"],
        ),
    ]
    headers: Annotated[
        Dict[str, Any],
        Field(
            description="Additional headers used to fetch the urls, "
            "e.g. authorization, agent, etc"
        ),
    ] = {}


class FileSource(BaseModel):
    base64_string: Annotated[
        str,
        Field(
            description="Content of the file serialized in base64. "
            "For example it can be obtained via "
            "`base64 -w 0 /path/to/file/pdf-to-convert.pdf`."
        ),
    ]
    filename: Annotated[
        str,
        Field(description="Filename of the uploaded document", examples=["file.pdf"]),
    ]

    def to_document_stream(self) -> DocumentStream:
        buf = BytesIO(base64.b64decode(self.base64_string))
        return DocumentStream(stream=buf, name=self.filename)


class ConvertDocumentHttpSourcesRequest(DocumentsConvertBase):
    http_sources: List[HttpSource]


class ConvertDocumentFileSourcesRequest(DocumentsConvertBase):
    file_sources: List[FileSource]


ConvertDocumentsRequest = Union[
    ConvertDocumentFileSourcesRequest, ConvertDocumentHttpSourcesRequest
]


# Document converters will be preloaded and stored in a dictionary
converters: Dict[str, DocumentConverter] = {}


# Custom serializer for PdfFormatOption
# (model_dump_json does not work with some classes)
def _serialize_pdf_format_option(pdf_format_option: PdfFormatOption) -> str:
    data = pdf_format_option.model_dump()

    # pipeline_options are not fully serialized by model_dump, dedicated pass
    if pdf_format_option.pipeline_options:
        data["pipeline_options"] = pdf_format_option.pipeline_options.model_dump()

        # Replace `artifacts_path` with a string representation
        data["pipeline_options"]["artifacts_path"] = repr(
            data["pipeline_options"]["artifacts_path"]
        )

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
def get_pdf_pipeline_opts(  # noqa: C901
    request: ConvertDocumentsOptions,
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

    if docling_serve_settings.artifacts_path is not None:
        if str(docling_serve_settings.artifacts_path.absolute()) == "":
            _log.info(
                "artifacts_path is an empty path, model weights will be dowloaded "
                "at runtime."
            )
            pipeline_options.artifacts_path = None
        elif docling_serve_settings.artifacts_path.is_dir():
            _log.info(
                "artifacts_path is set to a valid directory. "
                "No model weights will be downloaded at runtime."
            )
            pipeline_options.artifacts_path = docling_serve_settings.artifacts_path
        else:
            _log.warning(
                "artifacts_path is set to an invalid directory. "
                "The system will download the model weights at runtime."
            )
            pipeline_options.artifacts_path = None
    else:
        _log.info(
            "artifacts_path is unset. "
            "The system will download the model weights at runtime."
        )

    pdf_format_option = PdfFormatOption(
        pipeline_options=pipeline_options,
        backend=backend,
    )

    serialized_data = _serialize_pdf_format_option(pdf_format_option)

    options_hash = hashlib.sha1(serialized_data.encode()).hexdigest()

    return pdf_format_option, options_hash


def convert_documents(
    sources: Iterable[Union[Path, str, DocumentStream]],
    options: ConvertDocumentsOptions,
    headers: Optional[Dict[str, Any]] = None,
):
    pdf_format_option, options_hash = get_pdf_pipeline_opts(options)

    if options_hash not in converters:
        format_options: Dict[InputFormat, FormatOption] = {
            InputFormat.PDF: pdf_format_option,
            InputFormat.IMAGE: pdf_format_option,
        }

        converters[options_hash] = DocumentConverter(format_options=format_options)
        _log.info(f"We now have {len(converters)} converters in memory.")

    results: Iterator[ConversionResult] = converters[options_hash].convert_all(
        sources,
        headers=headers,
    )

    return results

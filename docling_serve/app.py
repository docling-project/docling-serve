import base64
import hashlib
from contextlib import asynccontextmanager
from enum import Enum
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple, Union

import httpx
from docling.datamodel.base_models import (
    ConversionStatus,
    DocumentStream,
    ErrorItem,
    InputFormat,
)
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
    OcrOptions,
    PdfPipelineOptions,
    RapidOcrOptions,
    TesseractOcrOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.utils.profiling import ProfilingItem
from docling_core.types.doc import DoclingDocument, ImageRefMode
from docling_core.utils.file import resolve_remote_filename
from fastapi import FastAPI, HTTPException, Response
from pydantic import AnyHttpUrl, BaseModel


# TODO: import enum from Docling, once it is exposed
class OcrEngine(str, Enum):
    EASYOCR = "easyocr"
    TESSERACT = "tesseract"
    RAPIDOCR = "rapidocr"


class ConvertOptions(BaseModel):
    output_docling_document: bool = True
    output_markdown: bool = False
    output_html: bool = False
    output_text: bool = False
    do_ocr: bool = True
    ocr_engine: OcrEngine = OcrEngine.EASYOCR
    ocr_lang: Optional[List[str]] = None
    force_ocr: bool = False
    do_table_structure: bool = True
    include_images: bool = True
    images_scale: float = 2.0


class DocumentConvertBase(BaseModel):
    options: ConvertOptions = ConvertOptions()


class HttpSource(BaseModel):
    url: str
    headers: Dict[str, Any] = {}


class FileSource(BaseModel):
    base64_string: str
    filename: str


class ConvertDocumentHttpSourceRequest(DocumentConvertBase):
    http_source: HttpSource


class ConvertDocumentFileSourceRequest(DocumentConvertBase):
    file_source: FileSource


class DocumentResponse(BaseModel):
    markdown: Optional[str] = None
    text: Optional[str] = None
    docling_document: Optional[DoclingDocument] = None
    html: Optional[str] = None


class ConvertDocumentResponse(BaseModel):
    document: DocumentResponse
    status: ConversionStatus
    errors: List[ErrorItem] = []
    timings: Dict[str, ProfilingItem] = {}


class ConvertDocumentErrorResponse(BaseModel):
    status: ConversionStatus
    # errors: List[ErrorItem] = []


ConvertDocumentRequest = Union[
    ConvertDocumentFileSourceRequest, ConvertDocumentHttpSourceRequest
]


class MarkdownTextResponse(Response):
    media_type = "text/markdown"

class PlainTextResponse(Response):
    media_type = "text/plain"

class HTMLTextResponse(Response):
    media_type = "text/html"


class HealthCheckResponse(BaseModel):
    status: str = "ok"


def get_pdf_pipeline_opts(options: ConvertOptions) -> Tuple[PdfPipelineOptions, str]:

    if options.ocr_engine == OcrEngine.EASYOCR:
        try:
            import easyocr  # noqa: F401
        except ImportError:
            raise HTTPException(
                status_code=400,
                detail="The requested OCR engine"
                f" (ocr_engine={options.ocr_engine.value})"
                " is not available on this system. Please choose another OCR engine "
                "or contact your system administrator.",
            )
        ocr_options: OcrOptions = EasyOcrOptions(force_full_page_ocr=options.force_ocr)
    elif options.ocr_engine == OcrEngine.TESSERACT:
        try:
            import tesserocr  # noqa: F401
        except ImportError:
            raise HTTPException(
                status_code=400,
                detail="The requested OCR engine"
                f" (ocr_engine={options.ocr_engine.value})"
                " is not available on this system. Please choose another OCR engine "
                "or contact your system administrator.",
            )
        ocr_options = TesseractOcrOptions(force_full_page_ocr=options.force_ocr)
    elif options.ocr_engine == OcrEngine.RAPIDOCR:
        try:
            from rapidocr_onnxruntime import RapidOCR  # noqa: F401
        except ImportError:
            raise HTTPException(
                status_code=400,
                detail="The requested OCR engine"
                f" (ocr_engine={options.ocr_engine.value})"
                " is not available on this system. Please choose another OCR engine "
                "or contact your system administrator.",
            )
        ocr_options = RapidOcrOptions(force_full_page_ocr=options.force_ocr)
    else:
        raise RuntimeError(f"Unexpected OCR engine type {options.ocr_engine}")

    if options.ocr_lang is not None:
        ocr_options.lang = options.ocr_lang

    pipeline_options = PdfPipelineOptions(
        do_ocr=options.do_ocr,
        ocr_options=ocr_options,
        do_table_structure=options.do_table_structure,
        generate_page_images=options.include_images,
        generate_picture_images=options.include_images,
        images_scale=options.images_scale,
    )

    options_hash = hashlib.sha1(pipeline_options.model_dump_json().encode()).hexdigest()

    return pipeline_options, options_hash


converters: Dict[str, DocumentConverter] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # settings = Settings()

    # Converter with default options
    pipeline_options, options_hash = get_pdf_pipeline_opts(ConvertOptions())
    converters[options_hash] = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            InputFormat.IMAGE: PdfFormatOption(pipeline_options=pipeline_options),
        }
    )

    converters[options_hash].initialize_pipeline(InputFormat.PDF)

    yield

    converters.clear()


app = FastAPI(
    title="Docling Serve",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> HealthCheckResponse:
    return HealthCheckResponse()


def _convert_document(
    body: ConvertDocumentRequest,
) -> ConversionResult:

    filename: str
    buf: BytesIO

    if isinstance(body, ConvertDocumentFileSourceRequest):
        buf = BytesIO(base64.b64decode(body.file_source.base64_string))
        filename = body.file_source.filename
    elif isinstance(body, ConvertDocumentHttpSourceRequest):
        http_res = httpx.get(body.http_source.url, headers=body.http_source.headers)
        buf = BytesIO(http_res.content)
        filename = resolve_remote_filename(
            http_url=AnyHttpUrl(body.http_source.url),
            response_headers=dict(**http_res.headers),
        )

    doc_input = DocumentStream(name=filename, stream=buf)

    pipeline_options, options_hash = get_pdf_pipeline_opts(body.options)
    if options_hash not in converters:
        converters[options_hash] = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
                InputFormat.IMAGE: PdfFormatOption(pipeline_options=pipeline_options),
            }
        )

    result: ConversionResult = converters[options_hash].convert(doc_input)

    if result is None or result.status == ConversionStatus.SKIPPED:
        raise HTTPException(status_code=400, detail=result.errors)

    if result is None or result.status not in {
        ConversionStatus.SUCCESS,
    }:
        raise HTTPException(
            status_code=500, detail={"errors": result.errors, "status": result.status}
        )

    return result


@app.post(
    "/convert",
)
def convert_document(
    body: ConvertDocumentRequest,
) -> ConvertDocumentResponse:

    result = _convert_document(body=body)

    image_mode = (
        ImageRefMode.EMBEDDED
        if body.options.include_images
        else ImageRefMode.PLACEHOLDER
    )
    doc_resp = DocumentResponse()
    if body.options.output_docling_document:
        doc_resp.docling_document = result.document
    if body.options.output_markdown:
        doc_resp.markdown = result.document.export_to_markdown(image_mode=image_mode)
    if body.options.output_html:
        doc_resp.html = result.document.export_to_html(image_mode=image_mode)
    if body.options.output_text:
        doc_resp.text = result.document.export_to_text()

    return ConvertDocumentResponse(
        document=doc_resp, status=result.status, timings=result.timings
    )


@app.post("/convert/markdown", response_class=MarkdownTextResponse)
def convert_document_md(
    body: ConvertDocumentRequest,
) -> MarkdownTextResponse:
    result = _convert_document(body=body)
    image_mode = (
        ImageRefMode.EMBEDDED
        if body.options.include_images
        else ImageRefMode.PLACEHOLDER
    )
    return MarkdownTextResponse(
        result.document.export_to_markdown(image_mode=image_mode)
    )

@app.post("/convert/text", response_class=PlainTextResponse)
def convert_document_text(
    body: ConvertDocumentRequest,
) -> PlainTextResponse:
    result = _convert_document(body=body)
    return PlainTextResponse(
        result.document.export_to_text()
    )

@app.post("/convert/html", response_class=HTMLTextResponse)
def convert_document_html(
    body: ConvertDocumentRequest,
) -> HTMLTextResponse:
    result = _convert_document(body=body)
    image_mode = (
        ImageRefMode.EMBEDDED
        if body.options.include_images
        else ImageRefMode.PLACEHOLDER
    )
    return HTMLTextResponse(
        result.document.export_to_html(image_mode=image_mode)
    )

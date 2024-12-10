import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Optional, Union

import gradio as gr
from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter
from docling_conversion import (
    ConvertDocumentsParameters,
    ConvertDocumentsRequest,
    convert_documents,
    converters,
    get_pdf_pipeline_opts,
)
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from gradio_ui import ui as gradio_ui
from helper_functions import _str_to_bool, _to_list_of_strings
from pydantic import BaseModel
from response_preparation import process_results
from uvicorn import run

# Load local env vars if present
load_dotenv()


# Set up custom logging as we'll be intermixes with FastAPI/Uvicorn's logging
class ColoredLogFormatter(logging.Formatter):
    COLOR_CODES = {
        logging.DEBUG: "\033[94m",  # Blue
        logging.INFO: "\033[92m",  # Green
        logging.WARNING: "\033[93m",  # Yellow
        logging.ERROR: "\033[91m",  # Red
        logging.CRITICAL: "\033[95m",  # Magenta
    }
    RESET_CODE = "\033[0m"

    def format(self, record):
        color = self.COLOR_CODES.get(record.levelno, "")
        record.levelname = f"{color}{record.levelname}{self.RESET_CODE}"
        return super().format(record)


logging.basicConfig(
    level=logging.INFO,  # Set the logging level
    format="%(levelname)s:\t%(asctime)s - %(name)s - %(message)s",
    datefmt="%H:%M:%S",
)

# Override the formatter with the custom ColoredLogFormatter
root_logger = logging.getLogger()  # Get the root logger
for handler in root_logger.handlers:  # Iterate through existing handlers
    if handler.formatter:
        handler.setFormatter(ColoredLogFormatter(handler.formatter._fmt))

_log = logging.getLogger(__name__)


# Context manager to initialize and clean up the lifespan of the FastAPI app
@asynccontextmanager
async def lifespan(app: FastAPI):
    # settings = Settings()

    # Converter with default options
    pdf_format_option, options_hash = get_pdf_pipeline_opts(
        ConvertDocumentsParameters()
    )
    converters[options_hash] = DocumentConverter(
        format_options={
            InputFormat.PDF: pdf_format_option,
            InputFormat.IMAGE: pdf_format_option,
        }
    )

    converters[options_hash].initialize_pipeline(InputFormat.PDF)

    yield

    converters.clear()
    gradio_ui.close()


##################################
# App creation and configuration #
##################################

app = FastAPI(
    title="Docling Serve",
    lifespan=lifespan,
)

origins = ["*"]
methods = ["*"]
headers = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=methods,
    allow_headers=headers,
)

# Mount the Gradio app
tmp_output_dir = Path(tempfile.mkdtemp())
gradio_ui.gradio_output_dir = tmp_output_dir
app = gr.mount_gradio_app(
    app, gradio_ui, path="/ui", allowed_paths=["./logo.png", tmp_output_dir]
)


#############################
# API Endpoints definitions #
#############################


# Favicon
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    response = RedirectResponse(url="https://ds4sd.github.io/docling/assets/logo.png")
    return response


# Status
class HealthCheckResponse(BaseModel):
    status: str = "ok"


@app.get("/health")
def health() -> HealthCheckResponse:
    return HealthCheckResponse()


# API readiness compatibility for OpenShift AI Workbench
@app.get("/api", include_in_schema=False)
def api_check() -> HealthCheckResponse:
    return HealthCheckResponse()


# Convert a document from URL(s)
@app.post("/v1alpha/convert/url")
def process_url(conversion_request: ConvertDocumentsRequest):
    # Note: results are only an iterator->lazy evaluation
    results = convert_documents(conversion_request)

    # The real processing will happen here
    response = process_results(
        conversion_request=conversion_request, conv_results=results
    )

    return response


# Convert a document from file(s)


# Parameters parser: Form object needed for the file(s) conversion endpoint
def _parse_parameters(
    from_formats: Optional[Union[List[str], str]] = Form(["pdf", "docx"]),
    to_formats: Optional[Union[List[str], str]] = Form(["md"]),
    image_export_mode: Optional[str] = Form("embedded"),
    do_ocr: Optional[Union[bool, str]] = Form("true"),
    force_ocr: Optional[Union[bool, str]] = Form("false"),
    ocr_engine: Optional[str] = Form("easyocr"),
    ocr_lang: Optional[str] = Form("en"),
    pdf_backend: Optional[str] = Form("dlparse_v2"),
    table_mode: Optional[str] = Form("fast"),
    abort_on_error: Optional[Union[bool, str]] = Form("false"),
    return_as_file: Optional[Union[bool, str]] = Form("false"),
    do_table_structure: Optional[Union[bool, str]] = Form("true"),
    include_images: Optional[Union[bool, str]] = Form("true"),
    images_scale: Optional[float] = Form(2.0),
) -> ConvertDocumentsParameters:
    return ConvertDocumentsParameters(
        from_formats=_to_list_of_strings(from_formats) if from_formats else None,
        to_formats=_to_list_of_strings(to_formats) if to_formats else None,
        image_export_mode=image_export_mode.strip() if image_export_mode else None,
        ocr=_str_to_bool(do_ocr),
        force_ocr=_str_to_bool(force_ocr),
        ocr_engine=ocr_engine.strip() if ocr_engine else None,
        ocr_lang=ocr_lang.strip() if ocr_lang else None,
        pdf_backend=pdf_backend.strip() if pdf_backend else None,
        table_mode=table_mode.strip() if table_mode else None,
        abort_on_error=_str_to_bool(abort_on_error),
        return_as_file=_str_to_bool(return_as_file),
        do_table_structure=_str_to_bool(do_table_structure),
        include_images=_str_to_bool(include_images),
        images_scale=images_scale,
    )


@app.post("/v1alpha/convert/file")
async def process_file(
    files: List[UploadFile] = File(...),
    parameters: ConvertDocumentsParameters = Depends(_parse_parameters),
):

    _log.info(f"Received {len(files)} files for processing.")

    # Create a temporary directory to store the file(s)
    tmp_input_dir = Path(tempfile.mkdtemp())

    # Save the uploaded files to the temporary directory
    file_paths = []
    for file in files:
        file_location = tmp_input_dir / file.filename  # type: ignore [operator]
        with open(file_location, "wb") as f:
            shutil.copyfileobj(file.file, f)
        file_paths.append(str(file_location))

    # Process the files
    conversion_request = ConvertDocumentsRequest(
        input_sources=file_paths,
        from_formats=parameters.from_formats,
        to_formats=parameters.to_formats,
        image_export_mode=parameters.image_export_mode,
        ocr=parameters.do_ocr,
        force_ocr=parameters.force_ocr,
        ocr_engine=parameters.ocr_engine,
        ocr_lang=parameters.ocr_lang,
        pdf_backend=parameters.pdf_backend,
        table_mode=parameters.table_mode,
        abort_on_error=parameters.abort_on_error,
        return_as_file=parameters.return_as_file,
    )

    results = convert_documents(conversion_request)

    response = process_results(
        conversion_request=conversion_request,
        conv_results=results,
        tmp_input_dir=tmp_input_dir,
    )

    return response


# Launch the FastAPI server
if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    workers = int(os.getenv("UVICORN_WORKERS", "1"))
    reload = _str_to_bool(os.getenv("RELOAD", "False"))
    run(
        "app:app",
        host="0.0.0.0",
        port=port,
        workers=workers,
        timeout_keep_alive=600,
        reload=reload,
    )

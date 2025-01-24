import logging
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, List

from docling.datamodel.base_models import InputFormat
from docling.document_converter import DocumentConverter
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from docling_serve.docling_conversion import (
    ConvertDocumentsParameters,
    ConvertDocumentsRequest,
    convert_documents,
    converters,
    get_pdf_pipeline_opts,
)
from docling_serve.helper_functions import FormDepends, _str_to_bool
from docling_serve.response_preparation import process_results

# Load local env vars if present
load_dotenv()

WITH_UI = _str_to_bool(os.getenv("WITH_UI", "False"))
if WITH_UI:
    import gradio as gr

    from docling_serve.gradio_ui import ui as gradio_ui


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
    if WITH_UI:
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
if WITH_UI:
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


@app.post("/v1alpha/convert/file")
async def process_file(
    files: List[UploadFile],
    parameters: Annotated[
        ConvertDocumentsParameters, FormDepends(ConvertDocumentsParameters)
    ],
):

    _log.info(f"Received {len(files)} files for processing.")

    # Create a temporary directory to store the file(s)
    tmp_input_dir = Path(tempfile.mkdtemp())

    # Save the uploaded files to the temporary directory
    # TODO: we could use the binary stream with Docling directly, using the file could
    # indeed help when many jobs are queued with background tasks.
    file_paths = []
    for file in files:
        file_location = tmp_input_dir / file.filename  # type: ignore [operator]
        with open(file_location, "wb") as f:
            shutil.copyfileobj(file.file, f)
        file_paths.append(str(file_location))

    # Process the files
    conversion_request = ConvertDocumentsRequest(
        input_sources=file_paths, **parameters.model_dump()
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
    from uvicorn import run

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

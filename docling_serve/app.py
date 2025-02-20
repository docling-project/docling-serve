import logging
import tempfile
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional, Union

from fastapi import BackgroundTasks, FastAPI, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.document_converter import DocumentConverter

from docling_serve.docling_conversion import (
    ConvertDocumentFileSourcesRequest,
    ConvertDocumentsOptions,
    ConvertDocumentsRequest,
    convert_documents,
    converters,
    get_pdf_pipeline_opts,
)
from docling_serve.helper_functions import FormDepends
from docling_serve.response_preparation import ConvertDocumentResponse, process_results
from docling_serve.settings import docling_serve_settings


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

    # Converter with default options
    pdf_format_option, options_hash = get_pdf_pipeline_opts(ConvertDocumentsOptions())
    converters[options_hash] = DocumentConverter(
        format_options={
            InputFormat.PDF: pdf_format_option,
            InputFormat.IMAGE: pdf_format_option,
        }
    )

    converters[options_hash].initialize_pipeline(InputFormat.PDF)

    yield

    converters.clear()
    # if WITH_UI:
    #     gradio_ui.close()


##################################
# App creation and configuration #
##################################


def create_app():
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
    if docling_serve_settings.enable_ui:

        try:
            import gradio as gr

            from docling_serve.gradio_ui import ui as gradio_ui

            tmp_output_dir = Path(tempfile.mkdtemp())
            gradio_ui.gradio_output_dir = tmp_output_dir
            app = gr.mount_gradio_app(
                app,
                gradio_ui,
                path="/ui",
                allowed_paths=["./logo.png", tmp_output_dir],
                root_path="/ui",
            )
        except ImportError:
            _log.warning(
                "Docling Serve enable_ui is activated, but gradio is not installed. "
                "Install it with `pip install docling-serve[ui]` "
                "or `pip install gradio`"
            )

    #############################
    # API Endpoints definitions #
    #############################

    # Favicon
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        response = RedirectResponse(
            url="https://ds4sd.github.io/docling/assets/logo.png"
        )
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
    @app.post(
        "/v1alpha/convert/source",
        response_model=ConvertDocumentResponse,
        responses={
            200: {
                "content": {"application/zip": {}},
                # "description": "Return the JSON item or an image.",
            }
        },
    )
    def process_url(
        background_tasks: BackgroundTasks, conversion_request: ConvertDocumentsRequest
    ):
        sources: List[Union[str, DocumentStream]] = []
        headers: Optional[Dict[str, Any]] = None
        if isinstance(conversion_request, ConvertDocumentFileSourcesRequest):
            for file_source in conversion_request.file_sources:
                sources.append(file_source.to_document_stream())
        else:
            for http_source in conversion_request.http_sources:
                sources.append(http_source.url)
                if headers is None and http_source.headers:
                    headers = http_source.headers

        # Note: results are only an iterator->lazy evaluation
        results = convert_documents(
            sources=sources, options=conversion_request.options, headers=headers
        )

        # The real processing will happen here
        response = process_results(
            background_tasks=background_tasks,
            conversion_options=conversion_request.options,
            conv_results=results,
        )

        return response

    # Convert a document from file(s)
    @app.post(
        "/v1alpha/convert/file",
        response_model=ConvertDocumentResponse,
        responses={
            200: {
                "content": {"application/zip": {}},
            }
        },
    )
    async def process_file(
        background_tasks: BackgroundTasks,
        files: List[UploadFile],
        options: Annotated[
            ConvertDocumentsOptions, FormDepends(ConvertDocumentsOptions)
        ],
    ):

        _log.info(f"Received {len(files)} files for processing.")

        # Load the uploaded files to Docling DocumentStream
        file_sources = []
        for file in files:
            buf = BytesIO(file.file.read())
            name = file.filename if file.filename else "file.pdf"
            file_sources.append(DocumentStream(name=name, stream=buf))

        results = convert_documents(sources=file_sources, options=options)

        response = process_results(
            background_tasks=background_tasks,
            conversion_options=options,
            conv_results=results,
        )

        return response

    return app

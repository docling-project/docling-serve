import asyncio
import importlib.metadata
import logging
import tempfile
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Optional, Union

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import (
    get_redoc_html,
    get_swagger_ui_html,
    get_swagger_ui_oauth2_redirect_html,
)
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from docling.datamodel.base_models import DocumentStream

from docling_serve.datamodel.convert import ConvertDocumentsOptions
from docling_serve.datamodel.requests import (
    ConvertDocumentFileSourcesRequest,
    ConvertDocumentsRequest,
)
from docling_serve.datamodel.responses import (
    ConvertDocumentResponse,
    HealthCheckResponse,
    MessageKind,
    TaskStatusResponse,
    WebsocketMessage,
)
from docling_serve.docling_conversion import (
    convert_documents,
    get_converter,
    get_pdf_pipeline_opts,
)
from docling_serve.engines import get_orchestrator
from docling_serve.engines.async_local.orchestrator import (
    AsyncLocalOrchestrator,
    TaskNotFoundError,
)
from docling_serve.helper_functions import FormDepends
from docling_serve.response_preparation import process_results
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
    pdf_format_option = get_pdf_pipeline_opts(ConvertDocumentsOptions())
    get_converter(pdf_format_option)

    orchestrator = get_orchestrator()

    # Start the background queue processor
    queue_task = asyncio.create_task(orchestrator.process_queue())

    yield

    # Cancel the background queue processor on shutdown
    queue_task.cancel()
    try:
        await queue_task
    except asyncio.CancelledError:
        _log.info("Queue processor cancelled.")


##################################
# App creation and configuration #
##################################


def create_app():  # noqa: C901
    try:
        version = importlib.metadata.version("docling_serve")
    except importlib.metadata.PackageNotFoundError:
        _log.warning("Unable to get docling_serve version, falling back to 0.0.0")

        version = "0.0.0"

    offline_docs_assets = False
    if (
        docling_serve_settings.static_path is not None
        and (docling_serve_settings.static_path).is_dir()
    ):
        offline_docs_assets = True
        _log.info("Found static assets.")

    app = FastAPI(
        title="Docling Serve",
        docs_url=None if offline_docs_assets else "/docs",
        redoc_url=None if offline_docs_assets else "/redocs",
        lifespan=lifespan,
        version=version,
    )

    origins = docling_serve_settings.cors_origins
    methods = docling_serve_settings.cors_methods
    headers = docling_serve_settings.cors_headers

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
    # Offline assets definition #
    #############################
    if offline_docs_assets:
        app.mount(
            "/static",
            StaticFiles(directory=docling_serve_settings.static_path),
            name="static",
        )

        @app.get("/docs", include_in_schema=False)
        async def custom_swagger_ui_html():
            return get_swagger_ui_html(
                openapi_url=app.openapi_url,
                title=app.title + " - Swagger UI",
                oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
                swagger_js_url="/static/swagger-ui-bundle.js",
                swagger_css_url="/static/swagger-ui.css",
            )

        @app.get(app.swagger_ui_oauth2_redirect_url, include_in_schema=False)
        async def swagger_ui_redirect():
            return get_swagger_ui_oauth2_redirect_html()

        @app.get("/redoc", include_in_schema=False)
        async def redoc_html():
            return get_redoc_html(
                openapi_url=app.openapi_url,
                title=app.title + " - ReDoc",
                redoc_js_url="/static/redoc.standalone.js",
            )

    #############################
    # API Endpoints definitions #
    #############################

    # Favicon
    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        logo_url = "https://raw.githubusercontent.com/docling-project/docling/refs/heads/main/docs/assets/logo.svg"
        if offline_docs_assets:
            logo_url = "/static/logo.svg"
        response = RedirectResponse(url=logo_url)
        return response

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
        sources: list[Union[str, DocumentStream]] = []
        headers: Optional[dict[str, Any]] = None
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
        files: list[UploadFile],
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

    # Convert a document from URL(s) using the async api
    @app.post(
        "/v1alpha/convert/source/async",
        response_model=TaskStatusResponse,
    )
    async def process_url_async(
        orchestrator: Annotated[AsyncLocalOrchestrator, Depends(get_orchestrator)],
        conversion_request: ConvertDocumentsRequest,
    ):
        task = await orchestrator.enqueue(request=conversion_request)
        task_queue_position = await orchestrator.get_queue_position(
            task_id=task.task_id
        )
        return TaskStatusResponse(
            task_id=task.task_id,
            task_status=task.task_status,
            task_position=task_queue_position,
        )

    # Task status poll
    @app.get(
        "/v1alpha/status/poll/{task_id}",
        response_model=TaskStatusResponse,
    )
    async def task_status_poll(
        orchestrator: Annotated[AsyncLocalOrchestrator, Depends(get_orchestrator)],
        task_id: str,
        wait: Annotated[
            float, Query(help="Number of seconds to wait for a completed status.")
        ] = 0.0,
    ):
        try:
            task = await orchestrator.task_status(task_id=task_id, wait=wait)
            task_queue_position = await orchestrator.get_queue_position(task_id=task_id)
        except TaskNotFoundError:
            raise HTTPException(status_code=404, detail="Task not found.")
        return TaskStatusResponse(
            task_id=task.task_id,
            task_status=task.task_status,
            task_position=task_queue_position,
        )

    # Task status websocket
    @app.websocket(
        "/v1alpha/status/ws/{task_id}",
    )
    async def task_status_ws(
        websocket: WebSocket,
        orchestrator: Annotated[AsyncLocalOrchestrator, Depends(get_orchestrator)],
        task_id: str,
    ):
        await websocket.accept()

        if task_id not in orchestrator.tasks:
            await websocket.send_text(
                WebsocketMessage(
                    message=MessageKind.ERROR, error="Task not found."
                ).model_dump_json()
            )
            await websocket.close()
            return

        task = orchestrator.tasks[task_id]

        # Track active WebSocket connections for this job
        orchestrator.task_subscribers[task_id].add(websocket)

        try:
            task_queue_position = await orchestrator.get_queue_position(task_id=task_id)
            task_response = TaskStatusResponse(
                task_id=task.task_id,
                task_status=task.task_status,
                task_position=task_queue_position,
            )
            await websocket.send_text(
                WebsocketMessage(
                    message=MessageKind.CONNECTION, task=task_response
                ).model_dump_json()
            )
            while True:
                task_queue_position = await orchestrator.get_queue_position(
                    task_id=task_id
                )
                task_response = TaskStatusResponse(
                    task_id=task.task_id,
                    task_status=task.task_status,
                    task_position=task_queue_position,
                )
                await websocket.send_text(
                    WebsocketMessage(
                        message=MessageKind.UPDATE, task=task_response
                    ).model_dump_json()
                )
                # each client message will be interpreted as a request for update
                msg = await websocket.receive_text()
                _log.debug(f"Received message: {msg}")

        except WebSocketDisconnect:
            _log.info(f"WebSocket disconnected for job {task_id}")

        finally:
            orchestrator.task_subscribers[task_id].remove(websocket)

    # Task result
    @app.get(
        "/v1alpha/result/{task_id}",
        response_model=ConvertDocumentResponse,
        responses={
            200: {
                "content": {"application/zip": {}},
            }
        },
    )
    async def task_result(
        orchestrator: Annotated[AsyncLocalOrchestrator, Depends(get_orchestrator)],
        task_id: str,
    ):
        result = await orchestrator.task_result(task_id=task_id)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="Task result not found. Please wait for a completion status.",
            )
        return result

    return app

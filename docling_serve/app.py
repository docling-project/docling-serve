import asyncio
import importlib.metadata
import logging
import shutil
import time
from contextlib import asynccontextmanager
from io import BytesIO
from typing import Annotated

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
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
from scalar_fastapi import get_scalar_api_reference

from docling.datamodel.base_models import DocumentStream
from docling_jobkit.datamodel.callback import (
    ProgressCallbackRequest,
    ProgressCallbackResponse,
)
from docling_jobkit.datamodel.http_inputs import FileSource, HttpSource
from docling_jobkit.datamodel.task import Task, TaskSource
from docling_jobkit.datamodel.task_targets import InBodyTarget, TaskTarget, ZipTarget
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
    ProgressInvalid,
    TaskNotFoundError,
)

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions
from docling_serve.datamodel.requests import (
    ConvertDocumentsRequest,
    FileSourceRequest,
    HttpSourceRequest,
    TargetName,
)
from docling_serve.datamodel.responses import (
    ClearResponse,
    ConvertDocumentResponse,
    HealthCheckResponse,
    MessageKind,
    TaskStatusResponse,
    WebsocketMessage,
)
from docling_serve.helper_functions import FormDepends
from docling_serve.orchestrator_factory import get_async_orchestrator
from docling_serve.response_preparation import prepare_response
from docling_serve.settings import docling_serve_settings
from docling_serve.storage import get_scratch
from docling_serve.websocker_notifier import WebsocketNotifier


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
    scratch_dir = get_scratch()

    orchestrator = get_async_orchestrator()
    notifier = WebsocketNotifier(orchestrator)
    orchestrator.bind_notifier(notifier)

    # Warm up processing cache
    if docling_serve_settings.load_models_at_boot:
        await orchestrator.warm_up_caches()

    # Start the background queue processor
    queue_task = asyncio.create_task(orchestrator.process_queue())

    yield

    # Cancel the background queue processor on shutdown
    queue_task.cancel()
    try:
        await queue_task
    except asyncio.CancelledError:
        _log.info("Queue processor cancelled.")

    # Remove scratch directory in case it was a tempfile
    if docling_serve_settings.scratch_path is not None:
        shutil.rmtree(scratch_dir, ignore_errors=True)


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
        docs_url=None if offline_docs_assets else "/swagger",
        redoc_url=None if offline_docs_assets else "/docs",
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

            tmp_output_dir = get_scratch() / "gradio"
            tmp_output_dir.mkdir(exist_ok=True, parents=True)
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

        @app.get("/swagger", include_in_schema=False)
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

        @app.get("/docs", include_in_schema=False)
        async def redoc_html():
            return get_redoc_html(
                openapi_url=app.openapi_url,
                title=app.title + " - ReDoc",
                redoc_js_url="/static/redoc.standalone.js",
            )

    @app.get("/scalar", include_in_schema=False)
    async def scalar_html():
        return get_scalar_api_reference(
            openapi_url=app.openapi_url,
            title=app.title,
            scalar_favicon_url="https://raw.githubusercontent.com/docling-project/docling/refs/heads/main/docs/assets/logo.svg",
            # hide_client_button=True,  # not yet released but in main
        )

    ########################
    # Async / Sync helpers #
    ########################

    async def _enque_source(
        orchestrator: BaseOrchestrator, conversion_request: ConvertDocumentsRequest
    ) -> Task:
        sources: list[TaskSource] = []
        for s in conversion_request.sources:
            if isinstance(s, FileSourceRequest):
                sources.append(FileSource.model_validate(s))
            elif isinstance(s, HttpSourceRequest):
                sources.append(HttpSource.model_validate(s))

        task = await orchestrator.enqueue(
            sources=sources,
            options=conversion_request.options,
            target=conversion_request.target,
        )
        return task

    async def _enque_file(
        orchestrator: BaseOrchestrator,
        files: list[UploadFile],
        options: ConvertDocumentsRequestOptions,
        target: TaskTarget,
    ) -> Task:
        _log.info(f"Received {len(files)} files for processing.")

        # Load the uploaded files to Docling DocumentStream
        file_sources: list[TaskSource] = []
        for i, file in enumerate(files):
            buf = BytesIO(file.file.read())
            suffix = "" if len(file_sources) == 1 else f"_{i}"
            name = file.filename if file.filename else f"file{suffix}.pdf"
            file_sources.append(DocumentStream(name=name, stream=buf))

        task = await orchestrator.enqueue(
            sources=file_sources, options=options, target=target
        )
        return task

    async def _wait_task_complete(orchestrator: BaseOrchestrator, task_id: str) -> bool:
        start_time = time.monotonic()
        while True:
            task = await orchestrator.task_status(task_id=task_id)
            if task.is_completed():
                return True
            await asyncio.sleep(5)
            elapsed_time = time.monotonic() - start_time
            if elapsed_time > docling_serve_settings.max_sync_wait:
                return False

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
        "/v1/convert/source",
        response_model=ConvertDocumentResponse,
        responses={
            200: {
                "content": {"application/zip": {}},
                # "description": "Return the JSON item or an image.",
            }
        },
    )
    async def process_url(
        background_tasks: BackgroundTasks,
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        conversion_request: ConvertDocumentsRequest,
    ):
        task = await _enque_source(
            orchestrator=orchestrator, conversion_request=conversion_request
        )
        completed = await _wait_task_complete(
            orchestrator=orchestrator, task_id=task.task_id
        )

        if not completed:
            # TODO: abort task!
            return HTTPException(
                status_code=504,
                detail=f"Conversion is taking too long. The maximum wait time is configure as DOCLING_SERVE_MAX_SYNC_WAIT={docling_serve_settings.max_sync_wait}.",
            )

        task = await orchestrator.get_raw_task(task_id=task.task_id)
        response = await prepare_response(
            task=task, orchestrator=orchestrator, background_tasks=background_tasks
        )
        return response

    # Convert a document from file(s)
    @app.post(
        "/v1/convert/file",
        response_model=ConvertDocumentResponse,
        responses={
            200: {
                "content": {"application/zip": {}},
            }
        },
    )
    async def process_file(
        background_tasks: BackgroundTasks,
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        files: list[UploadFile],
        options: Annotated[
            ConvertDocumentsRequestOptions, FormDepends(ConvertDocumentsRequestOptions)
        ],
        target_type: Annotated[TargetName, Form()] = TargetName.INBODY,
    ):
        target = InBodyTarget() if target_type == TargetName.INBODY else ZipTarget()
        task = await _enque_file(
            orchestrator=orchestrator, files=files, options=options, target=target
        )
        completed = await _wait_task_complete(
            orchestrator=orchestrator, task_id=task.task_id
        )

        if not completed:
            # TODO: abort task!
            return HTTPException(
                status_code=504,
                detail=f"Conversion is taking too long. The maximum wait time is configure as DOCLING_SERVE_MAX_SYNC_WAIT={docling_serve_settings.max_sync_wait}.",
            )

        task = await orchestrator.get_raw_task(task_id=task.task_id)
        response = await prepare_response(
            task=task, orchestrator=orchestrator, background_tasks=background_tasks
        )
        return response

    # Convert a document from URL(s) using the async api
    @app.post(
        "/v1/convert/source/async",
        response_model=TaskStatusResponse,
    )
    async def process_url_async(
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        conversion_request: ConvertDocumentsRequest,
    ):
        task = await _enque_source(
            orchestrator=orchestrator, conversion_request=conversion_request
        )
        task_queue_position = await orchestrator.get_queue_position(
            task_id=task.task_id
        )
        return TaskStatusResponse(
            task_id=task.task_id,
            task_status=task.task_status,
            task_position=task_queue_position,
            task_meta=task.processing_meta,
        )

    # Convert a document from file(s) using the async api
    @app.post(
        "/v1/convert/file/async",
        response_model=TaskStatusResponse,
    )
    async def process_file_async(
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        background_tasks: BackgroundTasks,
        files: list[UploadFile],
        options: Annotated[
            ConvertDocumentsRequestOptions, FormDepends(ConvertDocumentsRequestOptions)
        ],
        target_type: Annotated[TargetName, Form()] = TargetName.INBODY,
    ):
        target = InBodyTarget() if target_type == TargetName.INBODY else ZipTarget()
        task = await _enque_file(
            orchestrator=orchestrator, files=files, options=options, target=target
        )
        task_queue_position = await orchestrator.get_queue_position(
            task_id=task.task_id
        )
        return TaskStatusResponse(
            task_id=task.task_id,
            task_status=task.task_status,
            task_position=task_queue_position,
            task_meta=task.processing_meta,
        )

    # Task status poll
    @app.get(
        "/v1/status/poll/{task_id}",
        response_model=TaskStatusResponse,
    )
    async def task_status_poll(
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
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
            task_meta=task.processing_meta,
        )

    # Task status websocket
    @app.websocket(
        "/v1/status/ws/{task_id}",
    )
    async def task_status_ws(
        websocket: WebSocket,
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        task_id: str,
    ):
        assert isinstance(orchestrator.notifier, WebsocketNotifier)
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
        orchestrator.notifier.task_subscribers[task_id].add(websocket)

        try:
            task_queue_position = await orchestrator.get_queue_position(task_id=task_id)
            task_response = TaskStatusResponse(
                task_id=task.task_id,
                task_status=task.task_status,
                task_position=task_queue_position,
                task_meta=task.processing_meta,
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
                    task_meta=task.processing_meta,
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
            orchestrator.notifier.task_subscribers[task_id].remove(websocket)

    # Task result
    @app.get(
        "/v1/result/{task_id}",
        response_model=ConvertDocumentResponse,
        responses={
            200: {
                "content": {"application/zip": {}},
            }
        },
    )
    async def task_result(
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        background_tasks: BackgroundTasks,
        task_id: str,
    ):
        try:
            task = await orchestrator.get_raw_task(task_id=task_id)
            response = await prepare_response(
                task=task, orchestrator=orchestrator, background_tasks=background_tasks
            )
            return response
        except TaskNotFoundError:
            raise HTTPException(status_code=404, detail="Task not found.")

    # Update task progress
    @app.post(
        "/v1/callback/task/progress",
        response_model=ProgressCallbackResponse,
    )
    async def callback_task_progress(
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        request: ProgressCallbackRequest,
    ):
        try:
            await orchestrator.receive_task_progress(request=request)
            return ProgressCallbackResponse(status="ack")
        except TaskNotFoundError:
            raise HTTPException(status_code=404, detail="Task not found.")
        except ProgressInvalid as err:
            raise HTTPException(
                status_code=400, detail=f"Invalid progress payload: {err}"
            )

    #### Clear requests

    # Offload models
    @app.get(
        "/v1/clear/converters",
        response_model=ClearResponse,
    )
    async def clear_converters(
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
    ):
        await orchestrator.clear_converters()
        return ClearResponse()

    # Clean results
    @app.get(
        "/v1/clear/results",
        response_model=ClearResponse,
    )
    async def clear_results(
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        older_then: float = 3600,
    ):
        await orchestrator.clear_results(older_than=older_then)
        return ClearResponse()

    return app

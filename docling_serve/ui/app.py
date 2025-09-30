import io
import logging
from pathlib import Path
from typing import Annotated

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AnyHttpUrl
from pyjsx import auto_setup
from starlette.exceptions import HTTPException as StarletteHTTPException

from docling.datamodel.base_models import OutputFormat
from docling_core.types.doc.document import (
    FloatingItem,
    PageItem,
    RefItem,
)
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
)

from docling_serve.auth import APIKeyCookieAuth, AuthenticationResult
from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions
from docling_serve.datamodel.requests import ConvertDocumentsRequest, HttpSourceRequest
from docling_serve.helper_functions import FormDepends
from docling_serve.orchestrator_factory import get_async_orchestrator
from docling_serve.settings import docling_serve_settings

from .convert import ConvertPage  # type: ignore
from .pages import AuthPage, StatusPage, TaskPage, TasksPage  # type: ignore

# Initialize JSX.
auto_setup

_log = logging.getLogger(__name__)


# TODO: Isolate passed functions into a controller?
def create_ui_app(process_file, process_url, task_result, task_status_poll) -> FastAPI:  # noqa: C901
    ui_app = FastAPI()
    require_auth = APIKeyCookieAuth(docling_serve_settings.api_key)

    # Static files.
    ui_app.mount(
        "/static",
        StaticFiles(directory=Path(__file__).parent.absolute() / "static"),
        name="static",
    )

    # Convert page.
    @ui_app.get("/")
    async def get_root():
        return RedirectResponse(url="convert")

    @ui_app.get("/convert", response_class=HTMLResponse)
    async def get_convert(
        auth: Annotated[AuthenticationResult, Depends(require_auth)],
    ):
        return str(ConvertPage())

    @ui_app.post("/convert", response_class=HTMLResponse)
    async def post_convert(
        auth: Annotated[AuthenticationResult, Depends(require_auth)],
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        background_tasks: BackgroundTasks,
        options: Annotated[
            ConvertDocumentsRequestOptions, FormDepends(ConvertDocumentsRequestOptions)
        ],
        files: Annotated[list[UploadFile], Form()],
        url: Annotated[str, Form()],
        page_min: Annotated[str, Form()],
        page_max: Annotated[str, Form()],
    ):
        # Refined model options and behavior.
        if len(page_min) > 0:
            options.page_range = (int(page_min), options.page_range[1])
        if len(page_max) > 0:
            options.page_range = (options.page_range[0], int(page_max))

        options.ocr_lang = [
            sub_lang.strip()
            for lang in options.ocr_lang or []
            for sub_lang in lang.split(",")
            if len(sub_lang.strip()) > 0
        ]

        files = [f for f in files if f.size]
        if len(files) > 0:
            # Directly uploaded documents.
            response = await process_file(
                auth=auth,
                orchestrator=orchestrator,
                background_tasks=background_tasks,
                files=files,
                options=options,
            )
        elif len(url.strip()) > 0:
            # URLs of documents.
            source = HttpSourceRequest(url=AnyHttpUrl(url))
            request = ConvertDocumentsRequest(options=options, sources=[source])

            response = await process_url(
                auth=auth,
                orchestrator=orchestrator,
                conversion_request=request,
            )
        else:
            validation = {
                "files": "Upload files or enter a URL",
                "url": "Enter a URL or upload files",
            }
            return str(ConvertPage(options=options, validation=validation))

        return RedirectResponse(f"tasks/{response.task_id}/", status.HTTP_303_SEE_OTHER)

    # Task overview page.
    @ui_app.get("/tasks/", response_class=HTMLResponse)
    async def get_tasks(
        auth: Annotated[AuthenticationResult, Depends(require_auth)],
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
    ):
        tasks = sorted(orchestrator.tasks.values(), key=lambda t: t.created_at)

        return str(TasksPage(tasks=tasks))

    # Task specific page.
    @ui_app.get("/tasks/{task_id}/", response_class=HTMLResponse)
    async def get_task(
        auth: Annotated[AuthenticationResult, Depends(require_auth)],
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        background_tasks: BackgroundTasks,
        task_id: str,
    ):
        poll = await task_status_poll(auth, orchestrator, task_id)

        result = None
        if poll.task_status in ["success", "failure"]:
            try:
                result = await task_result(
                    auth, orchestrator, background_tasks, task_id
                )
            except Exception as ex:
                logging.error(ex)

        return str(TaskPage(poll, result))

    # Poll task via HTTP status.
    @ui_app.get("/tasks/{task_id}/poll", response_class=Response)
    async def poll_task(
        auth: Annotated[AuthenticationResult, Depends(require_auth)],
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        task_id: str,
    ):
        poll = await task_status_poll(auth, orchestrator, task_id)
        return Response(
            status_code=status.HTTP_202_ACCEPTED
            if poll.task_status == "started"
            else status.HTTP_200_OK
        )

    # Download the contents of zipped documents.
    @ui_app.get("/tasks/{task_id}/documents.zip")
    async def get_task_zip(
        auth: Annotated[AuthenticationResult, Depends(require_auth)],
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        background_tasks: BackgroundTasks,
        task_id: str,
    ):
        return await task_result(auth, orchestrator, background_tasks, task_id)

    # Get the output of a task, as a converted document in a specific format.
    @ui_app.get("/tasks/{task_id}/document.{format}")
    async def get_task_document_format(
        auth: Annotated[AuthenticationResult, Depends(require_auth)],
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        background_tasks: BackgroundTasks,
        task_id: str,
        format: str,
    ):
        if format not in [f.value for f in OutputFormat]:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Output format not found.")
        else:
            response = await task_result(auth, orchestrator, background_tasks, task_id)

        # TODO: Make this compatible with base_models FormatToMimeType?
        mimes = {
            "html": "text/html",
            "md": "text/markdown",
            "json": "application/json",
        }

        content = (
            response.document.json_content.export_to_dict()
            if format == OutputFormat.JSON
            else response.document.dict()[f"{format}_content"]
        )

        return Response(
            content=str(content),
            media_type=mimes.get(format, "text/plain"),
        )

    @ui_app.get("/tasks/{task_id}/document/{cref:path}")
    async def get_task_document_item(
        request: Request,
        auth: Annotated[AuthenticationResult, Depends(require_auth)],
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        background_tasks: BackgroundTasks,
        task_id: str,
        cref: str,
    ):
        response = await task_result(auth, orchestrator, background_tasks, task_id)
        doc = response.document.json_content
        item = RefItem(cref=f"#/{cref}").resolve(doc)  # type: ignore

        if "image/*" in (request.headers.get("Accept") or "") and isinstance(
            item, FloatingItem | PageItem
        ):
            content = io.BytesIO()

            if (
                isinstance(item, PageItem)
                and (img_ref := item.image)
                and img_ref.pil_image
            ):
                img_ref.pil_image.save(content, format="PNG")
            elif isinstance(item, FloatingItem) and (img := item.get_image(doc)):
                img.save(content, format="PNG")

            return Response(content=content.getvalue(), media_type="image/png")
        else:
            return item

    # Page not found; catch all.
    @ui_app.api_route("/{path_name:path}")
    def no_page(
        auth: Annotated[AuthenticationResult, Depends(require_auth)],
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Page not found.")

    # Exception and auth pages.
    @ui_app.exception_handler(StarletteHTTPException)
    @ui_app.exception_handler(Exception)
    async def exception_page(request: Request, ex: Exception):
        if not isinstance(ex, StarletteHTTPException):
            # Internal error.
            ex = HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR)

        if request.method == "POST":
            # Authorization required -> API key dialog.
            form = await request.form()
            form_api_key = form.get("api_key")
            if isinstance(form_api_key, str):
                response = RedirectResponse(request.url, status.HTTP_303_SEE_OTHER)
                require_auth._set_api_key(response, form_api_key)
                return response

        if ex.status_code == status.HTTP_401_UNAUTHORIZED:
            return HTMLResponse(str(AuthPage()), status.HTTP_401_UNAUTHORIZED)

        # HTTP exception page; avoid referer loop.
        referer = request.headers.get("Referer")
        if referer == request.url:
            referer = None

        return HTMLResponse(str(StatusPage(ex, referer)), ex.status_code)

    return ui_app

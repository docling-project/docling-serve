import io
import unicodedata
import zipfile
from urllib.parse import quote

from fastapi import BackgroundTasks, Response

from docling.datamodel.service.responses import (
    ChunkDocumentResponse,
    ChunkedDocumentResult,
    ConvertDocumentResponse,
    DoclingTaskResult,
    ExportResult,
    PresignedArtifactResult,
    PresignedUrlConvertDocumentResponse,
    PresignedUrlConvertResponse,
    RemoteTargetResult,
    ZipArchiveResult,
)
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
)

from docling_serve.settings import docling_serve_settings

DEFAULT_ZIP_FILENAME = "converted_docs.zip"

# Suffixes of the per-document files docling-jobkit writes as ``<stem><suffix>``.
_EXPORT_SUFFIXES = (
    ".chunks.jsonl",
    ".json",
    ".html",
    ".md",
    ".txt",
    ".doctags",
    ".dclg",
    ".dclx",
)
# Consolidated output of chunking tasks, covering every document in the task.
_CHUNKING_RESULT_FILENAME = "chunked_result.json"


def _zip_filename(content: bytes) -> str:
    """Name the archive after its document when it holds exactly one."""
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()
    except zipfile.BadZipFile:
        return DEFAULT_ZIP_FILENAME

    stems = set()
    for name in names:
        if "/" in name:
            continue  # entries under artifacts/ (referenced images)
        if name == _CHUNKING_RESULT_FILENAME:
            return DEFAULT_ZIP_FILENAME
        suffix = next((s for s in _EXPORT_SUFFIXES if name.endswith(s)), None)
        if suffix is None:
            return DEFAULT_ZIP_FILENAME
        stems.add(name[: -len(suffix)])

    if len(stems) != 1:
        return DEFAULT_ZIP_FILENAME
    stem = stems.pop()
    if not stem:
        return DEFAULT_ZIP_FILENAME
    return f"{stem}.zip"


def _content_disposition(filename: str) -> str:
    """Build an attachment header that is safe for non-ASCII filenames (RFC 6266)."""
    ascii_name = "".join(
        c if c.isprintable() and c not in '"\\' else "_"
        for c in unicodedata.normalize("NFKD", filename)
        .encode("ascii", "ignore")
        .decode("ascii")
    )
    if ascii_name in ("", ".zip"):
        ascii_name = DEFAULT_ZIP_FILENAME
    header = f'attachment; filename="{ascii_name}"'
    if ascii_name != filename:
        header += f"; filename*=UTF-8''{quote(filename, safe='')}"
    return header


async def prepare_response(
    task_id: str,
    task_result: DoclingTaskResult,
    orchestrator: BaseOrchestrator,
    background_tasks: BackgroundTasks,
):
    response: (
        Response
        | ConvertDocumentResponse
        | PresignedUrlConvertDocumentResponse
        | PresignedUrlConvertResponse
        | ChunkDocumentResponse
    )
    if isinstance(task_result.result, ExportResult):
        response = ConvertDocumentResponse(
            document=task_result.result.document,
            status=task_result.result.status,
            processing_time=task_result.processing_time,
            timings=task_result.result.timings,
            errors=task_result.result.errors,
            confidence=task_result.result.confidence,
        )
    elif isinstance(task_result.result, ZipArchiveResult):
        response = Response(
            content=task_result.result.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": _content_disposition(
                    _zip_filename(task_result.result.content)
                )
            },
        )
    elif isinstance(task_result.result, RemoteTargetResult):
        response = PresignedUrlConvertDocumentResponse(
            processing_time=task_result.processing_time,
            num_converted=task_result.num_converted,
            num_succeeded=task_result.num_succeeded,
            num_partially_succeeded=task_result.num_partially_succeeded,
            num_failed=task_result.num_failed,
        )
    elif isinstance(task_result.result, PresignedArtifactResult):
        response = PresignedUrlConvertResponse(
            documents=task_result.result.documents,
            processing_time=task_result.processing_time,
            num_converted=task_result.num_converted,
            num_succeeded=task_result.num_succeeded,
            num_partially_succeeded=task_result.num_partially_succeeded,
            num_failed=task_result.num_failed,
        )
    elif isinstance(task_result.result, ChunkedDocumentResult):
        response = ChunkDocumentResponse(
            chunks=task_result.result.chunks,
            documents=task_result.result.documents,
            processing_time=task_result.processing_time,
        )
    else:
        raise ValueError("Unknown result type")

    if docling_serve_settings.single_use_results:
        background_tasks.add_task(orchestrator.on_result_fetched, task_id)

    return response

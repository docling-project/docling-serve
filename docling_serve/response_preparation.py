from fastapi import BackgroundTasks, Response
from fastapi.responses import JSONResponse

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
from docling_jobkit.datamodel.exportable_document import project_document_dict
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
)

from docling_serve.settings import docling_serve_settings


async def prepare_response(
    task_id: str,
    task_result: DoclingTaskResult,
    orchestrator: BaseOrchestrator,
    background_tasks: BackgroundTasks,
    target_document_version: str | None = None,
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
        json_content = task_result.result.document.json_content
        projected = (
            project_document_dict(json_content, target_document_version)
            if json_content is not None
            else None
        )
        if projected is not None:
            # Emit the projected dict as-is; the DoclingDocument model would
            # re-add newer fields and its native version when serialized.
            content = response.model_dump(mode="json", by_alias=True)
            content["document"]["json_content"] = projected
            response = JSONResponse(content)
    elif isinstance(task_result.result, ZipArchiveResult):
        response = Response(
            content=task_result.result.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="converted_docs.zip"'
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

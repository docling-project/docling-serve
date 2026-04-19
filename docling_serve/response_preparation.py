import json
import logging
from pathlib import Path
from urllib.parse import unquote, unquote_plus

from fastapi import BackgroundTasks, Response

from docling_jobkit.datamodel.result import (
    ChunkedDocumentResult,
    DoclingTaskResult,
    ExportResult,
    RemoteTargetResult,
    ZipArchiveResult,
)
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
)

from docling_serve.datamodel.responses import (
    ChunkDocumentResponse,
    ConvertDocumentPublishedResponse,
    ConvertDocumentResponse,
    PresignedUrlConvertDocumentResponse,
    PublishedArtifactResponse,
)
from docling_serve.resource_rewriter import rewrite_export_document, upload_file_and_collect
from docling_serve.settings import docling_serve_settings

_log = logging.getLogger(__name__)


def _publish_text_file(filename: str, suffix: str, content: str):
    base_dir = Path(docling_serve_settings.resource_local_base_dir or ".")
    base_dir.mkdir(parents=True, exist_ok=True)
    decoded_filename = filename
    for decoder in [unquote, unquote_plus]:
        try:
            candidate = decoder(filename)
            if '%' not in candidate and candidate != filename:
                decoded_filename = candidate
                break
        except Exception:
            pass
    out_path = base_dir / f"{Path(decoded_filename).stem}{suffix}"
    out_path.write_text(content, encoding="utf-8")
    return upload_file_and_collect(out_path)


async def prepare_response(
    task_id: str,
    task_result: DoclingTaskResult,
    orchestrator: BaseOrchestrator,
    background_tasks: BackgroundTasks,
):
    response: (
        Response
        | ConvertDocumentResponse
        | ConvertDocumentPublishedResponse
        | PresignedUrlConvertDocumentResponse
        | ChunkDocumentResponse
    )
    if isinstance(task_result.result, ExportResult):
        _log.warning("DIAG prep before rewrite filename=%s output_dir=%s", getattr(task_result.result.content, "filename", None), getattr(task_result.result.content, "output_dir", None))
        rewritten_document = rewrite_export_document(task_result.result.content)
        _log.warning("DIAG prep after rewrite filename=%s output_dir=%s", getattr(rewritten_document, "filename", None), getattr(rewritten_document, "output_dir", None))
        if getattr(rewritten_document, "json_content", None) is not None:
            base_dir = Path(docling_serve_settings.resource_local_base_dir or ".")
            base_dir.mkdir(parents=True, exist_ok=True)
            raw_filename = rewritten_document.filename
            decoded_filename = raw_filename
            for decoder in [unquote, unquote_plus]:
                try:
                    candidate = decoder(raw_filename)
                    if '%' not in candidate and candidate != raw_filename:
                        decoded_filename = candidate
                        break
                except Exception:
                    pass
            filename = Path(decoded_filename).stem + ".json"
            json_path = base_dir / filename
            json_payload = rewritten_document.json_content.model_dump(mode="json")

            # 修正 JSON 内部的 name 和 origin.filename
            if "name" in json_payload and json_payload["name"]:
                json_payload["name"] = decoded_filename
            if "origin" in json_payload and isinstance(json_payload["origin"], dict):
                if "filename" in json_payload["origin"]:
                    json_payload["origin"]["filename"] = decoded_filename

            json_path.write_text(
                json.dumps(json_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            upload_meta = upload_file_and_collect(json_path)
            response = ConvertDocumentPublishedResponse(
                artifact=PublishedArtifactResponse(**upload_meta),
                status=task_result.result.status,
                processing_time=task_result.processing_time,
                timings=task_result.result.timings,
                errors=task_result.result.errors,
            )
        elif getattr(rewritten_document, "md_content", None):
            upload_meta = _publish_text_file(
                rewritten_document.filename,
                ".md",
                rewritten_document.md_content,
            )
            response = ConvertDocumentPublishedResponse(
                artifact=PublishedArtifactResponse(**upload_meta),
                status=task_result.result.status,
                processing_time=task_result.processing_time,
                timings=task_result.result.timings,
                errors=task_result.result.errors,
            )
        elif getattr(rewritten_document, "html_content", None):
            upload_meta = _publish_text_file(
                rewritten_document.filename,
                ".html",
                rewritten_document.html_content,
            )
            response = ConvertDocumentPublishedResponse(
                artifact=PublishedArtifactResponse(**upload_meta),
                status=task_result.result.status,
                processing_time=task_result.processing_time,
                timings=task_result.result.timings,
                errors=task_result.result.errors,
            )
        elif getattr(rewritten_document, "text_content", None):
            upload_meta = _publish_text_file(
                rewritten_document.filename,
                ".txt",
                rewritten_document.text_content,
            )
            response = ConvertDocumentPublishedResponse(
                artifact=PublishedArtifactResponse(**upload_meta),
                status=task_result.result.status,
                processing_time=task_result.processing_time,
                timings=task_result.result.timings,
                errors=task_result.result.errors,
            )
        else:
            response = ConvertDocumentResponse(
                document=type(task_result.result.content).model_validate(
                    rewritten_document.model_dump(mode="json")
                ),
                status=task_result.result.status,
                processing_time=task_result.processing_time,
                timings=task_result.result.timings,
                errors=task_result.result.errors,
            )
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

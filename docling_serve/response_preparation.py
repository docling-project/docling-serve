import json
import logging
import re
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

_CJK_CHAR_RE = r"\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
_CJK_PUNCT_RE = r"，。！？；：、】【（）《》“”‘’、"
_CJK_CHAR_CLASS = f"[{_CJK_CHAR_RE}]"
_CJK_OR_PUNCT_CLASS = f"[{_CJK_CHAR_RE}{_CJK_PUNCT_RE}]"


def _merge_broken_cjk_lines(text: str) -> str:
    lines = text.splitlines()
    if len(lines) <= 1:
        return text

    merged: list[str] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not merged:
            merged.append(line)
            continue
        if not line:
            merged.append(line)
            continue

        prev = merged[-1]
        if not prev:
            merged.append(line)
            continue

        is_new_block = bool(
            re.match(r"^(#{1,6}\s|[-*+]\s|\d+[.)、]\s*|[（(]?[一二三四五六七八九十]+[）)]\s*)", line)
        )
        prev_ends_sentence = bool(re.search(r"[。！？!?；;：:]$", prev))
        line_is_short_cjk = bool(re.fullmatch(rf"{_CJK_OR_PUNCT_CLASS}{{1,6}}", line))
        prev_ends_with_cjk = bool(re.search(rf"{_CJK_OR_PUNCT_CLASS}$", prev))
        line_starts_with_cjk = bool(re.match(rf"^{_CJK_OR_PUNCT_CLASS}", line))

        if not is_new_block and not prev_ends_sentence and (
            line_is_short_cjk or (prev_ends_with_cjk and line_starts_with_cjk)
        ):
            merged[-1] = prev + line
        else:
            merged.append(line)

    return "\n".join(merged)


def _normalize_cjk_spacing(text: str) -> str:
    text = _merge_broken_cjk_lines(text)
    text = re.sub(rf"(?<={_CJK_CHAR_CLASS})[ \t]+(?={_CJK_CHAR_CLASS})", "", text)
    text = re.sub(rf"(?<={_CJK_OR_PUNCT_CLASS})[ \t]+(?=[{_CJK_PUNCT_RE}])", "", text)
    text = re.sub(rf"(?<=[{_CJK_PUNCT_RE}])[ \t]+(?={_CJK_OR_PUNCT_CLASS})", "", text)
    text = re.sub(rf"([（《“‘【])\s+(?={_CJK_OR_PUNCT_CLASS})", r"\1", text)
    text = re.sub(rf"(?<={_CJK_OR_PUNCT_CLASS})\s+([）》”’】])", r"\1", text)
    return text


def _normalize_export_json_payload(payload: object):
    if isinstance(payload, dict):
        return {k: _normalize_export_json_payload(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_normalize_export_json_payload(v) for v in payload]
    if isinstance(payload, str):
        return _normalize_cjk_spacing(payload)
    return payload


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
    normalized_content = _normalize_cjk_spacing(content)
    out_path.write_text(normalized_content, encoding="utf-8")
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
            json_payload = _normalize_export_json_payload(json_payload)

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

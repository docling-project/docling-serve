import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import unquote

import pytest
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from docling.datamodel.base_models import ConversionStatus
from docling.datamodel.service.responses import (
    ConvertDocumentResponse,
    DoclingTaskResult,
    ExportDocumentResponse,
    ExportResult,
    ZipArchiveResult,
)
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel

from docling_serve.response_preparation import _content_disposition, prepare_response


def _stored_result() -> DoclingTaskResult:
    doc = DoclingDocument(name="sample")
    doc.add_text(label=DocItemLabel.TEXT, text="hello")
    result = DoclingTaskResult(
        result=ExportResult(
            document=ExportDocumentResponse(filename="a.pdf", json_content=doc),
            status=ConversionStatus.SUCCESS,
        ),
        processing_time=0.1,
        num_converted=1,
        num_succeeded=1,
        num_failed=0,
    )
    # Mimic the RQ/Ray Redis round-trip, which re-validates the document.
    return DoclingTaskResult.model_validate(result.model_dump())


async def _prepare(target_document_version: str | None):
    return await prepare_response(
        task_id="t",
        task_result=_stored_result(),
        orchestrator=SimpleNamespace(on_result_fetched=None),  # type: ignore[arg-type]
        background_tasks=BackgroundTasks(),
        target_document_version=target_document_version,
    )


@pytest.mark.asyncio
async def test_in_body_json_is_projected_after_redis_round_trip():
    response = await _prepare("1.5.0")

    assert isinstance(response, JSONResponse)
    json_content = json.loads(response.body)["document"]["json_content"]
    assert json_content["version"] == "1.5.0"
    assert "meta" not in json.dumps(json_content)
    assert json_content["texts"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_in_body_json_untouched_without_target():
    response = await _prepare(None)

    assert isinstance(response, ConvertDocumentResponse)


def test_content_disposition_ascii():
    assert _content_disposition("report.zip") == 'attachment; filename="report.zip"'


def test_content_disposition_non_ascii():
    header = _content_disposition("Übersicht für Prüfung.zip")
    assert header.startswith(
        "attachment; filename=\"Ubersicht fur Prufung.zip\"; filename*=UTF-8''"
    )
    encoded = header.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == "Übersicht für Prüfung.zip"
    header.encode("latin-1")  # must be a valid HTTP header value


def test_content_disposition_only_non_ascii():
    header = _content_disposition("日本語.zip")
    assert header.startswith('attachment; filename="converted_docs.zip"; ')
    assert unquote(header.split("filename*=UTF-8''", 1)[1]) == "日本語.zip"


def test_content_disposition_escapes_unsafe_chars():
    header = _content_disposition('a"b\\c\r\nX-Injected: 1.zip')
    ascii_part = header.split(";")[1]
    assert ascii_part == ' filename="a_b_c__X-Injected: 1.zip"'
    assert "\r" not in header and "\n" not in header


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        # docling-jobkit sets the name when the task had exactly one document.
        ("report.zip", 'attachment; filename="report.zip"'),
        (
            "Übersicht.zip",
            "attachment; filename=\"Ubersicht.zip\"; filename*=UTF-8''%C3%9Cbersicht.zip",
        ),
        # Several documents (or an older worker) leave it unset.
        (None, 'attachment; filename="converted_docs.zip"'),
    ],
)
async def test_prepare_response_zip_filename(filename, expected):
    task_result = DoclingTaskResult(
        result=ZipArchiveResult(content=b"PK", filename=filename),
        processing_time=0.0,
        num_converted=1,
        num_succeeded=1,
        num_partially_succeeded=0,
        num_failed=0,
    )
    response = await prepare_response(
        task_id="task",
        task_result=task_result,
        orchestrator=MagicMock(),
        background_tasks=BackgroundTasks(),
    )
    assert response.headers["content-disposition"] == expected
    assert response.media_type == "application/zip"

import io
import zipfile
from unittest.mock import MagicMock
from urllib.parse import unquote

import pytest
from fastapi import BackgroundTasks

from docling.datamodel.service.responses import DoclingTaskResult, ZipArchiveResult

from docling_serve.response_preparation import (
    _content_disposition,
    _zip_filename,
    prepare_response,
)


def _make_zip(names: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in names:
            zf.writestr(name, b"" if name.endswith("/") else b"x")
    return buf.getvalue()


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["report.md"], "report.zip"),
        (
            ["report.md", "report.json", "report.html", "report.txt"],
            "report.zip",
        ),
        (["report.doctags", "report.dclg", "report.dclx"], "report.zip"),
        (["report.md", "report.chunks.jsonl"], "report.zip"),
        (
            ["report.md", "artifacts/", "artifacts/image_000000.png"],
            "report.zip",
        ),
        (["annual.report.v2.md", "annual.report.v2.json"], "annual.report.v2.zip"),
        (["Übersicht.md"], "Übersicht.zip"),
        # Multiple documents keep the generic name.
        (["a.md", "b.md"], "converted_docs.zip"),
        (["a.md", "a.json", "b.json"], "converted_docs.zip"),
        # Archives that are not per-document exports keep the generic name.
        (["chunked_result.json"], "converted_docs.zip"),
        (["chunked_result.json", "artifacts/image_000000.png"], "converted_docs.zip"),
        (["unknown.bin"], "converted_docs.zip"),
        (["report.md", "notes.bin"], "converted_docs.zip"),
        ([".md"], "converted_docs.zip"),
        ([], "converted_docs.zip"),
    ],
)
def test_zip_filename(names, expected):
    assert _zip_filename(_make_zip(names)) == expected


def test_zip_filename_invalid_zip():
    assert _zip_filename(b"not a zip") == "converted_docs.zip"


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
    ("names", "expected"),
    [
        (["report.md", "report.json"], 'attachment; filename="report.zip"'),
        (["a.md", "b.md"], 'attachment; filename="converted_docs.zip"'),
    ],
)
async def test_prepare_response_zip_filename(names, expected):
    task_result = DoclingTaskResult(
        result=ZipArchiveResult(content=_make_zip(names)),
        processing_time=0.0,
        num_converted=len(names),
        num_succeeded=len(names),
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

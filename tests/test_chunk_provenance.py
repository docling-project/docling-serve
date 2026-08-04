import base64
from collections.abc import Iterator
from pathlib import Path, PurePath
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient, Response

from docling.datamodel.base_models import ConversionStatus
from docling.datamodel.service.chunking import HierarchicalChunkerOptions
from docling.datamodel.service.options import ConvertDocumentsOptions
from docling.datamodel.service.responses import (
    ChunkDocumentResponse,
    ChunkedDocumentResult,
    ChunkedDocumentResultItem,
    DoclingTaskResult,
    DocumentResultItem,
    ExportDocumentResponse,
    ZipArchiveResult,
)
from docling.datamodel.service.targets import InBodyTarget, ZipTarget
from docling.datamodel.service.tasks import TaskType
from docling_core.types.doc.document import (
    BoundingBox,
    DocItemLabel,
    DoclingDocument,
    ImageRefMode,
    ProvenanceItem,
    TextItem,
)
from docling_jobkit.convert.chunking import process_chunkable_results
from docling_jobkit.datamodel.chunking import ChunkingExportOptions
from docling_jobkit.datamodel.exportable_document import ExportableDocument
from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus

from docling_serve import app as app_module
from docling_serve.datamodel.chunking import (
    ChunkDocumentResponseWithProvenance,
    ChunkedDocItem,
    ChunkedDocumentResultItemWithProvenance,
    HierarchicalChunkerOptionsWithProvenance,
    HybridChunkerOptionsWithProvenance,
)
from docling_serve.response_preparation import resolve_chunk_provenance
from docling_serve.settings import AsyncEngine, docling_serve_settings


def _docling_document(name: str = "sample") -> DoclingDocument:
    return DoclingDocument(
        name=name,
        texts=[
            TextItem(
                self_ref="#/texts/0",
                label=DocItemLabel.TEXT,
                orig="hello",
                text="hello",
                prov=[
                    ProvenanceItem(
                        page_no=1,
                        bbox=BoundingBox(l=1, t=2, r=3, b=4),
                        charspan=(0, 5),
                    )
                ],
            )
        ],
    )


def _document_result(
    filename: str = "sample.pdf",
    document: DoclingDocument | None = None,
) -> DocumentResultItem:
    return DocumentResultItem(
        document=ExportDocumentResponse(
            filename=filename,
            json_content=document,
        ),
        status=ConversionStatus.SUCCESS,
    )


def _chunk_response(
    *,
    documents: list[DocumentResultItem] | None = None,
    filename: str = "sample.pdf",
    reference: str = "#/texts/0",
) -> ChunkDocumentResponse:
    return ChunkDocumentResponse(
        chunks=[
            ChunkedDocumentResultItem(
                filename=filename,
                chunk_index=0,
                text="hello",
                doc_items=[reference],
            )
        ],
        documents=(
            documents
            if documents is not None
            else [_document_result(document=_docling_document())]
        ),
        processing_time=0.25,
    )


def _task_result(
    include_converted_doc: bool,
    target: InBodyTarget | ZipTarget,
    reference: str = "#/texts/0",
) -> DoclingTaskResult:
    if isinstance(target, ZipTarget):
        return DoclingTaskResult(
            result=ZipArchiveResult(content=b"chunk archive"),
            processing_time=0.25,
            num_converted=1,
            num_succeeded=1,
            num_partially_succeeded=0,
            num_failed=0,
        )

    document = _docling_document() if include_converted_doc else None
    return DoclingTaskResult(
        result=ChunkedDocumentResult(
            chunks=_chunk_response(reference=reference).chunks,
            documents=[_document_result(document=document)],
        ),
        processing_time=0.25,
        num_converted=1,
        num_succeeded=1,
        num_partially_succeeded=0,
        num_failed=0,
    )


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.enqueued: list[dict[str, Any]] = []
        self.tasks: dict[str, Task] = {}
        self.doc_item_reference = "#/texts/0"

    async def enqueue(self, **kwargs: Any) -> Task:
        self.enqueued.append(kwargs)
        task = Task.model_construct(
            task_id=f"task-{len(self.enqueued)}",
            task_type=kwargs["task_type"],
            task_status=TaskStatus.SUCCESS,
            sources=kwargs["sources"],
            targets=kwargs["targets"],
            convert_options=kwargs["convert_options"],
            chunking_options=kwargs["chunking_options"],
            chunking_export_options=kwargs["chunking_export_options"],
            callbacks=kwargs["callbacks"],
            metadata={},
        )
        self.tasks[task.task_id] = task
        return task

    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
        del wait
        return self.tasks[task_id]

    async def get_queue_position(self, task_id: str) -> int:
        assert task_id in self.tasks
        return 0

    async def task_result(self, task_id: str) -> DoclingTaskResult:
        task = self.tasks[task_id]
        target = task.targets[0]
        if (
            task.chunking_export_options.include_converted_doc
            and isinstance(target, InBodyTarget)
            and task.convert_options.image_export_mode == ImageRefMode.REFERENCED
        ):
            raise RuntimeError("InBodyTarget cannot use REFERENCED image mode.")
        return _task_result(
            task.chunking_export_options.include_converted_doc,
            target,
            self.doc_item_reference,
        )

    async def task_outcome(self, task_id: str) -> DoclingTaskResult:
        return await self.task_result(task_id)

    async def on_result_fetched(self, task_id: str) -> None:
        del task_id


class _StaticChunkerManager:
    def chunk_document(
        self,
        document: DoclingDocument,
        filename: str,
        options: HierarchicalChunkerOptions,
    ) -> list[ChunkedDocumentResultItem]:
        del document, options
        return [
            ChunkedDocumentResultItem(
                filename=filename,
                chunk_index=0,
                text="hello",
                doc_items=[],
            )
        ]


@pytest.fixture(scope="module")
def fake_orchestrator() -> _FakeOrchestrator:
    return _FakeOrchestrator()


@pytest.fixture(scope="module")
def app(fake_orchestrator: _FakeOrchestrator) -> Iterator[FastAPI]:
    with (
        patch.object(
            app_module,
            "get_async_orchestrator",
            lambda: fake_orchestrator,
        ),
        patch.object(app_module, "setup_otel_instrumentation"),
    ):
        yield app_module.create_app()


@pytest.fixture(scope="module")
def auth_headers() -> dict[str, str]:
    if docling_serve_settings.api_key:
        return {"X-Api-Key": docling_serve_settings.api_key}
    return {}


def test_jobkit_rejects_inbody_converted_doc_with_referenced_images(
    tmp_path: Path,
) -> None:
    task = Task.model_construct(
        task_id="jobkit-referenced",
        task_type=TaskType.CHUNK,
        sources=[object()],
        targets=[InBodyTarget()],
        convert_options=ConvertDocumentsOptions(
            image_export_mode=ImageRefMode.REFERENCED
        ),
        chunking_options=HierarchicalChunkerOptions(),
        chunking_export_options=ChunkingExportOptions(include_converted_doc=True),
        callbacks=[],
    )
    exportable_document = ExportableDocument(
        file=PurePath("sample.pdf"),
        status=ConversionStatus.SUCCESS,
        document=_docling_document(),
    )

    with pytest.raises(
        RuntimeError,
        match="InBodyTarget cannot use REFERENCED image mode",
    ):
        process_chunkable_results(
            task,
            [exportable_document],
            tmp_path,
            chunker_manager=_StaticChunkerManager(),
        )


@pytest.mark.parametrize(
    "options_type",
    [
        HybridChunkerOptionsWithProvenance,
        HierarchicalChunkerOptionsWithProvenance,
    ],
)
def test_chunker_options_disable_provenance_by_default(options_type: type) -> None:
    assert options_type().include_provenance is False


def test_resolve_chunk_provenance_returns_resolved_items() -> None:
    result = resolve_chunk_provenance(
        _chunk_response(),
        keep_converted_doc=False,
    )

    assert result.chunks[0].doc_items == [
        ChunkedDocItem(
            self_ref="#/texts/0",
            label="text",
            prov=[
                ProvenanceItem(
                    page_no=1,
                    bbox=BoundingBox(l=1, t=2, r=3, b=4),
                    charspan=(0, 5),
                )
            ],
        )
    ]
    assert result.documents[0].document.json_content is None


def test_resolve_chunk_provenance_keeps_requested_document() -> None:
    result = resolve_chunk_provenance(
        _chunk_response(),
        keep_converted_doc=True,
    )

    assert result.documents[0].document.json_content == _docling_document()


def test_resolve_chunk_provenance_rejects_duplicate_filenames() -> None:
    response = _chunk_response(
        documents=[
            _document_result(document=_docling_document("first")),
            _document_result(document=_docling_document("second")),
        ]
    )

    with pytest.raises(ValueError, match=r"duplicate document filename.*sample\.pdf"):
        resolve_chunk_provenance(response, keep_converted_doc=False)


def test_resolve_chunk_provenance_rejects_duplicate_when_one_document_is_missing() -> (
    None
):
    response = _chunk_response(
        documents=[
            _document_result(),
            _document_result(document=_docling_document("second")),
        ]
    )

    with pytest.raises(ValueError, match=r"duplicate document filename.*sample\.pdf"):
        resolve_chunk_provenance(response, keep_converted_doc=False)


def test_resolve_chunk_provenance_requires_converted_document() -> None:
    response = _chunk_response(documents=[_document_result()])

    with pytest.raises(ValueError, match=r"converted document.*sample\.pdf"):
        resolve_chunk_provenance(response, keep_converted_doc=False)


def test_resolve_chunk_provenance_reports_unresolvable_reference() -> None:
    response = _chunk_response(reference="#/texts/9")

    with pytest.raises(ValueError, match=r"#/texts/9.*sample\.pdf"):
        resolve_chunk_provenance(response, keep_converted_doc=False)


def test_resolve_chunk_provenance_normalizes_missing_mapping_reference() -> None:
    response = _chunk_response(reference="#/pages/999")

    with pytest.raises(ValueError, match=r"#/pages/999.*sample\.pdf"):
        resolve_chunk_provenance(response, keep_converted_doc=False)


@pytest.mark.parametrize(
    ("self_refs", "reference"),
    [
        (("#/texts/1", "#/texts/0"), "#/texts/0"),
        (("#/texts/0", "#/texts/0"), "#/texts/1"),
    ],
)
def test_resolve_chunk_provenance_rejects_mismatched_self_ref(
    self_refs: tuple[str, str],
    reference: str,
) -> None:
    document = DoclingDocument(
        name="sample",
        texts=[
            TextItem(
                self_ref=f"#/texts/{index}",
                label=DocItemLabel.TEXT,
                orig=str(index),
                text=str(index),
            )
            for index in range(len(self_refs))
        ],
    )
    response = _chunk_response(
        documents=[_document_result(document=document)],
        reference=reference,
    )
    stored_document = response.documents[0].document.json_content
    assert stored_document is not None
    for item, self_ref in zip(stored_document.texts, self_refs, strict=True):
        item.self_ref = self_ref

    with pytest.raises(ValueError, match=rf"{reference}.*sample\.pdf"):
        resolve_chunk_provenance(response, keep_converted_doc=False)


def test_openapi_declares_legacy_and_provenance_chunk_shapes(app: FastAPI) -> None:
    schema = app.openapi()
    schemas = schema["components"]["schemas"]

    for chunker in ("hybrid", "hierarchical"):
        for encoding in ("file", "source"):
            response_schema = schema["paths"][f"/v1/chunk/{chunker}/{encoding}"][
                "post"
            ]["responses"]["200"]["content"]["application/json"]["schema"]
            assert {entry["$ref"] for entry in response_schema["anyOf"]} == {
                "#/components/schemas/ChunkDocumentResponse",
                "#/components/schemas/ChunkDocumentResponseWithProvenance",
            }

    legacy_doc_items = schemas["ChunkedDocumentResultItem"]["properties"]["doc_items"]
    assert legacy_doc_items["type"] == "array"
    assert legacy_doc_items["items"] == {"type": "string"}

    provenance_doc_items = schemas["ChunkedDocumentResultItemWithProvenance"][
        "properties"
    ]["doc_items"]
    assert provenance_doc_items["type"] == "array"
    assert provenance_doc_items["items"] == {
        "$ref": "#/components/schemas/ChunkedDocItem"
    }

    chunked_doc_item = schemas["ChunkedDocItem"]
    assert set(chunked_doc_item["required"]) == {"self_ref", "label"}
    assert chunked_doc_item["properties"]["prov"]["items"] == {
        "$ref": "#/components/schemas/ProvenanceItem"
    }

    provenance_item = schemas["ProvenanceItem"]
    assert set(provenance_item["required"]) == {"page_no", "bbox", "charspan"}
    assert provenance_item["properties"]["bbox"]["$ref"] == (
        "#/components/schemas/BoundingBox"
    )

    result_response_schema = schema["paths"]["/v1/result/{task_id}"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert {entry["$ref"] for entry in result_response_schema["anyOf"]}.issuperset(
        {
            "#/components/schemas/ChunkDocumentResponse",
            "#/components/schemas/ChunkDocumentResponseWithProvenance",
        }
    )


def test_provenance_response_models_only_override_changed_fields() -> None:
    assert ChunkedDocumentResultItemWithProvenance.__bases__ == (
        ChunkedDocumentResultItem,
    )
    assert set(ChunkedDocumentResultItemWithProvenance.__annotations__) == {"doc_items"}
    assert ChunkDocumentResponseWithProvenance.__bases__ == (ChunkDocumentResponse,)
    assert set(ChunkDocumentResponseWithProvenance.__annotations__) == {"chunks"}
    assert set(ChunkedDocumentResultItemWithProvenance.model_fields) == set(
        ChunkedDocumentResultItem.model_fields
    )
    assert set(ChunkDocumentResponseWithProvenance.model_fields) == set(
        ChunkDocumentResponse.model_fields
    )


def _assert_chunk_response(
    payload: dict[str, Any],
    *,
    include_provenance: bool,
    include_converted_doc: bool,
) -> None:
    if include_provenance:
        assert payload["chunks"][0]["doc_items"] == [
            {
                "self_ref": "#/texts/0",
                "label": "text",
                "prov": [
                    {
                        "page_no": 1,
                        "bbox": {
                            "l": 1.0,
                            "t": 2.0,
                            "r": 3.0,
                            "b": 4.0,
                            "coord_origin": "TOPLEFT",
                        },
                        "charspan": [0, 5],
                    }
                ],
            }
        ]
    else:
        assert payload["chunks"][0]["doc_items"] == ["#/texts/0"]

    converted_doc = payload["documents"][0]["content"]["json_content"]
    if include_converted_doc:
        assert converted_doc["schema_name"] == "DoclingDocument"
    else:
        assert converted_doc is None


async def _post_chunk_request(
    client: AsyncClient,
    encoding: str,
    auth_headers: dict[str, str],
    *,
    include_provenance: bool,
) -> Response:
    async_suffix = "/async" if encoding.endswith("_async") else ""
    if encoding.startswith("file"):
        data = {"chunking_include_provenance": "true"} if include_provenance else {}
        return await client.post(
            f"/v1/chunk/hierarchical/file{async_suffix}",
            files={"files": ("sample.pdf", b"test", "application/pdf")},
            data=data,
            headers=auth_headers,
        )

    payload: dict[str, Any] = {
        "sources": [
            {
                "kind": "file",
                "base64_string": base64.b64encode(b"test").decode(),
                "filename": "sample.pdf",
            }
        ]
    }
    if include_provenance:
        payload["chunking_options"] = {"include_provenance": True}
    return await client.post(
        f"/v1/chunk/hierarchical/source{async_suffix}",
        json=payload,
        headers=auth_headers,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "encoding",
    ["file", "source", "file_async", "source_async"],
)
async def test_chunk_rejects_provenance_with_ray_engine(
    app: FastAPI,
    fake_orchestrator: _FakeOrchestrator,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    encoding: str,
) -> None:
    monkeypatch.setattr(docling_serve_settings, "eng_kind", AsyncEngine.RAY)
    enqueued_before = len(fake_orchestrator.enqueued)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://app.io",
    ) as client:
        response = await _post_chunk_request(
            client,
            encoding,
            auth_headers,
            include_provenance=True,
        )

    assert response.status_code == 422, response.text
    assert response.json()["detail"] == (
        "include_provenance is not supported with the ray engine."
    )
    assert len(fake_orchestrator.enqueued) == enqueued_before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "encoding",
    ["file", "source", "file_async", "source_async"],
)
async def test_chunk_default_remains_available_with_ray_engine(
    app: FastAPI,
    fake_orchestrator: _FakeOrchestrator,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    encoding: str,
) -> None:
    monkeypatch.setattr(docling_serve_settings, "eng_kind", AsyncEngine.RAY)
    enqueued_before = len(fake_orchestrator.enqueued)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://app.io",
    ) as client:
        response = await _post_chunk_request(
            client,
            encoding,
            auth_headers,
            include_provenance=False,
        )

    assert response.status_code == 200, response.text
    assert len(fake_orchestrator.enqueued) == enqueued_before + 1
    assert "chunk_provenance_keep_converted_doc" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["direct", "stored_result"])
@pytest.mark.parametrize("reference", ["#/texts/9", "not-a-reference"])
async def test_chunk_provenance_reference_errors_are_public_422_responses(
    app: FastAPI,
    fake_orchestrator: _FakeOrchestrator,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    reference: str,
) -> None:
    monkeypatch.setattr(fake_orchestrator, "doc_item_reference", reference)
    monkeypatch.setattr(docling_serve_settings, "debug_error_details", False)

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://app.io",
    ) as client:
        response = await _post_chunk_request(
            client,
            "source_async" if boundary == "stored_result" else "source",
            auth_headers,
            include_provenance=True,
        )
        if boundary == "stored_result":
            assert response.status_code == 200, response.text
            response = await client.get(
                f"/v1/result/{response.json()['task_id']}",
                headers=auth_headers,
            )

    assert response.status_code == 422, response.text
    assert response.json() == {"detail": "Cannot resolve chunk provenance."}
    assert reference not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("chunker", ["hybrid", "hierarchical"])
@pytest.mark.parametrize(
    ("include_provenance", "include_converted_doc"),
    [(False, False), (False, True), (True, False), (True, True)],
)
async def test_chunk_file_options_and_response_shape(
    app: FastAPI,
    fake_orchestrator: _FakeOrchestrator,
    auth_headers: dict[str, str],
    chunker: str,
    include_provenance: bool,
    include_converted_doc: bool,
) -> None:
    data: dict[str, str] = {}
    if include_provenance:
        data["chunking_include_provenance"] = "true"
    if include_converted_doc:
        data["include_converted_doc"] = "true"

    enqueued_before = len(fake_orchestrator.enqueued)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            f"/v1/chunk/{chunker}/file",
            files={"files": ("sample.pdf", b"test", "application/pdf")},
            data=data,
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    assert len(fake_orchestrator.enqueued) == enqueued_before + 1
    request = fake_orchestrator.enqueued[-1]
    assert request["chunking_options"].include_provenance is include_provenance
    assert request["chunking_export_options"].include_converted_doc is (
        include_provenance or include_converted_doc
    )
    _assert_chunk_response(
        response.json(),
        include_provenance=include_provenance,
        include_converted_doc=include_converted_doc,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("chunker", ["hybrid", "hierarchical"])
@pytest.mark.parametrize(
    ("include_provenance", "include_converted_doc"),
    [(False, False), (False, True), (True, False), (True, True)],
)
async def test_chunk_source_options_and_response_shape(
    app: FastAPI,
    fake_orchestrator: _FakeOrchestrator,
    auth_headers: dict[str, str],
    chunker: str,
    include_provenance: bool,
    include_converted_doc: bool,
) -> None:
    payload: dict[str, Any] = {
        "sources": [
            {
                "kind": "file",
                "base64_string": base64.b64encode(b"test").decode(),
                "filename": "sample.pdf",
            }
        ]
    }
    if include_provenance:
        payload["chunking_options"] = {"include_provenance": True}
    if include_converted_doc:
        payload["include_converted_doc"] = True

    enqueued_before = len(fake_orchestrator.enqueued)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            f"/v1/chunk/{chunker}/source",
            json=payload,
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    assert len(fake_orchestrator.enqueued) == enqueued_before + 1
    request = fake_orchestrator.enqueued[-1]
    assert request["chunking_options"].include_provenance is include_provenance
    assert request["chunking_export_options"].include_converted_doc is (
        include_provenance or include_converted_doc
    )
    _assert_chunk_response(
        response.json(),
        include_provenance=include_provenance,
        include_converted_doc=include_converted_doc,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "encoding",
    ["file", "source", "file_async", "source_async"],
)
async def test_chunk_rejects_provenance_with_zip_target(
    app: FastAPI,
    fake_orchestrator: _FakeOrchestrator,
    auth_headers: dict[str, str],
    encoding: str,
) -> None:
    enqueued_before = len(fake_orchestrator.enqueued)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://app.io",
    ) as client:
        if encoding.startswith("file"):
            response = await client.post(
                f"/v1/chunk/hierarchical/file{'/async' if encoding.endswith('_async') else ''}",
                files={"files": ("sample.pdf", b"test", "application/pdf")},
                data={
                    "chunking_include_provenance": "true",
                    "target_type": "zip",
                },
                headers=auth_headers,
            )
        else:
            response = await client.post(
                f"/v1/chunk/hierarchical/source{'/async' if encoding.endswith('_async') else ''}",
                json={
                    "sources": [
                        {
                            "kind": "file",
                            "base64_string": base64.b64encode(b"test").decode(),
                            "filename": "sample.pdf",
                        }
                    ],
                    "target": {"kind": "zip"},
                    "chunking_options": {"include_provenance": True},
                },
                headers=auth_headers,
            )

    assert response.status_code == 422, response.text
    assert "include_provenance" in response.json()["detail"]
    assert len(fake_orchestrator.enqueued) == enqueued_before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "encoding",
    ["file", "source", "file_async", "source_async"],
)
async def test_chunk_rejects_provenance_with_referenced_images(
    app: FastAPI,
    fake_orchestrator: _FakeOrchestrator,
    auth_headers: dict[str, str],
    encoding: str,
) -> None:
    enqueued_before = len(fake_orchestrator.enqueued)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://app.io",
    ) as client:
        if encoding.startswith("file"):
            response = await client.post(
                f"/v1/chunk/hierarchical/file{'/async' if encoding.endswith('_async') else ''}",
                files={"files": ("sample.pdf", b"test", "application/pdf")},
                data={
                    "chunking_include_provenance": "true",
                    "convert_image_export_mode": "referenced",
                },
                headers=auth_headers,
            )
        else:
            response = await client.post(
                f"/v1/chunk/hierarchical/source{'/async' if encoding.endswith('_async') else ''}",
                json={
                    "sources": [
                        {
                            "kind": "file",
                            "base64_string": base64.b64encode(b"test").decode(),
                            "filename": "sample.pdf",
                        }
                    ],
                    "convert_options": {"image_export_mode": "referenced"},
                    "chunking_options": {"include_provenance": True},
                },
                headers=auth_headers,
            )

    assert response.status_code == 422, response.text
    assert "include_provenance" in response.json()["detail"]
    assert len(fake_orchestrator.enqueued) == enqueued_before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("encoding", "target"),
    [("file", "inbody"), ("source", "inbody"), ("file", "zip"), ("source", "zip")],
)
async def test_chunk_default_accepts_referenced_images_and_zip_target(
    app: FastAPI,
    fake_orchestrator: _FakeOrchestrator,
    auth_headers: dict[str, str],
    encoding: str,
    target: str,
) -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://app.io",
    ) as client:
        if encoding == "file":
            response = await client.post(
                "/v1/chunk/hierarchical/file",
                files={"files": ("sample.pdf", b"test", "application/pdf")},
                data={
                    "convert_image_export_mode": "referenced",
                    "target_type": target,
                },
                headers=auth_headers,
            )
        else:
            response = await client.post(
                "/v1/chunk/hierarchical/source",
                json={
                    "sources": [
                        {
                            "kind": "file",
                            "base64_string": base64.b64encode(b"test").decode(),
                            "filename": "sample.pdf",
                        }
                    ],
                    "target": {"kind": target},
                    "convert_options": {"image_export_mode": "referenced"},
                    "chunking_options": {},
                },
                headers=auth_headers,
            )

    assert response.status_code == 200, response.text
    if target == "zip":
        assert response.headers["content-type"] == "application/zip"
        assert response.content == b"chunk archive"
    else:
        _assert_chunk_response(
            response.json(),
            include_provenance=False,
            include_converted_doc=False,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("encoding", "include_converted_doc", "callbacks"),
    [
        ("file", False, []),
        ("source", False, []),
        ("source", False, [{"url": "https://example.com/callback"}]),
        ("source", True, []),
    ],
)
async def test_stored_chunk_result_preserves_provenance_response_contract(
    app: FastAPI,
    fake_orchestrator: _FakeOrchestrator,
    auth_headers: dict[str, str],
    encoding: str,
    include_converted_doc: bool,
    callbacks: list[dict[str, str]],
) -> None:
    payload: dict[str, Any] = {
        "sources": [
            {
                "kind": "file",
                "base64_string": base64.b64encode(b"test").decode(),
                "filename": "sample.pdf",
            }
        ],
        "chunking_options": {"include_provenance": True},
        "callbacks": callbacks,
    }
    if include_converted_doc:
        payload["include_converted_doc"] = True

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://app.io",
    ) as client:
        if encoding == "file":
            direct_response = await client.post(
                "/v1/chunk/hierarchical/file",
                files={"files": ("sample.pdf", b"test", "application/pdf")},
                data={"chunking_include_provenance": "true"},
                headers=auth_headers,
            )
        else:
            direct_response = await client.post(
                "/v1/chunk/hierarchical/source",
                json=payload,
                headers=auth_headers,
            )
        assert direct_response.status_code == 200, direct_response.text
        assert "chunk_provenance_keep_converted_doc" not in direct_response.text
        task_id = next(reversed(fake_orchestrator.tasks))
        task = fake_orchestrator.tasks[task_id]
        assert task.chunking_export_options.include_converted_doc is True
        assert bool(task.callbacks) is bool(callbacks)
        stored_response = await client.get(
            f"/v1/result/{task_id}",
            headers=auth_headers,
        )

    assert stored_response.status_code == 200, stored_response.text
    assert "chunk_provenance_keep_converted_doc" not in stored_response.text
    _assert_chunk_response(
        stored_response.json(),
        include_provenance=True,
        include_converted_doc=include_converted_doc,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("encoding", "include_converted_doc", "callbacks"),
    [
        ("file", False, []),
        ("source", False, [{"url": "https://example.com/callback"}]),
        ("source", True, []),
    ],
)
async def test_async_chunk_result_preserves_provenance_response_contract(
    app: FastAPI,
    fake_orchestrator: _FakeOrchestrator,
    auth_headers: dict[str, str],
    encoding: str,
    include_converted_doc: bool,
    callbacks: list[dict[str, str]],
) -> None:
    payload: dict[str, Any] = {
        "sources": [
            {
                "kind": "file",
                "base64_string": base64.b64encode(b"test").decode(),
                "filename": "sample.pdf",
            }
        ],
        "chunking_options": {"include_provenance": True},
        "callbacks": callbacks,
    }
    if include_converted_doc:
        payload["include_converted_doc"] = True

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://app.io",
    ) as client:
        if encoding == "file":
            data = {"chunking_include_provenance": "true"}
            if include_converted_doc:
                data["include_converted_doc"] = "true"
            task_response = await client.post(
                "/v1/chunk/hierarchical/file/async",
                files={"files": ("sample.pdf", b"test", "application/pdf")},
                data=data,
                headers=auth_headers,
            )
        else:
            task_response = await client.post(
                "/v1/chunk/hierarchical/source/async",
                json=payload,
                headers=auth_headers,
            )
        assert task_response.status_code == 200, task_response.text
        assert "chunk_provenance_keep_converted_doc" not in task_response.text
        task_id = task_response.json()["task_id"]
        task = fake_orchestrator.tasks[task_id]
        assert task.chunking_export_options.include_converted_doc is True
        assert bool(task.callbacks) is bool(callbacks)
        stored_response = await client.get(
            f"/v1/result/{task_id}",
            headers=auth_headers,
        )

    assert stored_response.status_code == 200, stored_response.text
    assert "chunk_provenance_keep_converted_doc" not in stored_response.text
    _assert_chunk_response(
        stored_response.json(),
        include_provenance=True,
        include_converted_doc=include_converted_doc,
    )

"""The chunk endpoints must enforce ``max_sources_per_request`` like convert does."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from docling_jobkit.datamodel.task import Task

MAX_SOURCES = 2


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []

    async def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)
        return Task.model_construct(
            task_id="task-chunk",
            task_type=kwargs["task_type"],
            sources=kwargs["sources"],
        )

    async def get_queue_position(self, task_id: str):
        del task_id
        return 0


@pytest.fixture
def fake_orchestrator(monkeypatch):
    from docling_serve import app as app_module

    orchestrator = _FakeOrchestrator()
    monkeypatch.setattr(
        app_module.docling_serve_settings, "max_sources_per_request", MAX_SOURCES
    )
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: orchestrator)
    return orchestrator


@pytest.fixture
def client(fake_orchestrator):
    from docling_serve import app as app_module

    del fake_orchestrator
    with patch.object(app_module, "setup_otel_instrumentation"):
        app = app_module.create_app()
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://app.io")


def _source_payload(num_sources: int) -> dict:
    return {
        "sources": [
            {"kind": "http", "url": f"https://example.com/{i}.pdf"}
            for i in range(num_sources)
        ],
        "chunking_options": {},
    }


def _files(num_files: int) -> list:
    return [
        ("files", (f"{i}.md", b"# Title\n\nSome text.\n", "text/markdown"))
        for i in range(num_files)
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("chunker", ["hybrid", "hierarchical"])
@pytest.mark.parametrize("suffix", ["", "/async"])
async def test_chunk_source_rejects_too_many_sources(
    client, fake_orchestrator, chunker, suffix
):
    async with client:
        response = await client.post(
            f"/v1/chunk/{chunker}/source{suffix}",
            json=_source_payload(MAX_SOURCES + 1),
        )

    assert response.status_code == 422
    assert "Too many sources" in response.json()["detail"]
    assert fake_orchestrator.enqueued == []


@pytest.mark.asyncio
@pytest.mark.parametrize("chunker", ["hybrid", "hierarchical"])
@pytest.mark.parametrize("suffix", ["", "/async"])
async def test_chunk_file_rejects_too_many_files(
    client, fake_orchestrator, chunker, suffix
):
    async with client:
        response = await client.post(
            f"/v1/chunk/{chunker}/file{suffix}",
            files=_files(MAX_SOURCES + 1),
        )

    assert response.status_code == 422
    assert "Too many files" in response.json()["detail"]
    assert fake_orchestrator.enqueued == []


@pytest.mark.asyncio
@pytest.mark.parametrize("chunker", ["hybrid", "hierarchical"])
async def test_chunk_source_async_accepts_sources_within_limit(
    client, fake_orchestrator, chunker
):
    async with client:
        response = await client.post(
            f"/v1/chunk/{chunker}/source/async",
            json=_source_payload(MAX_SOURCES),
        )

    assert response.status_code == 200
    assert len(fake_orchestrator.enqueued) == 1
    assert len(fake_orchestrator.enqueued[0]["sources"]) == MAX_SOURCES


@pytest.mark.asyncio
@pytest.mark.parametrize("chunker", ["hybrid", "hierarchical"])
async def test_chunk_file_async_accepts_files_within_limit(
    client, fake_orchestrator, chunker
):
    async with client:
        response = await client.post(
            f"/v1/chunk/{chunker}/file/async",
            files=_files(MAX_SOURCES),
        )

    assert response.status_code == 200
    assert len(fake_orchestrator.enqueued) == 1
    assert len(fake_orchestrator.enqueued[0]["sources"]) == MAX_SOURCES

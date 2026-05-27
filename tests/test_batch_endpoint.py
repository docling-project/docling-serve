from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from docling.datamodel.base_models import ConversionStatus
from docling.datamodel.service.responses import (
    ArtifactRef,
    DoclingTaskResult,
    DocumentArtifactItem,
    PresignedArtifactResult,
)
from docling.datamodel.service.targets import S3Target
from docling.datamodel.service.tasks import TaskType
from docling_jobkit.datamodel.task import Task


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []

    async def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)
        return Task(
            task_id="task-batch",
            task_type=kwargs["task_type"],
            sources=kwargs["sources"],
            target=kwargs["target"],
            convert_options=kwargs["convert_options"],
            callbacks=kwargs["callbacks"],
            metadata=kwargs["metadata"],
        )

    async def get_queue_position(self, task_id: str):
        del task_id
        return 0

    async def task_result(self, task_id: str):
        del task_id
        return DoclingTaskResult(
            result=PresignedArtifactResult(
                documents=[
                    DocumentArtifactItem(
                        source_index=0,
                        source_uri="https://example.com/a.pdf",
                        filename="a.pdf",
                        status=ConversionStatus.SUCCESS,
                        artifacts=[
                            ArtifactRef(
                                artifact_type="markdown",
                                mime_type="text/markdown",
                                uri="s3://converted/000000-a/a.md",
                            )
                        ],
                    )
                ]
            ),
            processing_time=1.0,
            num_converted=1,
            num_succeeded=1,
            num_partially_succeeded=0,
            num_failed=0,
        )

    async def on_result_fetched(self, task_id: str):
        del task_id


@pytest.fixture
def fake_orchestrator(monkeypatch):
    from docling_serve import app as app_module

    orchestrator = _FakeOrchestrator()
    monkeypatch.setattr(
        app_module.docling_serve_settings, "artifact_storage_enabled", True
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings, "max_sources_per_request", 10
    )
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: orchestrator)
    return orchestrator


@pytest.fixture
def app(fake_orchestrator):
    from docling_serve import app as app_module

    del fake_orchestrator
    with patch.object(app_module, "setup_otel_instrumentation"):
        return app_module.create_app()


@pytest.mark.asyncio
async def test_batch_endpoint_rejects_s3_source_with_presigned_target(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [
                    {
                        "kind": "s3",
                        "endpoint": "s3.example.com",
                        "access_key": "key",
                        "secret_key": "secret",
                        "bucket": "documents",
                    }
                ],
                "target": {"kind": "presigned_url"},
            },
        )

    assert response.status_code == 422
    assert "S3 sources require an S3 target" in response.text


@pytest.mark.asyncio
async def test_batch_endpoint_accepts_s3_source_with_s3_target(app, fake_orchestrator):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [
                    {
                        "kind": "s3",
                        "endpoint": "s3.example.com",
                        "access_key": "key",
                        "secret_key": "secret",
                        "bucket": "documents",
                    }
                ],
                "target": {
                    "kind": "s3",
                    "endpoint": "s3.example.com",
                    "access_key": "key",
                    "secret_key": "secret",
                    "bucket": "converted",
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["task_type"] == TaskType.CONVERT
    assert len(fake_orchestrator.enqueued[0]["sources"]) == 1
    assert isinstance(fake_orchestrator.enqueued[0]["target"], S3Target)


@pytest.mark.asyncio
async def test_batch_endpoint_accepts_http_source_with_presigned_target(
    app, fake_orchestrator
):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [
                    {"kind": "http", "url": "https://example.com/a.pdf"},
                    {"kind": "http", "url": "https://example.com/b.pdf"},
                ],
                "target": {"kind": "presigned_url"},
            },
        )

    assert response.status_code == 200
    assert len(fake_orchestrator.enqueued[0]["sources"]) == 2


@pytest.mark.asyncio
async def test_batch_endpoint_rejects_zip_target(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [{"kind": "http", "url": "https://example.com/a.pdf"}],
                "target": {"kind": "zip"},
            },
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_task_result_returns_presigned_artifact_response(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.get("/v1/result/task-batch")

    assert response.status_code == 200
    payload = response.json()
    assert payload["num_partially_succeeded"] == 0
    assert payload["documents"][0]["source_index"] == 0

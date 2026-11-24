"""Operators can disable callbacks and bound how many one request may register."""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from docling_jobkit.datamodel.task import Task

from docling_serve.policy import build_service_policy
from docling_serve.settings import DoclingServeSettings

MAX_CALLBACKS = 2


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []

    async def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)
        return Task.model_construct(
            task_id="task-callbacks",
            task_type=kwargs["task_type"],
            sources=kwargs["sources"],
        )

    async def get_queue_position(self, task_id: str):
        del task_id
        return 0


def _make_client(monkeypatch, *, enable_callbacks: bool):
    from docling_serve import app as app_module

    orchestrator = _FakeOrchestrator()
    monkeypatch.setattr(
        app_module.docling_serve_settings, "enable_callbacks", enable_callbacks
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings, "max_callbacks_per_request", MAX_CALLBACKS
    )
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: orchestrator)
    with patch.object(app_module, "setup_otel_instrumentation"):
        app = app_module.create_app()
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://app.io")
    return client, orchestrator


def _callback_urls(n: int) -> list[str]:
    return [f"http://hooks.internal.svc/done/{i}" for i in range(n)]


def _source_payload(num_callbacks: int) -> dict:
    return {
        "sources": [{"kind": "http", "url": "https://example.com/doc.pdf"}],
        "callbacks": [{"url": url} for url in _callback_urls(num_callbacks)],
    }


def _file_form(num_callbacks: int) -> dict:
    return {
        "files": [("files", ("doc.md", b"# Title\n\nSome text.\n", "text/markdown"))],
        "data": {"callbacks": _callback_urls(num_callbacks)},
    }


def test_policy_defaults_keep_callbacks_enabled():
    policy = build_service_policy(DoclingServeSettings())
    assert policy.callbacks_enabled is True
    assert policy.max_callbacks_per_request == 5


def test_policy_follows_enable_callbacks_setting():
    policy = build_service_policy(DoclingServeSettings(enable_callbacks=False))
    assert policy.callbacks_enabled is False


@pytest.mark.asyncio
async def test_source_rejects_callbacks_when_disabled(monkeypatch):
    client, orchestrator = _make_client(monkeypatch, enable_callbacks=False)
    async with client:
        response = await client.post(
            "/v1/convert/source/async", json=_source_payload(1)
        )

    assert response.status_code == 422
    assert "Callbacks are disabled" in response.json()["detail"]
    assert orchestrator.enqueued == []


@pytest.mark.asyncio
async def test_file_rejects_callbacks_when_disabled(monkeypatch):
    client, orchestrator = _make_client(monkeypatch, enable_callbacks=False)
    async with client:
        response = await client.post("/v1/convert/file/async", **_file_form(1))

    assert response.status_code == 422
    assert "Callbacks are disabled" in response.json()["detail"]
    assert orchestrator.enqueued == []


@pytest.mark.asyncio
async def test_requests_without_callbacks_pass_when_disabled(monkeypatch):
    client, orchestrator = _make_client(monkeypatch, enable_callbacks=False)
    async with client:
        response = await client.post(
            "/v1/convert/source/async", json=_source_payload(0)
        )

    assert response.status_code == 200
    assert len(orchestrator.enqueued) == 1


@pytest.mark.asyncio
async def test_source_rejects_too_many_callbacks(monkeypatch):
    client, orchestrator = _make_client(monkeypatch, enable_callbacks=True)
    async with client:
        response = await client.post(
            "/v1/convert/source/async", json=_source_payload(MAX_CALLBACKS + 1)
        )

    assert response.status_code == 422
    assert "Too many callbacks" in response.json()["detail"]
    assert orchestrator.enqueued == []


@pytest.mark.asyncio
async def test_file_rejects_too_many_callbacks(monkeypatch):
    client, orchestrator = _make_client(monkeypatch, enable_callbacks=True)
    async with client:
        response = await client.post(
            "/v1/convert/file/async", **_file_form(MAX_CALLBACKS + 1)
        )

    assert response.status_code == 422
    assert "Too many callbacks" in response.json()["detail"]
    assert orchestrator.enqueued == []


@pytest.mark.asyncio
async def test_callbacks_within_limit_reach_the_orchestrator(monkeypatch):
    client, orchestrator = _make_client(monkeypatch, enable_callbacks=True)
    async with client:
        source_response = await client.post(
            "/v1/convert/source/async", json=_source_payload(MAX_CALLBACKS)
        )
        file_response = await client.post(
            "/v1/convert/file/async", **_file_form(MAX_CALLBACKS)
        )

    assert source_response.status_code == 200
    assert file_response.status_code == 200
    assert [len(e["callbacks"]) for e in orchestrator.enqueued] == [
        MAX_CALLBACKS,
        MAX_CALLBACKS,
    ]

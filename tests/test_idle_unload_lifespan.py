# SPDX-License-Identifier: MIT

import asyncio
import threading
from io import BytesIO
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from docling.datamodel.base_models import DocumentStream
from docling.datamodel.service.options import ConvertDocumentsOptions
from docling.datamodel.service.targets import InBodyTarget
from docling_jobkit.convert.manager import (
    DoclingConverterManager,
    DoclingConverterManagerConfig,
)
from docling_jobkit.orchestrators.local.orchestrator import (
    LocalOrchestrator,
    LocalOrchestratorConfig,
)

from docling_serve import app as app_module, idle_unload as idle
from docling_serve.settings import AsyncEngine


@pytest.fixture
def orchestrator(monkeypatch, tmp_path):
    orch = LocalOrchestrator(
        LocalOrchestratorConfig(
            num_workers=1, shared_models=True, scratch_dir=tmp_path
        ),
        DoclingConverterManager(DoclingConverterManagerConfig()),
    )
    orch.warm_up_caches = AsyncMock()
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: orch)
    monkeypatch.setattr(app_module, "get_scratch", lambda: tmp_path)
    monkeypatch.setattr(app_module.docling_serve_settings, "load_models_at_boot", True)
    monkeypatch.setattr(app_module.docling_serve_settings, "idle_unload_seconds", 0.01)
    monkeypatch.setattr(idle, "release_memory", lambda: True)
    return orch


async def test_disabled_keeps_original_queue(monkeypatch, orchestrator):
    monkeypatch.setattr(app_module.docling_serve_settings, "idle_unload_seconds", 0)
    queue = orchestrator.task_queue
    async with app_module.lifespan(FastAPI()):
        assert orchestrator.task_queue is queue
    orchestrator.warm_up_caches.assert_awaited_once()


async def test_unloads_after_warmup_polling_and_next_conversion(
    monkeypatch, orchestrator
):
    cleaned = asyncio.Event()
    original_clear = orchestrator.clear_converters

    async def clear():
        orchestrator.warm_up_caches.assert_awaited_once()
        await original_clear()
        cleaned.set()

    monkeypatch.setattr(orchestrator, "clear_converters", clear)
    app = app_module.create_app()
    async with app_module.lifespan(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            started_at = orchestrator.task_queue.owner.last_activity
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/ready")).status_code == 200
            assert orchestrator.task_queue.owner.last_activity == started_at
            await asyncio.wait_for(cleaned.wait(), 2)
            task = await orchestrator.enqueue(
                targets=[InBodyTarget()],
                convert_options=ConvertDocumentsOptions(),
                sources=[
                    DocumentStream(
                        name="sample.md", stream=BytesIO(b"# Hello\n\nReloaded.")
                    )
                ],
            )
            await asyncio.wait_for(orchestrator.task_queue.join(), 10)
            assert task.task_status.value == "success"
            assert await orchestrator.task_result(task.task_id) is not None


@pytest.mark.parametrize("exceptional", [False, True])
async def test_shutdown_stops_idle_before_cancelling_real_executor(
    monkeypatch, orchestrator, exceptional
):
    entered, release = threading.Event(), threading.Event()

    def blocked_conversion(*args, **kwargs):
        entered.set()
        release.wait(5)
        return iter(())

    monkeypatch.setattr(orchestrator.cm, "convert_documents", blocked_conversion)
    cleared = AsyncMock()
    monkeypatch.setattr(orchestrator, "clear_converters", cleared)
    context = app_module.lifespan(FastAPI())
    await context.__aenter__()
    try:
        await orchestrator.enqueue(
            targets=[InBodyTarget()],
            convert_options=ConvertDocumentsOptions(),
            sources=[DocumentStream(name="sample.md", stream=BytesIO(b"text"))],
        )
        assert await asyncio.to_thread(entered.wait, 3)
        queue = orchestrator.task_queue
        assert isinstance(queue, idle._ActivityQueue)
        if exceptional:
            assert not await context.__aexit__(RuntimeError, RuntimeError("body"), None)
        else:
            await context.__aexit__(None, None, None)
        assert queue.owner.stopped
        assert not await queue.owner.unload_if_idle()
        cleared.assert_not_awaited()
    finally:
        release.set()
        if not isinstance(orchestrator.task_queue, idle._ActivityQueue):
            await context.__aexit__(None, None, None)


async def test_mutated_nonlocal_setting_rejected(monkeypatch, orchestrator):
    monkeypatch.setattr(app_module.docling_serve_settings, "eng_kind", AsyncEngine.RQ)
    with pytest.raises(ValueError, match="local"):
        async with app_module.lifespan(FastAPI()):
            pass

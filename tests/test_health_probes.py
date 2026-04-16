import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from docling_serve.app import _models_ready, create_app
from docling_serve.datamodel.responses import (
    HealthCheckResponse,
    ReadinessResponse,
)
from docling_serve.settings import AsyncEngine, docling_serve_settings


@pytest.fixture(scope="session")
def event_loop():
    return asyncio.get_event_loop()


@pytest_asyncio.fixture(scope="session")
async def app():
    original_load_models_at_boot = docling_serve_settings.load_models_at_boot
    docling_serve_settings.load_models_at_boot = False
    try:
        app = create_app()
        async with LifespanManager(app) as manager:
            yield manager.app
    finally:
        docling_serve_settings.load_models_at_boot = original_load_models_at_boot


@pytest_asyncio.fixture(scope="session")
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        yield client


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_ready(client: AsyncClient):
    response = await client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_readyz_alias(client: AsyncClient):
    response = await client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_readyz_for_ray_runs_deep_connection_check(client: AsyncClient):
    original_engine = docling_serve_settings.eng_kind
    docling_serve_settings.eng_kind = AsyncEngine.RAY
    try:
        orchestrator = MagicMock()
        orchestrator.check_connection = AsyncMock(
            side_effect=RuntimeError("Ray dispatcher unavailable")
        )

        with patch(
            "docling_serve.app.get_async_orchestrator", return_value=orchestrator
        ):
            response = await client.get("/readyz")
    finally:
        docling_serve_settings.eng_kind = original_engine

    assert response.status_code == 503
    assert response.json()["detail"] == "Ray dispatcher unavailable"
    orchestrator.check_connection.assert_awaited_once()


@pytest.mark.asyncio
async def test_livez_alias(client: AsyncClient):
    response = await client.get("/livez")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_livez_for_ray_does_not_check_orchestrator_health(
    client: AsyncClient,
):
    original_engine = docling_serve_settings.eng_kind
    docling_serve_settings.eng_kind = AsyncEngine.RAY
    try:
        with patch(
            "docling_serve.app.get_async_orchestrator",
            side_effect=AssertionError("/livez should not touch the Ray orchestrator"),
        ):
            response = await client.get("/livez")
    finally:
        docling_serve_settings.eng_kind = original_engine

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_ready_returns_503_when_models_not_loaded(client: AsyncClient):
    _models_ready.clear()
    try:
        response = await client.get("/ready")
        assert response.status_code == 503
        assert "Models not yet loaded" in response.json()["detail"]
    finally:
        _models_ready.set()


def test_health_check_response_model():
    resp = HealthCheckResponse()
    assert resp.status == "ok"


def test_readiness_response_model():
    resp = ReadinessResponse()
    assert resp.status == "ok"

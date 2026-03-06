import asyncio

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from docling_serve.app import _models_ready, create_app
from docling_serve.datamodel.responses import (
    HealthCheckResponse,
    ReadinessResponse,
)


@pytest.fixture(scope="session")
def event_loop():
    return asyncio.get_event_loop()


@pytest_asyncio.fixture(scope="session")
async def app():
    app = create_app()
    async with LifespanManager(app) as manager:
        yield manager.app


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
async def test_livez_alias(client: AsyncClient):
    response = await client.get("/livez")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


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

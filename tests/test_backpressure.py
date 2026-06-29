import asyncio
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from docling_serve.app import create_app


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
async def test_capacity_endpoint_returns_data(client: AsyncClient):
    response = await client.get("/v1/capacity")
    assert response.status_code == 200
    data = response.json()
    assert "queue_depth" in data
    assert "active_jobs" in data
    assert "active_workers" in data


@pytest.mark.asyncio
async def test_capacity_endpoint_fields_are_ints(client: AsyncClient):
    response = await client.get("/v1/capacity")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["queue_depth"], int)
    assert isinstance(data["active_jobs"], int)
    assert isinstance(data["active_workers"], int)


@pytest.mark.asyncio
async def test_queue_limit_exceeded_returns_429(client: AsyncClient):
    from docling_jobkit.orchestrators.ray.orchestrator import (
        QueueLimitExceededError,
    )

    async def _raise(*args, **kwargs):
        raise QueueLimitExceededError("Queue full (10/10)")

    with patch("docling_serve.app.get_async_orchestrator") as mock_get_orch:
        mock_orch = AsyncMock()
        mock_orch.enqueue = _raise
        mock_orch.get_capacity = AsyncMock(return_value=None)
        mock_get_orch.return_value = mock_orch

        response = await client.post(
            "/v1/convert/source/async",
            json={
                "sources": [{"url": "https://example.com/test.pdf"}],
                "options": {},
            },
        )

    assert response.status_code == 429
    data = response.json()
    assert "Queue full" in data["detail"]
    assert "Retry-After" in response.headers


@pytest.mark.asyncio
async def test_redis_backpressure_returns_503(client: AsyncClient):
    from docling_jobkit.orchestrators.base_orchestrator import (
        RedisBackpressureError,
    )

    async def _raise(*args, **kwargs):
        raise RedisBackpressureError("saturated")

    with patch("docling_serve.app.get_async_orchestrator") as mock_get_orch:
        mock_orch = AsyncMock()
        mock_orch.enqueue = _raise
        mock_get_orch.return_value = mock_orch

        response = await client.post(
            "/v1/convert/source/async",
            json={
                "sources": [{"url": "https://example.com/test.pdf"}],
                "options": {},
            },
        )

    assert response.status_code == 503
    assert "Retry-After" in response.headers

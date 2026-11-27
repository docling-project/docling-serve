"""The management endpoints require the API key like every other data route.

With ``api_key`` set and ``enable_management_endpoints`` on, ``/v1/memory/stats``
and ``/v1/memory/counts`` must not expose server internals to callers without
the ``X-Api-Key`` header.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from docling_serve import app as app_module
from docling_serve.settings import docling_serve_settings

MANAGEMENT_ROUTES = ("/v1/memory/stats", "/v1/memory/counts")
API_KEY = "secret123"


@pytest.fixture
def make_client(monkeypatch):
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: MagicMock())
    monkeypatch.setattr(docling_serve_settings, "enable_management_endpoints", True)

    def _make(api_key: str) -> TestClient:
        monkeypatch.setattr(docling_serve_settings, "api_key", api_key)
        with patch.object(app_module, "setup_otel_instrumentation"):
            return TestClient(app_module.create_app())

    return _make


@pytest.mark.parametrize("path", MANAGEMENT_ROUTES)
def test_management_route_rejects_missing_api_key(make_client, path: str) -> None:
    client = make_client(API_KEY)

    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", MANAGEMENT_ROUTES)
def test_management_route_rejects_wrong_api_key(make_client, path: str) -> None:
    client = make_client(API_KEY)

    assert client.get(path, headers={"X-Api-Key": "wrong"}).status_code == 401


def test_memory_counts_accepts_valid_api_key(make_client) -> None:
    client = make_client(API_KEY)

    response = client.get("/v1/memory/counts", headers={"X-Api-Key": API_KEY})

    assert response.status_code == 200


def test_memory_counts_open_without_configured_api_key(make_client) -> None:
    client = make_client("")

    assert client.get("/v1/memory/counts").status_code == 200

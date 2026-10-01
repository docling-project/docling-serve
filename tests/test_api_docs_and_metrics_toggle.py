"""Deployments can turn off the key-less API reference and metrics routes.

Authentication is a per-route dependency, so the schema pages and ``/metrics``
are readable without an API key. ``enable_api_docs=false`` leaves the schema
routes unregistered; ``otel_enable_prometheus=false`` leaves ``/metrics``
unregistered instead of only removing the collectors behind it.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from docling_serve import app as app_module
from docling_serve.settings import docling_serve_settings

# FastAPI registers the OAuth2 redirect page together with its Swagger UI; the
# offline branch of create_app registers its own copy under the same path.
API_DOCS_ROUTES = (
    "/openapi.json",
    "/swagger",
    "/docs",
    "/docs/oauth2-redirect",
    "/scalar",
)


@pytest.fixture
def make_client(monkeypatch):
    """Build the app with settings overrides.

    No lifespan is entered, so no models are loaded. The orchestrator dependency
    is stubbed as in test_batch_endpoint.py: FastAPI resolves dependencies
    before it validates the body, and the real factory would build a
    LocalOrchestrator with a converter manager and cache it for the rest of the
    session. The OpenTelemetry setup is patched out for the same reason as
    there: each real call would register another collector in the
    process-global Prometheus registry, and ``/metrics`` renders that registry
    either way.
    """
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: MagicMock())

    def _make(**overrides) -> TestClient:
        for name, value in overrides.items():
            monkeypatch.setattr(docling_serve_settings, name, value)
        with patch.object(app_module, "setup_otel_instrumentation"):
            return TestClient(app_module.create_app())

    return _make


@pytest.mark.parametrize("path", API_DOCS_ROUTES)
def test_api_docs_routes_are_served_by_default(make_client, path: str) -> None:
    client = make_client(enable_api_docs=True, static_path=None)

    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", API_DOCS_ROUTES)
def test_api_docs_routes_are_not_registered_when_disabled(
    make_client, path: str
) -> None:
    client = make_client(enable_api_docs=False, static_path=None)

    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", API_DOCS_ROUTES)
def test_offline_api_docs_routes_are_served_by_default(
    make_client, tmp_path, path: str
) -> None:
    # With a static_path the Swagger UI and ReDoc pages come from docling-serve's
    # own routes. The directory stays empty, so this proves the routes are
    # registered; the pages reference /static/*.js that is not there.
    client = make_client(enable_api_docs=True, static_path=tmp_path)

    assert client.get(path).status_code == 200


@pytest.mark.parametrize("path", API_DOCS_ROUTES)
def test_offline_api_docs_routes_are_not_registered_when_disabled(
    make_client, tmp_path, path: str
) -> None:
    client = make_client(enable_api_docs=False, static_path=tmp_path)

    assert client.get(path).status_code == 404


def test_disabling_api_docs_keeps_the_api_routes(make_client) -> None:
    client = make_client(enable_api_docs=False, static_path=None)

    # The request is rejected by validation (422), so the route exists and is
    # reached; an unregistered route would answer 404.
    assert client.post("/v1/convert/source", json={}).status_code == 422
    assert client.get("/health").status_code == 200


def test_metrics_route_is_served_while_prometheus_is_enabled(make_client) -> None:
    response = make_client(otel_enable_prometheus=True).get("/metrics")

    assert response.status_code == 200
    assert "# HELP" in response.text or "# TYPE" in response.text


def test_metrics_route_is_not_registered_when_prometheus_is_disabled(
    make_client,
) -> None:
    assert make_client(otel_enable_prometheus=False).get("/metrics").status_code == 404

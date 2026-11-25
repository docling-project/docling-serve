import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from docling_serve.logging_config import LogContextMiddleware, get_log_context


def _make_client(header_prefix: str) -> TestClient:
    app = FastAPI()
    app.add_middleware(LogContextMiddleware, header_prefix=header_prefix)

    @app.get("/ctx")
    def ctx():
        return get_log_context()

    return TestClient(app)


HEADERS = {
    "Authorization": "Bearer abc",
    "Proxy-Authorization": "Basic xyz",
    "Cookie": "session=123",
    "X-Api-Key": "key",
    "X-Docling-Log-RequestID": "req-42",
}


def test_default_prefix_extracts_matching_headers():
    resp = _make_client("X-Docling-Log-").get("/ctx", headers=HEADERS)
    assert resp.json() == {"requestid": "req-42"}


@pytest.mark.parametrize("prefix", ["", "   "])
def test_empty_prefix_disables_extraction(prefix):
    resp = _make_client(prefix).get("/ctx", headers=HEADERS)
    assert resp.json() == {}


@pytest.mark.parametrize("prefix", ["X-", "proxy-", "a"])
def test_credential_headers_never_extracted(prefix):
    ctx = _make_client(prefix).get("/ctx", headers=HEADERS).json()
    for value in ("Bearer abc", "Basic xyz", "session=123", "key"):
        assert value not in ctx.values()

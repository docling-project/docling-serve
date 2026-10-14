"""Integration tests for WS /v1/convert/ws endpoint.

These tests require the full docling stack to be installed.
Run with: pytest tests/test_ws_convert.py -v
"""

import json

import pytest
from starlette.testclient import TestClient

from docling_serve.app import create_app
from docling_serve.settings import docling_serve_settings


@pytest.fixture(scope="module")
def app():
    """Create the FastAPI app."""
    return create_app()


def _api_key_param() -> str:
    if docling_serve_settings.api_key:
        return f"?api_key={docling_serve_settings.api_key}"
    return ""


class TestWsConvertUrl:
    """Test URL-based conversion over WebSocket."""

    def test_connected_greeting(self, app):
        """Verify the server sends a connected message on connect."""
        with TestClient(app) as client:
            with client.websocket_connect(
                f"/v1/convert/ws{_api_key_param()}"
            ) as ws:
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "connected"
                assert "queue_length" in msg

    def test_invalid_api_key(self, app):
        """Verify auth rejection when API key is configured."""
        if not docling_serve_settings.api_key:
            pytest.skip("No API key configured")

        with TestClient(app) as client:
            with client.websocket_connect(
                "/v1/convert/ws?api_key=wrong_key"
            ) as ws:
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "error"
                assert "API key" in msg["error"]

    def test_unknown_message_type(self, app):
        """Verify error on unknown message type."""
        with TestClient(app) as client:
            with client.websocket_connect(
                f"/v1/convert/ws{_api_key_param()}"
            ) as ws:
                ws.receive_text()  # connected greeting
                ws.send_text(json.dumps({"type": "unknown"}))
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "error"
                assert "Unknown message type" in msg["error"]

    def test_invalid_json(self, app):
        """Verify error on malformed JSON."""
        with TestClient(app) as client:
            with client.websocket_connect(
                f"/v1/convert/ws{_api_key_param()}"
            ) as ws:
                ws.receive_text()  # connected greeting
                ws.send_text("not json at all")
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "error"
                assert "JSON" in msg["error"]


class TestWsConvertFile:
    """Test file upload conversion over WebSocket."""

    def test_upload_too_large(self, app):
        """Verify early rejection of oversized uploads."""
        if docling_serve_settings.max_file_size >= 10**18:
            pytest.skip("No file size limit configured")

        with TestClient(app) as client:
            with client.websocket_connect(
                f"/v1/convert/ws{_api_key_param()}"
            ) as ws:
                ws.receive_text()  # connected greeting
                ws.send_text(
                    json.dumps(
                        {
                            "type": "upload_start",
                            "filename": "huge.pdf",
                            "total_bytes": docling_serve_settings.max_file_size + 1,
                            "content_type": "application/pdf",
                            "chunks": 1,
                            "options": {},
                        }
                    )
                )
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "error"
                assert (
                    "too large" in msg["error"].lower()
                    or "exceeds" in msg["error"].lower()
                )

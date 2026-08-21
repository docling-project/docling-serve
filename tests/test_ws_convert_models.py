"""Tests for WebSocket convert protocol message models."""

import json
import time

import pytest


def test_convert_request_model():
    from docling_serve.ws_convert import WsConvertRequest

    msg = WsConvertRequest(
        sources=[{"kind": "http", "url": "https://example.com/doc.pdf"}],
        options={"to_formats": ["md"]},
        target_type="inbody",
    )
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "convert"
    assert len(data["sources"]) == 1
    assert data["target_type"] == "inbody"


def test_upload_start_model():
    from docling_serve.ws_convert import WsUploadStart

    msg = WsUploadStart(
        filename="report.pdf",
        total_bytes=5_242_880,
        content_type="application/pdf",
        chunks=5,
        options={"to_formats": ["md"]},
        target_type="zip",
    )
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "upload_start"
    assert data["total_bytes"] == 5_242_880
    assert data["chunks"] == 5


def test_upload_end_model():
    from docling_serve.ws_convert import WsUploadEnd

    msg = WsUploadEnd(sha256="abc123")
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "upload_end"
    assert data["sha256"] == "abc123"


def test_connected_model():
    from docling_serve.ws_convert import WsConnected

    msg = WsConnected(queue_length=3)
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "connected"
    assert data["queue_length"] == 3


def test_status_model():
    from docling_serve.ws_convert import WsStatus

    msg = WsStatus(
        task_id="abc",
        task_status="processing",
        task_position=None,
        progress=0.5,
        message="Running OCR...",
    )
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "status"
    assert data["progress"] == 0.5
    assert data["task_position"] is None


def test_heartbeat_model():
    from docling_serve.ws_convert import WsHeartbeat

    before = time.time()
    msg = WsHeartbeat(task_position=2)
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "heartbeat"
    assert data["task_position"] == 2
    assert data["timestamp"] >= before


def test_result_start_model():
    from docling_serve.ws_convert import WsResultStart

    msg = WsResultStart(
        task_id="abc",
        total_bytes=15_000_000,
        content_type="application/json",
        chunks=15,
    )
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "result_start"
    assert data["total_bytes"] == 15_000_000


def test_result_end_model():
    from docling_serve.ws_convert import WsResultEnd

    msg = WsResultEnd(task_id="abc", sha256="def456")
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "result_end"


def test_error_model():
    from docling_serve.ws_convert import WsError

    msg = WsError(error="Something went wrong", task_id="abc")
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "error"
    assert data["task_id"] == "abc"

    msg_no_task = WsError(error="Bad request")
    data2 = json.loads(msg_no_task.model_dump_json())
    assert data2["task_id"] is None

"""Tests for the chunked result sender helper."""

import hashlib
import json
import math

import pytest

from docling_serve.ws_convert import send_chunked_result, CHUNK_SIZE


class FakeWebSocket:
    """Collects messages sent by the server."""

    def __init__(self):
        self.text_messages: list[str] = []
        self.binary_messages: list[bytes] = []

    async def send_text(self, text: str):
        self.text_messages.append(text)

    async def send_bytes(self, data: bytes):
        self.binary_messages.append(data)


@pytest.mark.asyncio
async def test_send_chunked_result_json():
    ws = FakeWebSocket()
    result_bytes = b'{"document": {"md": "# Hello"}}' * 100
    task_id = "test-task-123"

    await send_chunked_result(
        ws,
        task_id=task_id,
        result_bytes=result_bytes,
        content_type="application/json",
    )

    # Should have result_start, binary chunks, result_end
    assert len(ws.text_messages) == 2  # result_start + result_end
    expected_chunks = math.ceil(len(result_bytes) / CHUNK_SIZE)
    assert len(ws.binary_messages) == expected_chunks

    # Verify result_start
    start = json.loads(ws.text_messages[0])
    assert start["type"] == "result_start"
    assert start["task_id"] == task_id
    assert start["total_bytes"] == len(result_bytes)
    assert start["content_type"] == "application/json"
    assert start["chunks"] == expected_chunks

    # Verify result_end
    end = json.loads(ws.text_messages[1])
    assert end["type"] == "result_end"
    assert end["sha256"] == hashlib.sha256(result_bytes).hexdigest()

    # Reassemble and verify
    reassembled = b"".join(ws.binary_messages)
    assert reassembled == result_bytes


@pytest.mark.asyncio
async def test_send_chunked_result_large_binary():
    ws = FakeWebSocket()
    # 3.5 MB of binary data -> should be 4 chunks
    result_bytes = b"\x00\xff" * (CHUNK_SIZE * 2 - 100)
    task_id = "zip-task-456"

    await send_chunked_result(
        ws,
        task_id=task_id,
        result_bytes=result_bytes,
        content_type="application/zip",
    )

    expected_chunks = math.ceil(len(result_bytes) / CHUNK_SIZE)
    assert len(ws.binary_messages) == expected_chunks
    reassembled = b"".join(ws.binary_messages)
    assert reassembled == result_bytes

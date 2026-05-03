"""Tests for the chunked file upload receive helper."""

import hashlib
import json

import pytest

from docling_serve.ws_convert import WsUploadStart, receive_upload


class FakeWebSocket:
    """Simulates a WebSocket that yields binary frames then an upload_end JSON."""

    def __init__(self, file_bytes: bytes, chunk_size: int = 1024):
        self._frames: list[dict | bytes] = []
        # Split file into binary chunks
        for i in range(0, len(file_bytes), chunk_size):
            self._frames.append(file_bytes[i : i + chunk_size])
        # Final upload_end message
        sha = hashlib.sha256(file_bytes).hexdigest()
        self._frames.append(
            {"type": "upload_end", "sha256": sha}
        )
        self._index = 0
        self.sent: list[str] = []

    async def receive(self) -> dict:
        frame = self._frames[self._index]
        self._index += 1
        if isinstance(frame, bytes):
            return {"type": "websocket.receive", "bytes": frame}
        else:
            return {"type": "websocket.receive", "text": json.dumps(frame)}

    async def send_text(self, text: str):
        self.sent.append(text)


class FakeWebSocketBadChecksum(FakeWebSocket):
    """Sends a wrong SHA-256 in upload_end."""

    def __init__(self, file_bytes: bytes, chunk_size: int = 1024):
        super().__init__(file_bytes, chunk_size)
        # Replace the last frame with a bad checksum
        self._frames[-1] = {"type": "upload_end", "sha256": "bad_checksum"}


@pytest.mark.asyncio
async def test_receive_upload_success(tmp_path):
    file_content = b"Hello world! " * 1000  # ~13KB
    ws = FakeWebSocket(file_content, chunk_size=4096)
    header = WsUploadStart(
        filename="test.pdf",
        total_bytes=len(file_content),
        content_type="application/pdf",
        chunks=4,  # approximate
        options={},
    )

    result_path = await receive_upload(ws, header, scratch_dir=tmp_path)

    assert result_path.exists()
    assert result_path.read_bytes() == file_content
    assert result_path.name == "test.pdf"


@pytest.mark.asyncio
async def test_receive_upload_bad_checksum(tmp_path):
    file_content = b"Hello world! " * 1000
    ws = FakeWebSocketBadChecksum(file_content, chunk_size=4096)
    header = WsUploadStart(
        filename="test.pdf",
        total_bytes=len(file_content),
        content_type="application/pdf",
        chunks=4,
        options={},
    )

    with pytest.raises(ValueError, match="SHA-256"):
        await receive_upload(ws, header, scratch_dir=tmp_path)

    # Temp file should be cleaned up
    assert not list(tmp_path.iterdir())

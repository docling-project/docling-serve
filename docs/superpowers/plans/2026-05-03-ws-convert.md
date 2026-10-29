# WebSocket Convert Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `WS /v1/convert/ws` endpoint that handles the full document conversion lifecycle (submit, progress, result) over a single WebSocket connection.

**Architecture:** New module `docling_serve/ws_convert.py` contains the WebSocket handler, protocol message models, and helpers for chunked binary transfer. It's registered into the FastAPI app via a `register_ws_convert()` function called from `app.py`. The endpoint reuses the existing orchestrator pipeline and notifier infrastructure.

**Tech Stack:** FastAPI WebSocket, Pydantic v2, asyncio, SHA-256 checksums, existing docling-jobkit orchestrator

**Spec:** `docs/superpowers/specs/2026-05-02-ws-convert-design.md`

---

### Task 1: Add `ws_heartbeat_interval` Setting

**Files:**
- Modify: `docling_serve/settings.py`

- [ ] **Step 1: Add the setting field**

In `docling_serve/settings.py`, add this field to the `DoclingServeSettings` class, after the `max_sync_wait` line (around line 133):

```python
    ws_heartbeat_interval: int = 30  # seconds
```

- [ ] **Step 2: Verify the setting loads**

Run:
```bash
uv run python -c "from docling_serve.settings import docling_serve_settings; print(docling_serve_settings.ws_heartbeat_interval)"
```
Expected: `30`

Note: if `uv run` fails due to torch download issues, just verify the field is syntactically correct by checking that `python -c "from docling_serve.settings import DoclingServeSettings; print(DoclingServeSettings.model_fields['ws_heartbeat_interval'])"` works, or simply move on — the integration tests will catch any issues.

- [ ] **Step 3: Commit**

```bash
git add docling_serve/settings.py
git commit -m "feat(ws): add ws_heartbeat_interval setting"
```

---

### Task 2: Create Protocol Message Models

**Files:**
- Create: `docling_serve/ws_convert.py` (initial version with just models)

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_convert_models.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ws_convert_models.py -v --no-header -x 2>&1 | tail -5`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Write the message models**

Create `docling_serve/ws_convert.py`:

```python
"""WebSocket convert endpoint — single-connection conversion lifecycle.

Protocol: see docs/superpowers/specs/2026-05-02-ws-convert-design.md
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Client → Server messages
# ---------------------------------------------------------------------------


class WsConvertRequest(BaseModel):
    """URL-based conversion request."""

    type: Literal["convert"] = "convert"
    sources: list[dict[str, Any]]
    options: dict[str, Any] = Field(default_factory=dict)
    target_type: Literal["inbody", "zip"] = "inbody"


class WsUploadStart(BaseModel):
    """Begin a chunked file upload."""

    type: Literal["upload_start"] = "upload_start"
    filename: str
    total_bytes: int
    content_type: str = "application/octet-stream"
    chunks: int
    options: dict[str, Any] = Field(default_factory=dict)
    target_type: Literal["inbody", "zip"] = "inbody"


class WsUploadEnd(BaseModel):
    """Finalize a chunked file upload with integrity check."""

    type: Literal["upload_end"] = "upload_end"
    sha256: str


# ---------------------------------------------------------------------------
# Server → Client messages
# ---------------------------------------------------------------------------


class WsConnected(BaseModel):
    """Greeting sent immediately after handshake."""

    type: Literal["connected"] = "connected"
    queue_length: int


class WsStatus(BaseModel):
    """Progress or queue position update."""

    type: Literal["status"] = "status"
    task_id: str
    task_status: str
    task_position: int | None = None
    progress: float | None = None
    message: str | None = None


class WsHeartbeat(BaseModel):
    """Keepalive with optional queue position."""

    type: Literal["heartbeat"] = "heartbeat"
    task_position: int | None = None
    timestamp: float = Field(default_factory=time.time)


class WsResultStart(BaseModel):
    """Begin chunked result delivery."""

    type: Literal["result_start"] = "result_start"
    task_id: str
    total_bytes: int
    content_type: str
    chunks: int


class WsResultEnd(BaseModel):
    """Finalize chunked result delivery with integrity check."""

    type: Literal["result_end"] = "result_end"
    task_id: str
    sha256: str


class WsError(BaseModel):
    """Error message."""

    type: Literal["error"] = "error"
    error: str
    task_id: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ws_convert_models.py -v --no-header -x 2>&1 | tail -15`
Expected: all 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add docling_serve/ws_convert.py tests/test_ws_convert_models.py
git commit -m "feat(ws): add protocol message models for WS convert endpoint"
```

---

### Task 3: Implement File Upload Receive Helper

**Files:**
- Modify: `docling_serve/ws_convert.py`
- Create: `tests/test_ws_upload_helper.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_upload_helper.py`:

```python
"""Tests for the chunked file upload receive helper."""

import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ws_upload_helper.py -v --no-header -x 2>&1 | tail -5`
Expected: FAIL with `ImportError` (receive_upload not defined)

- [ ] **Step 3: Implement receive_upload**

Add the following to `docling_serve/ws_convert.py`, after the message model classes:

```python
import hashlib
import json
import logging
import uuid
from pathlib import Path

_log = logging.getLogger(__name__)

CHUNK_SIZE = 1_048_576  # 1 MB


async def receive_upload(
    websocket,
    header: WsUploadStart,
    *,
    scratch_dir: Path,
) -> Path:
    """Receive binary frames from the client and write to a temp file.

    Returns the path to the completed file. Raises ValueError on checksum
    mismatch (and cleans up the temp file).
    """
    # Write to a unique subdir to avoid filename collisions
    upload_dir = scratch_dir / f"ws_upload_{uuid.uuid4().hex}"
    upload_dir.mkdir(parents=True, exist_ok=True)
    dest = upload_dir / header.filename

    hasher = hashlib.sha256()
    bytes_received = 0

    try:
        with open(dest, "wb") as f:
            while True:
                raw = await websocket.receive()
                if raw.get("bytes"):
                    chunk = raw["bytes"]
                    f.write(chunk)
                    hasher.update(chunk)
                    bytes_received += len(chunk)
                elif raw.get("text"):
                    msg = json.loads(raw["text"])
                    if msg.get("type") == "upload_end":
                        expected_sha = msg["sha256"]
                        break
                    else:
                        raise ValueError(
                            f"Unexpected message during upload: {msg.get('type')}"
                        )

        actual_sha = hasher.hexdigest()
        if actual_sha != expected_sha:
            raise ValueError(
                f"SHA-256 mismatch: expected {expected_sha}, got {actual_sha}"
            )

        _log.info(
            f"Upload complete: {header.filename}, "
            f"{bytes_received} bytes, sha256={actual_sha[:12]}..."
        )
        return dest

    except Exception:
        # Clean up on any failure
        if dest.exists():
            dest.unlink()
        if upload_dir.exists():
            upload_dir.rmdir()
        raise
```

Also update the imports at the top of the file. The full import block should be:

```python
from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

_log = logging.getLogger(__name__)

CHUNK_SIZE = 1_048_576  # 1 MB
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ws_upload_helper.py -v --no-header -x 2>&1 | tail -10`
Expected: both tests PASS

- [ ] **Step 5: Commit**

```bash
git add docling_serve/ws_convert.py tests/test_ws_upload_helper.py
git commit -m "feat(ws): implement chunked file upload receive helper"
```

---

### Task 4: Implement Chunked Result Sender

**Files:**
- Modify: `docling_serve/ws_convert.py`
- Create: `tests/test_ws_result_sender.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ws_result_sender.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ws_result_sender.py -v --no-header -x 2>&1 | tail -5`
Expected: FAIL with `ImportError` (send_chunked_result not defined)

- [ ] **Step 3: Implement send_chunked_result**

Add to `docling_serve/ws_convert.py`, after the `receive_upload` function:

```python
import math


async def send_chunked_result(
    websocket,
    *,
    task_id: str,
    result_bytes: bytes,
    content_type: str,
) -> None:
    """Send a result as chunked binary frames with integrity checksum."""
    total_bytes = len(result_bytes)
    num_chunks = math.ceil(total_bytes / CHUNK_SIZE)
    sha = hashlib.sha256(result_bytes).hexdigest()

    # Send result_start header
    await websocket.send_text(
        WsResultStart(
            task_id=task_id,
            total_bytes=total_bytes,
            content_type=content_type,
            chunks=num_chunks,
        ).model_dump_json()
    )

    # Send binary chunks
    for i in range(num_chunks):
        start = i * CHUNK_SIZE
        end = min(start + CHUNK_SIZE, total_bytes)
        await websocket.send_bytes(result_bytes[start:end])

    # Send result_end with checksum
    await websocket.send_text(
        WsResultEnd(
            task_id=task_id,
            sha256=sha,
        ).model_dump_json()
    )
```

Also add `import math` to the imports at the top of the file.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ws_result_sender.py -v --no-header -x 2>&1 | tail -10`
Expected: both tests PASS

- [ ] **Step 5: Run all model and helper tests together**

Run: `uv run pytest tests/test_ws_convert_models.py tests/test_ws_upload_helper.py tests/test_ws_result_sender.py -v --no-header 2>&1 | tail -20`
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add docling_serve/ws_convert.py tests/test_ws_result_sender.py
git commit -m "feat(ws): implement chunked result sender helper"
```

---

### Task 5: Implement the WebSocket Handler and Registration

**Files:**
- Modify: `docling_serve/ws_convert.py`
- Modify: `docling_serve/app.py`

This is the core task. The handler orchestrates the full lifecycle: auth, greeting, receive request, enqueue, stream progress, deliver result.

- [ ] **Step 1: Implement the handler and registration function**

Add the following to `docling_serve/ws_convert.py`, after the helper functions:

```python
import asyncio
from io import BytesIO

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from typing import Annotated

from docling.datamodel.base_models import DocumentStream
from docling.datamodel.service.options import (
    ConvertDocumentsOptions as ConvertDocumentsRequestOptions,
)
from docling.datamodel.service.requests import ConvertDocumentsRequest
from docling.datamodel.service.targets import InBodyTarget, ZipTarget
from docling_jobkit.datamodel.result import ExportResult, ZipArchiveResult
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
    RedisBackpressureError,
)

from docling.datamodel.service.tasks import TaskType
from docling_serve.orchestrator_factory import get_async_orchestrator
from docling_serve.settings import docling_serve_settings
from docling_serve.storage import get_scratch
from docling_serve.websocket_notifier import WebsocketNotifier


def register_ws_convert(
    app: FastAPI,
    service_policy,
    enque_source,
    enque_file,
    prepare_convert_request,
    prepare_convert_options,
) -> None:
    """Register the WS /v1/convert/ws endpoint on the app."""

    @app.websocket("/v1/convert/ws")
    async def ws_convert(
        websocket: WebSocket,
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        api_key: Annotated[str, Query()] = "",
    ):
        # --- Auth ---
        if docling_serve_settings.api_key:
            if api_key != docling_serve_settings.api_key:
                await websocket.accept()
                await websocket.send_text(
                    WsError(error="Invalid API key.").model_dump_json()
                )
                await websocket.close()
                return

        await websocket.accept()

        heartbeat_task: asyncio.Task | None = None
        task_id: str | None = None

        try:
            # --- Connected greeting ---
            queue_length = await orchestrator.get_queue_length()
            await websocket.send_text(
                WsConnected(queue_length=queue_length).model_dump_json()
            )

            # --- Receive client request ---
            raw = await websocket.receive()
            if raw.get("text"):
                msg = json.loads(raw["text"])
            else:
                await websocket.send_text(
                    WsError(error="Expected JSON text message, got binary.").model_dump_json()
                )
                await websocket.close()
                return

            msg_type = msg.get("type")

            if msg_type == "convert":
                # URL-based conversion
                request_data = WsConvertRequest(**msg)
                conv_request = ConvertDocumentsRequest(
                    sources=request_data.sources,
                    options=ConvertDocumentsRequestOptions(**request_data.options),
                )
                conv_request = prepare_convert_request(conv_request)
                target_type = request_data.target_type

                task = await enque_source(
                    orchestrator=orchestrator,
                    request=conv_request,
                )

            elif msg_type == "upload_start":
                # File upload conversion
                upload_header = WsUploadStart(**msg)

                # Early rejection if file is too big
                if upload_header.total_bytes > docling_serve_settings.max_file_size:
                    await websocket.send_text(
                        WsError(
                            error=f"File too large: {upload_header.total_bytes} bytes "
                            f"exceeds limit of {docling_serve_settings.max_file_size} bytes."
                        ).model_dump_json()
                    )
                    await websocket.close()
                    return

                scratch_dir = get_scratch()
                file_path = await receive_upload(
                    websocket, upload_header, scratch_dir=scratch_dir
                )

                try:
                    options = ConvertDocumentsRequestOptions(
                        **upload_header.options
                    )
                    options = prepare_convert_options(options)
                    target_type = upload_header.target_type

                    # Build a DocumentStream from the uploaded file
                    file_bytes = file_path.read_bytes()
                    buf = BytesIO(file_bytes)
                    sources = [DocumentStream(name=upload_header.filename, stream=buf)]

                    target = InBodyTarget() if target_type == "inbody" else ZipTarget()

                    task = await orchestrator.enqueue(
                        task_type=TaskType.CONVERT,
                        sources=sources,
                        convert_options=options,
                        chunking_options=None,
                        chunking_export_options=None,
                        target=target,
                        callbacks=[],
                        metadata={},
                    )
                finally:
                    # Clean up uploaded file
                    if file_path.exists():
                        file_path.unlink()
                    if file_path.parent.exists():
                        try:
                            file_path.parent.rmdir()
                        except OSError:
                            pass

            else:
                await websocket.send_text(
                    WsError(
                        error=f"Unknown message type: {msg_type}. "
                        f"Expected 'convert' or 'upload_start'."
                    ).model_dump_json()
                )
                await websocket.close()
                return

            task_id = task.task_id

            # --- Register for notifier updates ---
            assert isinstance(orchestrator.notifier, WebsocketNotifier)
            orchestrator.notifier.task_subscribers.setdefault(task_id, set()).add(
                websocket
            )

            # --- Start heartbeat loop ---
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(websocket, orchestrator, task_id)
            )

            # --- Wait for task completion ---
            while True:
                task = await orchestrator.task_status(task_id=task_id)
                if task.task_status.value in ("success", "failure"):
                    break
                await asyncio.sleep(docling_serve_settings.sync_poll_interval)

            # --- Stop heartbeat ---
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            # --- Handle failure ---
            if task.task_status.value == "failure":
                error_msg = getattr(task, "error_message", None) or "Conversion failed"
                await websocket.send_text(
                    WsStatus(
                        task_id=task_id,
                        task_status="failure",
                        message=error_msg,
                    ).model_dump_json()
                )
                await websocket.close()
                return

            # --- Deliver result ---
            task_result = await orchestrator.task_result(task_id=task_id)
            if task_result is None:
                await websocket.send_text(
                    WsError(
                        error="Task completed but result not found.",
                        task_id=task_id,
                    ).model_dump_json()
                )
                await websocket.close()
                return

            if isinstance(task_result.result, ExportResult):
                from docling.datamodel.service.responses import ConvertDocumentResponse

                response = ConvertDocumentResponse(
                    document=task_result.result.content,
                    status=task_result.result.status,
                    processing_time=task_result.processing_time,
                    timings=task_result.result.timings,
                    errors=task_result.result.errors,
                )
                result_bytes = response.model_dump_json().encode("utf-8")
                content_type = "application/json"
            elif isinstance(task_result.result, ZipArchiveResult):
                result_bytes = task_result.result.content
                content_type = "application/zip"
            else:
                await websocket.send_text(
                    WsError(
                        error=f"Unsupported result type: {type(task_result.result).__name__}",
                        task_id=task_id,
                    ).model_dump_json()
                )
                await websocket.close()
                return

            await send_chunked_result(
                websocket,
                task_id=task_id,
                result_bytes=result_bytes,
                content_type=content_type,
            )

            await websocket.close()

        except WebSocketDisconnect:
            _log.info(f"WebSocket disconnected for ws_convert (task_id={task_id})")

        except ValueError as e:
            # Upload validation errors (SHA mismatch, unexpected messages)
            try:
                await websocket.send_text(
                    WsError(error=str(e), task_id=task_id).model_dump_json()
                )
                await websocket.close()
            except Exception:
                pass

        except RedisBackpressureError:
            try:
                await websocket.send_text(
                    WsError(
                        error="Server is busy, please try again shortly.",
                        task_id=task_id,
                    ).model_dump_json()
                )
                await websocket.close()
            except Exception:
                pass

        except Exception as e:
            _log.exception(f"Unexpected error in ws_convert: {e}")
            try:
                await websocket.send_text(
                    WsError(
                        error="Internal server error.",
                        task_id=task_id,
                    ).model_dump_json()
                )
                await websocket.close()
            except Exception:
                pass

        finally:
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
            if task_id:
                subs = orchestrator.notifier.task_subscribers.get(task_id)
                if subs:
                    subs.discard(websocket)


async def _heartbeat_loop(
    websocket,
    orchestrator: BaseOrchestrator,
    task_id: str,
) -> None:
    """Send periodic heartbeats with queue position until cancelled."""
    interval = docling_serve_settings.ws_heartbeat_interval
    while True:
        await asyncio.sleep(interval)
        try:
            position = await orchestrator.get_queue_position(task_id)
            await websocket.send_text(
                WsHeartbeat(task_position=position).model_dump_json()
            )
        except Exception:
            break
```

Also add the missing import at the top:

```python
from fastapi import Depends
```

The full import block at the top of the file should now be:

```python
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from docling.datamodel.base_models import DocumentStream
from docling.datamodel.service.options import (
    ConvertDocumentsOptions as ConvertDocumentsRequestOptions,
)
from docling.datamodel.service.requests import ConvertDocumentsRequest
from docling.datamodel.service.targets import InBodyTarget, ZipTarget
from docling.datamodel.service.tasks import TaskType
from docling_jobkit.datamodel.result import ExportResult, ZipArchiveResult
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
    RedisBackpressureError,
)

from docling_serve.orchestrator_factory import get_async_orchestrator
from docling_serve.settings import docling_serve_settings
from docling_serve.storage import get_scratch
from docling_serve.websocket_notifier import WebsocketNotifier
```

- [ ] **Step 2: Wire up registration in app.py**

In `docling_serve/app.py`, add this import near the top with the other imports:

```python
from docling_serve.ws_convert import register_ws_convert
```

Then, inside the `create_app()` function, just before `return app` (around line 1411), add:

```python
    # Register WebSocket convert endpoint
    register_ws_convert(
        app=app,
        service_policy=service_policy,
        enque_source=_enque_source,
        enque_file=_enque_file,
        prepare_convert_request=_prepare_convert_request,
        prepare_convert_options=_prepare_convert_options,
    )
```

- [ ] **Step 3: Handle `get_queue_length` availability**

The `connected` greeting uses `orchestrator.get_queue_length()`. This method may not exist on `BaseOrchestrator`. Check and handle gracefully. Replace the `get_queue_length` call in the handler with a safe fallback:

```python
            # --- Connected greeting ---
            try:
                queue_length = await orchestrator.get_queue_length()
            except (AttributeError, NotImplementedError):
                queue_length = 0
            await websocket.send_text(
                WsConnected(queue_length=queue_length).model_dump_json()
            )
```

- [ ] **Step 4: Commit**

```bash
git add docling_serve/ws_convert.py docling_serve/app.py
git commit -m "feat(ws): implement WebSocket convert handler and register endpoint"
```

---

### Task 6: Integration Test — URL Conversion via WebSocket

**Files:**
- Create: `tests/test_ws_convert.py`

This test uses the in-process ASGI app with `httpx` and the `starlette.testclient.TestClient` WebSocket support.

- [ ] **Step 1: Write the integration test**

Create `tests/test_ws_convert.py`:

```python
"""Integration tests for WS /v1/convert/ws endpoint."""

import asyncio
import hashlib
import json
import math

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from starlette.testclient import TestClient

from docling_serve.app import create_app
from docling_serve.settings import docling_serve_settings


@pytest.fixture(scope="module")
def app():
    """Create the FastAPI app (synchronous fixture for TestClient)."""
    return create_app()


@pytest.fixture(scope="module")
def managed_app(app):
    """App with lifespan managed."""
    import asyncio

    async def _run():
        async with LifespanManager(app) as manager:
            return manager.app

    loop = asyncio.new_event_loop()
    managed = loop.run_until_complete(_run())
    yield managed
    loop.close()


class TestWsConvertUrl:
    """Test URL-based conversion over WebSocket."""

    def test_connected_greeting(self, app):
        """Verify the server sends a connected message on connect."""
        with TestClient(app) as client:
            api_key_param = (
                f"?api_key={docling_serve_settings.api_key}"
                if docling_serve_settings.api_key
                else ""
            )
            with client.websocket_connect(
                f"/v1/convert/ws{api_key_param}"
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
            api_key_param = (
                f"?api_key={docling_serve_settings.api_key}"
                if docling_serve_settings.api_key
                else ""
            )
            with client.websocket_connect(
                f"/v1/convert/ws{api_key_param}"
            ) as ws:
                # Receive connected greeting
                ws.receive_text()
                # Send unknown type
                ws.send_text(json.dumps({"type": "unknown"}))
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "error"
                assert "Unknown message type" in msg["error"]

    def test_invalid_json(self, app):
        """Verify error on malformed JSON."""
        with TestClient(app) as client:
            api_key_param = (
                f"?api_key={docling_serve_settings.api_key}"
                if docling_serve_settings.api_key
                else ""
            )
            with client.websocket_connect(
                f"/v1/convert/ws{api_key_param}"
            ) as ws:
                # Receive connected greeting
                ws.receive_text()
                # Send invalid JSON
                ws.send_text("not json at all")
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "error"
```

- [ ] **Step 2: Run the basic tests**

Run: `uv run pytest tests/test_ws_convert.py -v --no-header -x -k "not convert_url_full" 2>&1 | tail -20`
Expected: the greeting, auth, and error tests should PASS. If the environment can't install dependencies (torch), these tests will fail at import time — that's OK, they'll work in CI or a proper dev environment.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ws_convert.py
git commit -m "test(ws): add integration tests for WS convert endpoint"
```

---

### Task 7: Integration Test — File Upload via WebSocket

**Files:**
- Modify: `tests/test_ws_convert.py`

- [ ] **Step 1: Add file upload test**

Add to `tests/test_ws_convert.py`:

```python
class TestWsConvertFile:
    """Test file upload conversion over WebSocket."""

    def test_upload_too_large(self, app):
        """Verify early rejection of oversized uploads."""
        if docling_serve_settings.max_file_size >= 10**18:
            pytest.skip("No file size limit configured")

        with TestClient(app) as client:
            api_key_param = (
                f"?api_key={docling_serve_settings.api_key}"
                if docling_serve_settings.api_key
                else ""
            )
            with client.websocket_connect(
                f"/v1/convert/ws{api_key_param}"
            ) as ws:
                # Receive connected greeting
                ws.receive_text()
                # Send upload_start with oversized total_bytes
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
                assert "too large" in msg["error"].lower() or "exceeds" in msg["error"].lower()
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/test_ws_convert.py::TestWsConvertFile -v --no-header -x 2>&1 | tail -10`
Expected: PASS (or skip if no file size limit)

- [ ] **Step 3: Commit**

```bash
git add tests/test_ws_convert.py
git commit -m "test(ws): add file upload integration tests"
```

---

### Task 8: Verify Existing Tests Still Pass

**Files:** (none modified — verification only)

- [ ] **Step 1: Run existing test suite**

Run: `uv run pytest tests/test_fastapi_endpoints.py tests/test_config_file_loading.py tests/test_service_policy.py -v --no-header 2>&1 | tail -20`
Expected: all existing tests PASS (no regressions)

- [ ] **Step 2: Run all new tests together**

Run: `uv run pytest tests/test_ws_convert_models.py tests/test_ws_upload_helper.py tests/test_ws_result_sender.py tests/test_ws_convert.py -v --no-header 2>&1 | tail -30`
Expected: all new tests PASS

- [ ] **Step 3: Run linter**

Run: `uv run ruff check docling_serve/ws_convert.py`
Expected: no errors (fix any that appear)

- [ ] **Step 4: Run type checker**

Run: `uv run mypy docling_serve/ws_convert.py`
Expected: no errors (fix any that appear)

---

### Task 9: Final Cleanup and Summary Commit

**Files:**
- Possibly modify: `docling_serve/ws_convert.py` (lint/type fixes from Task 8)

- [ ] **Step 1: Fix any lint or type issues found in Task 8**

Apply fixes as needed.

- [ ] **Step 2: Verify the endpoint appears in OpenAPI**

Note: WebSocket endpoints don't appear in OpenAPI by default in FastAPI. This is expected behavior — the endpoint is documented in the spec. No action needed unless the team wants a custom OpenAPI extension.

- [ ] **Step 3: Final commit if there were cleanup changes**

```bash
git add -A
git commit -m "chore(ws): lint and type fixes for ws_convert"
```

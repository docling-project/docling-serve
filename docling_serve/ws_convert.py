"""WebSocket convert endpoint — single-connection conversion lifecycle.

Protocol: see docs/superpowers/specs/2026-05-02-ws-convert-design.md
"""

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

# These must be module-level so get_type_hints() can resolve the WebSocket
# handler's Annotated[...] signature (from __future__ annotations are lazy).
from docling_jobkit.orchestrators.base_orchestrator import BaseOrchestrator

from docling_serve.orchestrator_factory import get_async_orchestrator

_log = logging.getLogger(__name__)

CHUNK_SIZE = 1_048_576  # 1 MB


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
    elapsed: float | None = None
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
        with open(dest, "wb") as f:  # noqa: ASYNC230
            while True:
                raw = await websocket.receive()
                if raw.get("bytes") is not None:
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


async def send_chunked_result(
    websocket,
    *,
    task_id: str,
    result_path: Path,
    content_type: str,
) -> None:
    """Stream a result file as chunked binary frames with integrity checksum.

    Reads from *result_path* in CHUNK_SIZE pieces so the full payload is
    never held in memory at once.  The file is deleted after delivery.
    """
    total_bytes = result_path.stat().st_size
    num_chunks = math.ceil(total_bytes / CHUNK_SIZE)

    # Send result_start header
    await websocket.send_text(
        WsResultStart(
            task_id=task_id,
            total_bytes=total_bytes,
            content_type=content_type,
            chunks=num_chunks,
        ).model_dump_json()
    )

    # Stream binary chunks from disk, computing SHA as we go.
    # NOTE: Do NOT yield (asyncio.sleep(0)) between sends — doing so
    # lets the websockets library's read task process an incoming ping
    # and send a pong, which races with our data write and triggers an
    # AssertionError in the drain helper.
    hasher = hashlib.sha256()
    with open(result_path, "rb") as f:  # noqa: ASYNC230
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
            await websocket.send_bytes(chunk)

    # Send result_end with checksum
    await websocket.send_text(
        WsResultEnd(
            task_id=task_id,
            sha256=hasher.hexdigest(),
        ).model_dump_json()
    )


def register_ws_convert(  # noqa: C901
    app: FastAPI,
    enque_source,
    prepare_convert_request,
    prepare_convert_options,
) -> None:
    """Register the WS /v1/convert/ws endpoint on the app."""
    from docling.datamodel.base_models import DocumentStream
    from docling.datamodel.service.options import (
        ConvertDocumentsOptions as ConvertDocumentsRequestOptions,
    )
    from docling.datamodel.service.requests import ConvertDocumentsRequest
    from docling.datamodel.service.targets import InBodyTarget, ZipTarget
    from docling.datamodel.service.tasks import TaskType
    from docling_jobkit.datamodel.result import ExportResult, ZipArchiveResult
    from docling_jobkit.orchestrators.base_orchestrator import (
        RedisBackpressureError,
    )

    from docling_serve.settings import docling_serve_settings as settings
    from docling_serve.storage import get_scratch

    _log.info("Registering WS /v1/convert/ws endpoint")

    @app.websocket("/v1/convert/ws")
    async def ws_convert(  # noqa: C901
        websocket: WebSocket,
        orchestrator: Annotated[BaseOrchestrator, Depends(get_async_orchestrator)],
        api_key: Annotated[str, Query()] = "",
    ):
        # --- Auth ---
        if settings.api_key:
            if api_key != settings.api_key:
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
            try:
                queue_length = await orchestrator.queue_size()
            except (AttributeError, NotImplementedError):
                queue_length = 0
            await websocket.send_text(
                WsConnected(queue_length=queue_length).model_dump_json()
            )

            # --- Receive client request ---
            raw = await websocket.receive()
            if raw.get("text"):
                try:
                    msg = json.loads(raw["text"])
                except json.JSONDecodeError:
                    await websocket.send_text(
                        WsError(error="Invalid JSON.").model_dump_json()
                    )
                    await websocket.close()
                    return
            else:
                await websocket.send_text(
                    WsError(
                        error="Expected JSON text message, got binary."
                    ).model_dump_json()
                )
                await websocket.close()
                return

            msg_type = msg.get("type")

            if msg_type == "convert":
                # URL-based conversion
                request_data = WsConvertRequest(**msg)
                target = InBodyTarget() if request_data.target_type == "inbody" else ZipTarget()
                conv_request = ConvertDocumentsRequest(
                    sources=request_data.sources,
                    options=ConvertDocumentsRequestOptions(**request_data.options),
                    target=target,
                )
                conv_request = prepare_convert_request(conv_request)

                task = await enque_source(
                    orchestrator=orchestrator,
                    request=conv_request,
                )

            elif msg_type == "upload_start":
                # File upload conversion
                upload_header = WsUploadStart(**msg)

                # Early rejection if file is too big
                if upload_header.total_bytes > settings.max_file_size:
                    await websocket.send_text(
                        WsError(
                            error=f"File too large: {upload_header.total_bytes} bytes "
                            f"exceeds limit of {settings.max_file_size} bytes."
                        ).model_dump_json()
                    )
                    await websocket.close()
                    return

                scratch_dir = get_scratch()
                file_path = await receive_upload(
                    websocket, upload_header, scratch_dir=scratch_dir
                )

                try:
                    options = ConvertDocumentsRequestOptions(**upload_header.options)
                    options = prepare_convert_options(options)
                    target_type = upload_header.target_type

                    # Build a DocumentStream from the uploaded file
                    file_bytes = file_path.read_bytes()
                    buf = BytesIO(file_bytes)
                    sources = [
                        DocumentStream(name=upload_header.filename, stream=buf)
                    ]

                    target = (
                        InBodyTarget() if target_type == "inbody" else ZipTarget()
                    )

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

            # NOTE: We intentionally do NOT register in
            # orchestrator.notifier.task_subscribers here. The notifier sends
            # WebsocketMessage objects (a different format than our WsStatus
            # protocol) and would close the socket on task completion before
            # we can deliver the chunked result. Instead, this handler has its
            # own polling loop and heartbeat.

            # --- Start heartbeat loop ---
            task_start_time = time.time()
            heartbeat_task = asyncio.create_task(
                _heartbeat_loop(websocket, orchestrator, task_id, task_start_time)
            )

            # --- Wait for task completion ---
            while True:
                task = await orchestrator.task_status(task_id=task_id)
                if task.task_status.value in ("success", "failure"):
                    break
                await asyncio.sleep(settings.sync_poll_interval)

            # --- Stop heartbeat ---
            if heartbeat_task:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass

            # --- Handle failure ---
            if task.task_status.value == "failure":
                error_msg = (
                    getattr(task, "error_message", None) or "Conversion failed"
                )
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

            # Spool the result to a temp file so we never hold the
            # full serialised payload in memory during delivery.
            scratch_dir = get_scratch()
            result_file = scratch_dir / f"ws_result_{task_id}"

            try:
                if isinstance(task_result.result, ExportResult):
                    from docling.datamodel.service.responses import (
                        ConvertDocumentResponse,
                    )

                    response = ConvertDocumentResponse(
                        document=task_result.result.content,
                        status=task_result.result.status,
                        processing_time=task_result.processing_time,
                        timings=task_result.result.timings,
                        errors=task_result.result.errors,
                    )
                    with open(result_file, "wb") as f:  # noqa: ASYNC230
                        f.write(response.model_dump_json().encode("utf-8"))
                    del response  # free memory before sending
                    content_type = "application/json"
                elif isinstance(task_result.result, ZipArchiveResult):
                    with open(result_file, "wb") as f:  # noqa: ASYNC230
                        f.write(task_result.result.content)
                    content_type = "application/zip"
                else:
                    await websocket.send_text(
                        WsError(
                            error=f"Unsupported result type: "
                            f"{type(task_result.result).__name__}",
                            task_id=task_id,
                        ).model_dump_json()
                    )
                    await websocket.close()
                    return

                del task_result  # free memory before streaming

                await send_chunked_result(
                    websocket,
                    task_id=task_id,
                    result_path=result_file,
                    content_type=content_type,
                )
            finally:
                if result_file.exists():
                    result_file.unlink()

            await websocket.close()

        except WebSocketDisconnect:
            _log.info(
                f"WebSocket disconnected for ws_convert (task_id={task_id})"
            )

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

        except RuntimeError as e:
            # "Unexpected ASGI message after websocket.close" — connection
            # already torn down, nothing we can do.
            _log.warning(f"WebSocket runtime error (task_id={task_id}): {e}")

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


async def _heartbeat_loop(
    websocket,
    orchestrator,
    task_id: str,
    start_time: float,
) -> None:
    """Send periodic heartbeats with queue position until cancelled."""
    from docling_serve.settings import docling_serve_settings as settings

    interval = settings.ws_heartbeat_interval
    while True:
        await asyncio.sleep(interval)
        try:
            position = await orchestrator.get_queue_position(task_id)
            await websocket.send_text(
                WsHeartbeat(
                    task_position=position,
                    elapsed=time.time() - start_time,
                ).model_dump_json()
            )
        except Exception:
            break

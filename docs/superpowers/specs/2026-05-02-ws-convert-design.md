# WebSocket Convert Endpoint Design

**Issue:** [#595 — Synchronous WebSocket convert endpoint](https://github.com/docling-project/docling-serve/issues/595)
**Date:** 2026-05-02

## Problem

The current async conversion workflow requires three separate HTTP/WebSocket connections across different endpoints (submit → poll/ws → fetch result). When session affinity breaks during autoscaling events (e.g., Azure Container Apps adding replicas), status polls and result fetches can hit a replica with no knowledge of the task. This is especially problematic with the local orchestrator, common for GPU inference workloads.

## Solution

A single WebSocket endpoint (`WS /v1/convert/ws`) that handles the entire conversion lifecycle over one persistent connection: submit request, receive progress updates, and get results. The WebSocket connection is pinned to the replica that accepted the handshake, surviving autoscaling events.

## Scope

- Convert operations only (source + file). Chunking endpoints deferred to future work.
- Single file upload per connection. Protocol designed to support multi-file later (`more_files` flag on `upload_end`).
- Works with any orchestrator engine (local, RQ, Ray, KFP) — no runtime restriction.

## Endpoint

```
WS /v1/convert/ws?api_key=SECRET
```

Authentication via `?api_key=` query parameter, matching existing `task_status_ws` pattern. Auth is only enforced when the server has an API key configured.

## Protocol

### Client → Server Messages

| Message Type | Purpose | Fields |
|---|---|---|
| `convert` | Convert from URL(s) | `type`, `sources` (list of HttpSourceRequest), `options` (ConvertDocumentsRequestOptions), `target_type` ("inbody" \| "zip") |
| `upload_start` | Begin file upload | `type`, `filename`, `total_bytes`, `content_type`, `chunks`, `options`, `target_type` |
| *(binary frames)* | File data | Raw bytes, ~1MB per frame |
| `upload_end` | Finalize upload | `type`, `sha256` |

### Server → Client Messages

| Message Type | Purpose | Fields |
|---|---|---|
| `connected` | Greeting on connect | `type`, `queue_length` |
| `status` | Progress/queue update | `type`, `task_id`, `task_status`, `task_position` (int \| null), `progress` (float \| null), `message` |
| `heartbeat` | Keepalive + queue position | `type`, `task_position` (int \| null), `timestamp` |
| `result_start` | Begin chunked result | `type`, `task_id`, `total_bytes`, `content_type`, `chunks` |
| *(binary frames)* | Result data | Raw bytes, ~1MB per frame |
| `result_end` | Finalize result | `type`, `task_id`, `sha256` |
| `error` | Error occurred | `type`, `error` (string), `task_id` (optional) |

### URL Conversion Flow

```
Client                              Server
  |---- WS handshake (/v1/convert/ws?api_key=...) ---->|
  |<--- connected {queue_length: 3} -------------------|
  |---- convert {sources, options, target_type} ------->|
  |<--- status {PENDING, position: 4} -----------------|
  |<--- heartbeat {position: 4} -----------------------|  (every 30s)
  |<--- status {PENDING, position: 3} -----------------|
  |<--- status {PROCESSING, progress: 0.1} ------------|
  |<--- status {PROCESSING, progress: 0.5} ------------|
  |<--- result_start {total_bytes, content_type, chunks}|
  |<--- [binary frame 1] ------------------------------|
  |<--- [binary frame N] ------------------------------|
  |<--- result_end {sha256} ----------------------------|
  |---- connection closed ------------------------------|
```

### File Upload Flow

```
Client                              Server
  |---- WS handshake (/v1/convert/ws?api_key=...) ---->|
  |<--- connected {queue_length: 3} -------------------|
  |---- upload_start {filename, total_bytes, ...} ----->|
  |---- [binary frame 1] ----------------------------->|
  |---- [binary frame N] ----------------------------->|
  |---- upload_end {sha256} --------------------------->|
  |<--- status {PENDING, position: 4} -----------------|
  |     ... (same as URL flow from here) ...           |
  |<--- result_start {total_bytes, ...} ---------------|
  |<--- [binary frame 1] ------------------------------|
  |<--- [binary frame N] ------------------------------|
  |<--- result_end {sha256} ----------------------------|
  |---- connection closed ------------------------------|
```

### Result Delivery

All results use chunked binary transfer:
- **ExportResult** (InBody): serialized as JSON bytes, `content_type: "application/json"`
- **ZipArchiveResult** (Zip): raw zip bytes, `content_type: "application/zip"`
- Binary frames are ~1MB each
- SHA-256 checksum in `result_end` for integrity verification

## Module Structure

### New file: `docling_serve/ws_convert.py`

Contains:
- Pydantic models for WebSocket message types (client and server)
- `register_ws_convert(app, service_policy, enque_source, enque_file, prepare_convert_request, prepare_convert_options)` — registers the endpoint, captures dependencies via closure
- `_handle_ws_convert(websocket, orchestrator, api_key)` — main handler
- Private helpers:
  - `_receive_upload(websocket)` — writes binary frames to temp file on disk, verifies SHA-256, returns file path and metadata (filename, content_type). The handler then constructs a `DocumentStream` from the temp file for `_enque_file()`.
  - `_send_chunked_result(websocket, task_result)` — sends `result_start` → binary frames → `result_end`
  - `_heartbeat_loop(websocket, orchestrator, task_id)` — asyncio task sending heartbeats every 30s, cancelled when result delivery starts

### Changes to `app.py`

Minimal — import and call `register_ws_convert(app, service_policy, ...)` inside `create_app()` after existing endpoint definitions. Internal helpers (`_enque_source`, `_enque_file`, `_prepare_convert_request`, `_prepare_convert_options`) are passed as arguments.

### Changes to `websocket_notifier.py`

None. The new endpoint registers its WebSocket in `notifier.task_subscribers[task_id]` using the existing mechanism.

## Data Flow

```
WS /v1/convert/ws
    │
    ├─ URL request: parse convert message → _prepare_convert_request() → _enque_source()
    │
    └─ File request: receive binary → write to disk → _prepare_convert_options() → _enque_file()
            │
            ▼
    orchestrator.enqueue()          ← same as REST
            │
            ▼
    register in notifier.task_subscribers[task_id]
            │
            ▼
    notifier pushes status/queue updates → send as status messages
            │
            ▼
    task completes → orchestrator.task_result()
            │
            ▼
    serialize result → result_start → binary chunks → result_end
            │
            ▼
    close connection
```

## Error Handling

| Scenario | When | Response |
|---|---|---|
| Auth failure | Handshake | `error` message + close (only when API key configured) |
| Invalid first message | After connect | `error` message + close |
| Invalid JSON / unknown type | Any client message | `error` message + close |
| SHA-256 mismatch on upload | After `upload_end` | `error` message, clean up temp file, close |
| Upload exceeds max file size | At `upload_start` | `error` message + close (reject early based on declared `total_bytes`) |
| Policy validation failure | After parsing request | `error` message + close |
| Enqueue failure (backpressure) | After enqueue attempt | `error` message + close |
| Task failure | During processing | `status` with `task_status: "FAILURE"` and error in `message`, close |
| Client disconnects | Any time | Server logs, task continues in orchestrator, temp files cleaned up |
| Server shutdown | Any time | WebSocket closed by framework |

Principles:
- Fail fast, fail clearly — every error sends an `error` message before closing
- No partial state — if upload validation fails, temp files are cleaned up
- Tasks are fire-and-forget — once enqueued, client disconnect doesn't cancel the task
- One error = connection closed — client reconnects and retries

## Configuration

### New setting

| Setting | Env var | Default | Purpose |
|---|---|---|---|
| `ws_heartbeat_interval` | `DOCLING_SERVE_WS_HEARTBEAT_INTERVAL` | `30` (seconds) | Interval between heartbeat messages |

### Existing settings that apply

- `api_key` — auth enforcement
- `max_num_pages`, `max_file_size` — enforced via policy validation; `max_file_size` also checked at `upload_start` for early rejection
- `result_removal_delay`, `single_use_results` — handled by orchestrator after result fetch
- `scratch_path` — temp file location for uploads

## Testing

### Test file: `tests/test_ws_convert.py`

**URL conversion tests:**
- Connect, receive `connected`, send `convert`, receive status updates, receive chunked result, verify SHA-256
- Connect with bad API key (when configured) — expect error + close
- Send invalid JSON — expect error + close
- Send unknown message type — expect error + close

**File upload tests:**
- Connect, send `upload_start` → binary frames → `upload_end`, receive status updates, receive chunked result, verify SHA-256
- SHA-256 mismatch on upload — expect error + close
- `total_bytes` exceeds max file size — expect early rejection

**Heartbeat tests:**
- Verify heartbeats arrive during idle periods
- Verify heartbeats include `task_position`

**Edge cases:**
- Client disconnects mid-upload — verify temp file cleanup
- Client disconnects mid-conversion — verify task still completes
- Large result chunking — verify reassembled bytes match expected output

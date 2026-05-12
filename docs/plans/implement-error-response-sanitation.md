# Error Detail Sanitization With Debug Override

## Summary
- Add a canonical server flag, `DOCLING_SERVE_DEBUG_ERROR_DETAILS`, default `false`.
- When the flag is `false`, suppress infrastructure exception details from public responses and callbacks, while keeping raw exceptions in logs.
- When the flag is `true`, allow current exception detail to propagate for debugging.
- Preserve intentionally public, explicit error messages that are already safe: policy validation, timeouts, result-not-found, backpressure, dispatcher unavailable, watchdog/orphan-state messages.

## Implementation Changes
- Add `debug_error_details: bool = False` to `docling_serve` settings and document `DOCLING_SERVE_DEBUG_ERROR_DETAILS` in [docs/configuration.md](docs/configuration.md).
- Thread that flag from `docling-serve` into jobkit orchestrator configs in [docling_serve/orchestrator_factory.py](docling_serve/orchestrator_factory.py).
- Extend jobkit config objects so both Ray and RQ paths receive the flag programmatically. `RayOrchestratorConfig` should carry it directly; `RQOrchestratorConfig` should gain the same field.
- Add one shared jobkit helper module for public error shaping and use it from the exception-ingestion points.

## Helper Responsibilities
- `build_public_task_error(exc, debug_enabled) -> str`
  - Used when an infrastructure exception is being copied into `Task.error_message` or a pub/sub task update.
  - In debug mode, return `str(exc) or exc.__class__.__name__`.
  - In non-debug mode, return one stable generic message such as `Internal processing error.`
  - Never log; formatting only.

- `build_public_error_item(exc, debug_enabled) -> ErrorItem`
  - Used when an infrastructure exception is being turned into a document-scoped `ErrorItem`.
  - In debug mode, preserve current behavior: exception class name in `module_name`, exception text in `error_message`.
  - In non-debug mode, emit a safe synthetic item, for example `module_name="internal_error"` and `error_message="Internal document processing error."`
  - Always produce a schema-valid `ErrorItem`; no `None` fields.

- `render_public_error_list(errors, debug_enabled) -> str | None`
  - Used only for callback/reporting string fields that currently do `str(exportable_document.errors)`.
  - Accepts already-public `ErrorItem`s and renders them into a readable string without Python repr output.
  - In non-debug mode, join the public `error_message` values only.
  - In debug mode, may include `module_name` prefixes, but still as deliberate formatting rather than raw list repr.
  - Returns `None` when the list is empty.

- `build_public_http_detail(exc, debug_enabled, fallback_message: str) -> str`
  - Used in `docling-serve` service-layer `HTTPException(detail=...)` sites that currently use `str(exc)`.
  - In debug mode, return `str(exc) or fallback_message`.
  - In non-debug mode, return the supplied safe fallback.
  - Keeps sanitization policy for HTTP error bodies separate from orchestration/task models.

## Ingestion Points
- Use `build_public_error_item(...)` at Ray slice failure construction in `serve_deployment.py`.
- Use `build_public_task_error(...)` at:
  - Ray coordinator failure terminalization/publication in `serve_deployment.py`
  - Ray dispatcher failure terminalization/publication in `dispatcher.py`
  - RQ worker failure publication in `rq/worker.py`
- Use `render_public_error_list(...)` in jobkit callback/reporting code:
  - `FailedDocsItem.error` in `convert/results.py` and `convert/chunking.py`
  - `DocumentCompletedItem.error` in `convert/results.py` and `convert/chunking.py`
- Use `build_public_http_detail(...)` in `docling-serve` for raw `str(exc)` HTTP detail sites such as readiness and progress validation.
- Leave explicit safe messages authored directly in app code unchanged.

## Public Interfaces
- New env var: `DOCLING_SERVE_DEBUG_ERROR_DETAILS=false`.
- New internal config field on jobkit Ray/RQ configs: `debug_error_details: bool`.
- No response schema changes. Existing fields remain, but their values become sanitized by default.
- No origin-tagging/data-model extension in v1. This pass fixes known infrastructure injection points instead of retrofitting provenance onto all `ErrorItem`s.

## Test Plan
- `docling-serve` unit tests:
  - readiness returns generic 503 detail by default and raw detail when debug flag is on
  - progress callback validation returns generic 400 detail by default and raw detail when debug flag is on
  - async status/websocket responses expose generic `error_message` by default and raw text when debug flag is on
  - `DispatcherUnavailableError` and other explicit safe messages remain unchanged
- `docling-jobkit` unit tests:
  - Ray slice failure builds sanitized `ErrorItem` by default and raw `module_name`/message when debug flag is on
  - Ray dispatcher/coordinator failure publication stores sanitized `error_message` by default and raw text when debug flag is on
  - RQ worker failure publication does the same
  - callback error rendering no longer emits Python list/dataclass reprs
- Cross-path behavior tests:
  - library-generated document errors still pass through unchanged with debug off
  - infrastructure-origin failures surface as generic messages in convert/chunk result errors, async task status, websocket updates, and callback payloads

## Assumptions
- This pass addresses the audited, known exception-stringification paths and does not add heuristic post-hoc scrubbing of arbitrary `ConversionResult.errors`.
- Raw exception detail remains available in server logs regardless of the flag.
- `DOCLING_SERVE_DEBUG_ERROR_DETAILS` is the canonical deployment control; standalone jobkit callers can set the config field directly if needed.

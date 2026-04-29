"""Instrumented wrapper for RQ job functions with OpenTelemetry tracing."""

import hashlib
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from rq import get_current_job

from docling_jobkit.convert.manager import DoclingConverterManager
from docling_jobkit.datamodel.task import Task
from docling_jobkit.orchestrators.rq.orchestrator import RQOrchestratorConfig
from docling_jobkit.orchestrators.rq.worker import _run_docling_task

from docling_serve.rq_instrumentation import extract_trace_context

logger = logging.getLogger(__name__)


def instrumented_docling_task(
    task_data: dict,
    conversion_manager: DoclingConverterManager,
    orchestrator_config: RQOrchestratorConfig,
    scratch_dir: Path,
):
    """
    Instrumented wrapper for docling_task that extracts and activates trace context.

    This function extracts the OpenTelemetry trace context from the RQ job metadata
    and activates it before calling the actual task function, enabling end-to-end
    distributed tracing from API to worker. It also adds detailed sub-spans for each
    processing stage to identify performance bottlenecks.
    """
    job = get_current_job()
    assert job is not None

    task = Task.model_validate(task_data)
    task_id = task.task_id

    # Extract parent trace context from job metadata
    parent_context = extract_trace_context(job) if job else None

    # Get tracer
    tracer = trace.get_tracer(__name__)

    # Create main job span with parent context (this creates the link to the API trace)
    with tracer.start_as_current_span(
        "rq.job.docling_task",
        context=parent_context,
        kind=SpanKind.CONSUMER,
    ) as span:
        try:
            # Add job attributes
            span.set_attribute("rq.job.id", job.id)
            if job.func_name:
                span.set_attribute("rq.job.func_name", job.func_name)
            span.set_attribute("rq.queue.name", job.origin)

            # Add task attributes
            span.set_attribute("docling.task.id", task_id)
            span.set_attribute("docling.task.type", str(task.task_type.value))
            span.set_attribute("docling.task.num_sources", len(task.sources))

            logger.info(
                f"Executing docling_task {task_id} with "
                f"trace_id={span.get_span_context().trace_id:032x} "
                f"span_id={span.get_span_context().span_id:016x}"
            )

            phase_state: dict[str, Any] = {
                "num_sources": len(task.sources),
                "has_headers": False,
            }

            @contextmanager
            def phase_cm(name: str):
                with tracer.start_as_current_span(name) as phase_span:
                    if name == "convert_documents":
                        phase_span.set_attribute(
                            "num_sources", phase_state["num_sources"]
                        )
                        phase_span.set_attribute(
                            "has_headers", phase_state["has_headers"]
                        )
                    elif name == "process_results":
                        phase_span.set_attribute("task_type", str(task.task_type.value))
                    yield

            def on_source_prepared(
                idx: int,
                source: Any,
                info: dict[str, str],
                raw_bytes: Any = None,
            ) -> None:
                event_info = dict(info)
                if info["type"] == "FileSource" and raw_bytes is not None:
                    file_hash = hashlib.md5(
                        raw_bytes, usedforsecurity=False
                    ).hexdigest()[:12]
                    logger.info(
                        f"FileSource {idx}: filename={source.filename}, "
                        f"base64_len={len(source.base64_string)}, "
                        f"decoded_size={len(raw_bytes)}, md5={file_hash}"
                    )
                    event_info["size"] = str(len(raw_bytes))
                    event_info["md5"] = file_hash

                trace.get_current_span().add_event(
                    f"source_{idx}_prepared",
                    event_info,
                )

            def on_sources_prepared(
                source_info: list[dict[str, str]],
                num_sources: int,
                has_headers: bool,
            ) -> None:
                phase_state["num_sources"] = num_sources
                phase_state["has_headers"] = has_headers
                trace.get_current_span().set_attribute("num_sources", num_sources)
                source_names = ", ".join(
                    f"{s['type']}={s.get('name') or s.get('filename') or s.get('url', 'unknown')}"
                    for s in source_info
                )
                logger.info(
                    f"Task {task_id} processing {num_sources} source(s): {source_names}"
                )

            def on_result_stored(result_key: str, result_size_bytes: int) -> None:
                store_span = trace.get_current_span()
                store_span.set_attribute("result_size_bytes", result_size_bytes)
                store_span.set_attribute("result_key", result_key)

            def on_failure(
                _task: Task,
                exc: Exception,
                source_info: list[dict[str, str]],
            ) -> None:
                source_context = "N/A"
                if source_info:
                    source_context = ", ".join(
                        f"{s['type']}={s.get('name') or s.get('filename') or s.get('url', 'unknown')}"
                        for s in source_info
                    )
                logger.error(
                    f"Docling task {task_id} failed: {exc}. Sources: {source_context}",
                    exc_info=True,
                )

            result_key = _run_docling_task(
                task,
                conversion_manager,
                orchestrator_config,
                scratch_dir,
                phase_cm=phase_cm,
                on_source_prepared=on_source_prepared,
                on_sources_prepared=on_sources_prepared,
                on_result_stored=on_result_stored,
                on_failure=on_failure,
            )

            # Mark span as successful
            span.set_status(Status(StatusCode.OK))
            logger.info(f"Docling task {task_id} completed successfully")

            return result_key

        except Exception as e:
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

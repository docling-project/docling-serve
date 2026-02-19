"""Instrumented wrapper for RQ job functions with OpenTelemetry tracing."""

import base64
import hashlib
import logging
import shutil
from pathlib import Path
from typing import Any, Union

import msgpack
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from rq import get_current_job

from docling.datamodel.base_models import DocumentStream
from docling_jobkit.convert.chunking import process_chunk_results
from docling_jobkit.convert.manager import DoclingConverterManager
from docling_jobkit.convert.results import process_export_results
from docling_jobkit.datamodel.http_inputs import FileSource, HttpSource
from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus, TaskType
from docling_jobkit.orchestrators.rq.orchestrator import (
    RQOrchestratorConfig,
    _TaskUpdate,
)
from docling_jobkit.orchestrators.rq.worker import make_msgpack_safe

from docling_serve.rq_instrumentation import extract_trace_context

logger = logging.getLogger(__name__)


def instrumented_docling_task(  # noqa: C901
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

    conn = job.connection
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

            # Notify task started
            with tracer.start_as_current_span("notify.task_started"):
                conn.publish(
                    orchestrator_config.sub_channel,
                    _TaskUpdate(
                        task_id=task_id,
                        task_status=TaskStatus.STARTED,
                    ).model_dump_json(),
                )

            workdir = scratch_dir / task_id

            # Prepare sources with detailed tracing
            with tracer.start_as_current_span("prepare_sources") as prep_span:
                convert_sources: list[Union[str, DocumentStream]] = []
                headers: dict[str, Any] | None = None
                source_info: list[dict[str, str]] = []

                for idx, source in enumerate(task.sources):
                    if isinstance(source, DocumentStream):
                        convert_sources.append(source)
                        info = {"type": "DocumentStream", "name": source.name}
                        source_info.append(info)
                        prep_span.add_event(f"source_{idx}_prepared", info)
                    elif isinstance(source, FileSource):
                        decoded_bytes = base64.b64decode(source.base64_string)
                        file_hash = hashlib.md5(decoded_bytes).hexdigest()[:12]
                        logger.info(
                            f"FileSource {idx}: filename={source.filename}, "
                            f"base64_len={len(source.base64_string)}, "
                            f"decoded_size={len(decoded_bytes)}, md5={file_hash}"
                        )
                        doc_stream = source.to_document_stream()
                        convert_sources.append(doc_stream)
                        info = {
                            "type": "FileSource",
                            "filename": source.filename,
                            "size": str(len(decoded_bytes)),
                            "md5": file_hash,
                        }
                        source_info.append(info)
                        prep_span.add_event(f"source_{idx}_prepared", info)
                    elif isinstance(source, HttpSource):
                        convert_sources.append(str(source.url))
                        info = {"type": "HttpSource", "url": str(source.url)}
                        source_info.append(info)
                        if headers is None and source.headers:
                            headers = source.headers
                        prep_span.add_event(f"source_{idx}_prepared", info)

                prep_span.set_attribute("num_sources", len(convert_sources))

                source_names = ", ".join(
                    f"{s['type']}={s.get('name') or s.get('filename') or s.get('url', 'unknown')}"
                    for s in source_info
                )
                logger.info(
                    f"Task {task_id} processing {len(convert_sources)} source(s): {source_names}"
                )

            if not conversion_manager:
                raise RuntimeError("No converter")
            if not task.convert_options:
                raise RuntimeError("No conversion options")

            # Document conversion with detailed tracing
            with tracer.start_as_current_span("convert_documents") as conv_span:
                conv_span.set_attribute("num_sources", len(convert_sources))
                conv_span.set_attribute("has_headers", headers is not None)

                conv_results = conversion_manager.convert_documents(
                    sources=convert_sources,
                    options=task.convert_options,
                    headers=headers,
                )

            # Result processing with detailed tracing
            with tracer.start_as_current_span("process_results") as proc_span:
                proc_span.set_attribute("task_type", str(task.task_type.value))

                try:
                    if task.task_type == TaskType.CONVERT:
                        with tracer.start_as_current_span("process_export_results"):
                            processed_results = process_export_results(
                                task=task,
                                conv_results=conv_results,
                                work_dir=workdir,
                            )
                    elif task.task_type == TaskType.CHUNK:
                        with tracer.start_as_current_span("process_chunk_results"):
                            processed_results = process_chunk_results(
                                task=task,
                                conv_results=conv_results,
                                work_dir=workdir,
                            )
                except Exception as proc_error:
                    source_names = ", ".join(
                        f"{s['type']}={s.get('name') or s.get('filename') or s.get('url', 'unknown')}"
                        for s in source_info
                    )
                    logger.error(
                        f"Task {task_id} processing failed. "
                        f"Sources: {source_names}. "
                        f"Error: {proc_error}"
                    )
                    raise

            # Serialize and store results
            with tracer.start_as_current_span("serialize_and_store") as store_span:
                safe_data = make_msgpack_safe(processed_results.model_dump())
                packed = msgpack.packb(safe_data, use_bin_type=True)
                store_span.set_attribute("result_size_bytes", len(packed))

                result_key = f"{orchestrator_config.results_prefix}:{task_id}"
                conn.setex(result_key, orchestrator_config.results_ttl, packed)
                store_span.set_attribute("result_key", result_key)

            # Notify task success
            with tracer.start_as_current_span("notify.task_success"):
                conn.publish(
                    orchestrator_config.sub_channel,
                    _TaskUpdate(
                        task_id=task_id,
                        task_status=TaskStatus.SUCCESS,
                        result_key=result_key,
                    ).model_dump_json(),
                )

            # Clean up
            with tracer.start_as_current_span("cleanup"):
                if workdir.exists():
                    shutil.rmtree(workdir)

            # Mark span as successful
            span.set_status(Status(StatusCode.OK))
            logger.info(f"Docling task {task_id} completed successfully")

            return result_key

        except Exception as e:
            # Notify task failure
            try:
                conn.publish(
                    orchestrator_config.sub_channel,
                    _TaskUpdate(
                        task_id=task_id,
                        task_status=TaskStatus.FAILURE,
                        error_message=str(e),
                    ).model_dump_json(),
                )
            except Exception:
                pass

            # Clean up on error
            workdir = scratch_dir / task_id
            if workdir.exists():
                try:
                    shutil.rmtree(workdir)
                except Exception:
                    pass

            # Record exception and mark span as failed
            source_context = "N/A"
            if "source_info" in locals():
                source_context = ", ".join(
                    f"{s['type']}={s.get('name') or s.get('filename') or s.get('url', 'unknown')}"
                    for s in source_info
                )
            logger.error(
                f"Docling task {task_id} failed: {e}. Sources: {source_context}",
                exc_info=True,
            )
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

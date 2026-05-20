"""Instrumented wrapper for RQ job functions with OpenTelemetry tracing."""

import logging
from pathlib import Path

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
    job = get_current_job()
    assert job is not None

    task = Task.model_validate(task_data)
    task_id = task.task_id

    parent_context = extract_trace_context(job) if job else None
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span(
        "rq.job.docling_task",
        context=parent_context,
        kind=SpanKind.CONSUMER,
    ) as span:
        try:
            span.set_attribute("rq.job.id", job.id)
            if job.func_name:
                span.set_attribute("rq.job.func_name", job.func_name)
            span.set_attribute("rq.queue.name", job.origin)
            span.set_attribute("docling.task.id", task_id)
            span.set_attribute("docling.task.type", str(task.task_type.value))
            span.set_attribute("docling.task.num_sources", len(task.sources))

            logger.info(
                f"Executing docling_task {task_id} with "
                f"trace_id={span.get_span_context().trace_id:032x} "
                f"span_id={span.get_span_context().span_id:016x}"
            )

            result_key = _run_docling_task(
                task,
                conversion_manager,
                orchestrator_config,
                scratch_dir,
            )

            span.set_status(Status(StatusCode.OK))
            logger.info(f"Docling task {task_id} completed successfully")

            return result_key

        except Exception as e:
            logger.error(f"Docling task {task_id} failed: {e}", exc_info=True)
            span.record_exception(e)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            raise

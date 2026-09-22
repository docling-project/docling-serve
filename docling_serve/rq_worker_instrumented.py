"""Instrumented RQ worker with OpenTelemetry tracing support."""

import logging
from datetime import datetime, timezone
from pathlib import Path

from opentelemetry import metrics, trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from docling_jobkit.convert.manager import (
    DoclingConverterManagerConfig,
)
from docling_jobkit.orchestrators.rq.orchestrator import RQOrchestratorConfig
from docling_jobkit.orchestrators.rq.worker import CustomRQWorker

from docling_serve.rq_instrumentation import extract_trace_context

logger = logging.getLogger(__name__)


class InstrumentedRQWorker(CustomRQWorker):
    """RQ Worker with OpenTelemetry tracing instrumentation."""

    def __init__(
        self,
        *args,
        orchestrator_config: RQOrchestratorConfig,
        cm_config: DoclingConverterManagerConfig,
        scratch_dir: Path,
        **kwargs,
    ):
        super().__init__(
            *args,
            orchestrator_config=orchestrator_config,
            cm_config=cm_config,
            scratch_dir=scratch_dir,
            **kwargs,
        )
        self.tracer = trace.get_tracer(__name__)
        self.queue_wait_duration = metrics.get_meter(__name__).create_histogram(
            "docling.rq.queue.wait.duration",
            unit="s",
            description="Time from enqueue to worker execution entry for each RQ job attempt",
            explicit_bucket_boundaries_advisory=(
                0,
                0.1,
                0.5,
                1,
                2.5,
                5,
                10,
                30,
                60,
                120,
                300,
                600,
                1800,
                3600,
            ),
        )

    def perform_job(self, job, queue):
        """
        Perform job with distributed tracing support.

        This extracts the trace context from the job metadata and creates
        a span that continues the trace from the API request.
        """
        if job.enqueued_at is not None:
            self.queue_wait_duration.record(
                max(
                    0.0, (datetime.now(timezone.utc) - job.enqueued_at).total_seconds()
                ),
                attributes={"rq.queue.name": queue.name},
            )

        # Extract parent trace context from job metadata
        parent_context = extract_trace_context(job)

        # Create span name from job function
        func_name = job.func_name if hasattr(job, "func_name") else "unknown"
        span_name = f"rq.job.{func_name}"

        # Start span with parent context
        with self.tracer.start_as_current_span(
            span_name,
            context=parent_context,
            kind=SpanKind.CONSUMER,
        ) as span:
            try:
                # Add job attributes to span
                span.set_attribute("rq.job.id", job.id)
                span.set_attribute("rq.job.func_name", func_name)
                span.set_attribute("rq.queue.name", queue.name)

                if hasattr(job, "description") and job.description:
                    span.set_attribute("rq.job.description", job.description)

                if hasattr(job, "timeout") and job.timeout:
                    span.set_attribute("rq.job.timeout", job.timeout)

                # Add job kwargs info
                if hasattr(job, "kwargs") and job.kwargs:
                    # Add conversion manager before executing
                    job.kwargs["conversion_manager"] = self.conversion_manager
                    job.kwargs["orchestrator_config"] = self.orchestrator_config
                    job.kwargs["scratch_dir"] = self.scratch_dir

                    # Log task info if available
                    task_type = job.kwargs.get("task_type")
                    if task_type:
                        span.set_attribute("docling.task.type", str(task_type))

                    sources = job.kwargs.get("sources", [])
                    if sources:
                        span.set_attribute("docling.task.num_sources", len(sources))

                logger.info(
                    f"Executing job {job.id} with trace_id={span.get_span_context().trace_id:032x}"
                )

                # Execute the actual job
                result = super().perform_job(job, queue)

                # Mark span as successful
                span.set_status(Status(StatusCode.OK))
                logger.debug(f"Job {job.id} completed successfully")

                return result

            except Exception as e:
                # Record exception and mark span as failed
                logger.error(f"Job {job.id} failed: {e}", exc_info=True)
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

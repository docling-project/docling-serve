"""RQ instrumentation for distributed tracing across API and workers."""

import functools
import logging
from collections.abc import Callable
from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import SpanKind, Status, StatusCode

logger = logging.getLogger(__name__)

# Global tracer instance
_tracer = trace.get_tracer(__name__)


def get_rq_tracer() -> trace.Tracer:
    """Get the RQ tracer instance."""
    return _tracer


def inject_trace_context(job_kwargs: dict[str, Any]) -> dict[str, Any]:
    """
    Inject current trace context into RQ job kwargs.

    This is called when enqueueing a job to propagate the trace context
    from the API request to the RQ worker.

    Args:
        job_kwargs: Job keyword arguments

    Returns:
        Modified job kwargs with trace context in metadata
    """
    # Create carrier dict to hold trace context
    carrier: dict[str, str] = {}

    # Inject current context into carrier
    inject(carrier)

    # Store carrier in job metadata
    if carrier:
        job_kwargs.setdefault("meta", {})
        job_kwargs["meta"]["otel_context"] = carrier
        logger.debug(f"Injected trace context into job: {carrier}")

    return job_kwargs


def extract_trace_context(job) -> Context | None:
    """
    Extract trace context from RQ job metadata.

    This is called in the worker to continue the trace that was started
    in the API.

    Args:
        job: RQ Job instance

    Returns:
        OpenTelemetry context extracted from job metadata, or None if not found
    """
    carrier = {}

    # Extract carrier from job metadata
    if hasattr(job, "meta") and job.meta:
        carrier = job.meta.get("otel_context", {})
        logger.debug(f"Extracted trace context from job: {carrier}")

    # Extract context from carrier
    return extract(carrier) if carrier else None


def instrument_rq_job(func: Callable) -> Callable:
    """
    Decorator to instrument RQ job functions with tracing.

    This creates a span for the job execution and links it to the parent
    trace from the API request.

    Args:
        func: Job function to instrument

    Returns:
        Instrumented function
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        # Get job instance (RQ passes it as first arg in some contexts)
        job = kwargs.get("job")

        # Extract trace context from job
        parent_context = extract_trace_context(job) if job else None

        # Create span with parent context
        tracer = get_rq_tracer()
        span_name = f"rq.job.{func.__name__}"

        with tracer.start_as_current_span(
            span_name,
            context=parent_context,
            kind=SpanKind.CONSUMER,
        ) as span:
            try:
                # Add job metadata as span attributes
                if job:
                    span.set_attribute("rq.job.id", job.id)
                    span.set_attribute("rq.job.func_name", job.func_name)
                    span.set_attribute("rq.queue.name", job.origin)
                    if hasattr(job, "description"):
                        span.set_attribute("rq.job.description", job.description)

                # Execute the actual job function
                result = func(*args, **kwargs)

                # Mark span as successful
                span.set_status(Status(StatusCode.OK))
                return result

            except Exception as e:
                # Record exception and mark span as failed
                span.record_exception(e)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                raise

    return wrapper


def setup_rq_worker_instrumentation():
    """
    Set up OpenTelemetry instrumentation for RQ workers.

    This should be called when starting an RQ worker to ensure traces
    are properly initialized in the worker process.
    """
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    # Check if tracer provider is already set
    if not isinstance(trace.get_tracer_provider(), TracerProvider):
        logger.info("Setting up OpenTelemetry for RQ worker")

        # Create resource with service name
        resource = Resource(attributes={SERVICE_NAME: "docling-serve-worker"})

        # Set up trace provider
        trace_provider = TracerProvider(resource=resource)
        trace_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(trace_provider)

        # Update global tracer
        global _tracer
        _tracer = trace.get_tracer(__name__)

        logger.info("OpenTelemetry setup complete for RQ worker")
    else:
        logger.debug("OpenTelemetry already configured for RQ worker")


def wrap_rq_queue_for_tracing(rq_queue):
    """
    Wrap RQ queue's enqueue method to inject trace context into jobs.

    This monkey-patches the queue's enqueue method to automatically inject
    the current trace context into job metadata.

    Args:
        rq_queue: RQ Queue instance to wrap
    """
    original_enqueue = rq_queue.enqueue

    def traced_enqueue(*args, **kwargs):
        """Wrapped enqueue that injects trace context."""
        # Get or create meta dict for the job
        meta = kwargs.get("meta", {})

        # Inject trace context into meta
        carrier: dict[str, str] = {}
        inject(carrier)

        if carrier:
            meta["otel_context"] = carrier
            kwargs["meta"] = meta
            logger.debug(f"Injected trace context into RQ job: {carrier}")

        # Call original enqueue
        return original_enqueue(*args, **kwargs)

    # Replace enqueue method
    rq_queue.enqueue = traced_enqueue
    logger.info("RQ queue wrapped for distributed tracing")

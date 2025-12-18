"""OpenTelemetry instrumentation for docling-serve with metrics and traces."""

import logging

from opentelemetry import metrics, trace
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.prometheus import PrometheusMetricReader
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import REGISTRY
from redis import Redis

from docling_serve.rq_metrics_collector import RQCollector

logger = logging.getLogger(__name__)


def setup_otel_instrumentation(
    app,
    service_name: str = "docling-serve",
    enable_metrics: bool = True,
    enable_traces: bool = True,
    enable_prometheus: bool = True,
    enable_otlp_metrics: bool = False,
    redis_url: str | None = None,
):
    """
    Set up OpenTelemetry instrumentation for FastAPI app.

    Args:
        app: FastAPI application instance
        service_name: Service name for OTEL resource
        enable_metrics: Enable OTEL metrics
        enable_traces: Enable OTEL traces
        enable_prometheus: Enable Prometheus metrics export
        enable_otlp_metrics: Enable OTLP metrics export (for OTEL collector)
        redis_url: Redis URL for RQ metrics (if using RQ engine)
    """
    resource = Resource(attributes={SERVICE_NAME: service_name})

    # Setup traces
    if enable_traces:
        logger.info("Setting up OpenTelemetry traces")
        trace_provider = TracerProvider(resource=resource)
        trace_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(trace_provider)

    # Setup metrics
    if enable_metrics:
        logger.info("Setting up OpenTelemetry metrics")
        metric_readers: list = []

        # Prometheus metrics reader (for scraping endpoint)
        if enable_prometheus:
            logger.info("Enabling Prometheus metrics export")
            prometheus_reader = PrometheusMetricReader()
            metric_readers.append(prometheus_reader)

        # OTLP metrics exporter (for OTEL collector)
        if enable_otlp_metrics:
            logger.info("Enabling OTLP metrics export")
            otlp_reader = PeriodicExportingMetricReader(OTLPMetricExporter())
            metric_readers.append(otlp_reader)

        if metric_readers:
            meter_provider = MeterProvider(
                resource=resource,
                metric_readers=metric_readers,
            )
            metrics.set_meter_provider(meter_provider)

    # Instrument FastAPI
    logger.info("Instrumenting FastAPI with OpenTelemetry")
    FastAPIInstrumentor.instrument_app(app)

    # Register RQ metrics if Redis URL is provided
    if redis_url and enable_prometheus:
        logger.info(f"Registering RQ metrics collector for Redis at {redis_url}")
        connection = Redis.from_url(redis_url)
        REGISTRY.register(RQCollector(connection))


def get_metrics_endpoint_content():
    """
    Get Prometheus metrics content for /metrics endpoint.

    Returns:
        Prometheus-formatted metrics content
    """
    from prometheus_client import REGISTRY, generate_latest

    return generate_latest(REGISTRY)

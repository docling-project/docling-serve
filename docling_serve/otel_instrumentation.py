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
from opentelemetry.sdk.trace.sampling import Decision, Sampler, SamplingResult
from opentelemetry.trace import SpanKind
from opentelemetry.util.types import Attributes
from prometheus_client import REGISTRY, start_http_server
from redis import Redis

from docling_serve.ray_metrics_collector import RayCollector
from docling_serve.rq_metrics_collector import RQCollector

logger = logging.getLogger(__name__)


FILTERED_PATHS = {"/metrics", "/health", "/healthz", "/ready", "/readyz", "/livez"}


class HealthMetricsFilterSampler(Sampler):
    """
    Sampler that filters out traces for health and metrics endpoints.

    Drops spans for /metrics, /health, /healthz, /readyz, /livez regardless
    of query parameters. All other endpoints are sampled normally (always on).
    """

    def should_sample(
        self,
        parent_context,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Attributes | None = None,
        links=None,
        trace_state=None,
    ) -> SamplingResult:
        if attributes:
            http_target = attributes.get("http.target") or attributes.get("url.path")
            if http_target:
                path = str(http_target).split("?")[0]
                if path in FILTERED_PATHS:
                    return SamplingResult(Decision.DROP)

        return SamplingResult(Decision.RECORD_AND_SAMPLE)

    def get_description(self) -> str:
        """Return description of the sampler."""
        return (
            "HealthMetricsFilterSampler: drops traces for health and metrics endpoints"
        )


def setup_otel_instrumentation(
    app,
    service_name: str = "docling-serve",
    enable_metrics: bool = True,
    enable_traces: bool = True,
    enable_prometheus: bool = True,
    enable_otlp_metrics: bool = False,
    redis_url: str | None = None,
    metrics_port: int | None = None,
    ray_redis_manager=None,
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
        metrics_port: If set, start a separate HTTP server on this port for /metrics
        ray_redis_manager: RedisStateManager instance for Ray metrics (if using Ray engine)
    """
    resource = Resource(attributes={SERVICE_NAME: service_name})

    # Setup traces
    if enable_traces:
        logger.info("Setting up OpenTelemetry traces with health/metrics filtering")
        sampler = HealthMetricsFilterSampler()
        trace_provider = TracerProvider(resource=resource, sampler=sampler)
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

        if metrics_port:
            try:
                start_http_server(metrics_port)
                logger.info(f"Serving metrics on port {metrics_port}")
            except OSError as e:
                raise RuntimeError(
                    f"Failed to start metrics server on port {metrics_port}: {e}"
                ) from e

    # Instrument FastAPI - use excluded_urls to suppress both traces AND metrics
    # for health/readiness/metrics endpoints. The custom sampler above only filters
    # trace spans
    # Patterns are anchored with $ to avoid matching substrings like /healthcheck.
    excluded_urls = ",".join(f"{p}$" for p in FILTERED_PATHS)
    logger.info(
        "Instrumenting FastAPI with OpenTelemetry (excluded_urls=%s)",
        excluded_urls,
    )
    FastAPIInstrumentor.instrument_app(app, excluded_urls=excluded_urls)

    # Register RQ metrics if Redis URL is provided
    if redis_url and enable_prometheus:
        logger.info(f"Registering RQ metrics collector for Redis at {redis_url}")
        connection = Redis.from_url(redis_url)
        REGISTRY.register(RQCollector(connection))

    # Register Ray metrics if RedisStateManager is provided
    if ray_redis_manager and enable_prometheus:
        logger.info("Registering Ray metrics collector")
        REGISTRY.register(RayCollector(ray_redis_manager))


def get_metrics_endpoint_content():
    """
    Get Prometheus metrics content for /metrics endpoint.

    Returns:
        Prometheus-formatted metrics content
    """
    from prometheus_client import REGISTRY, generate_latest

    return generate_latest(REGISTRY)

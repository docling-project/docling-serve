import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import grpc
import pytest
from opentelemetry import metrics
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
    ExportMetricsServiceResponse,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader
from redis import Redis
from rq import Queue, Retry
from rq.job import JobStatus

from docling_jobkit.convert.manager import (
    DoclingConverterManager,
    DoclingConverterManagerConfig,
)
from docling_jobkit.orchestrators.rq.orchestrator import RQOrchestratorConfig

from docling_serve.rq_worker_instrumented import InstrumentedRQWorker


def finish_job(
    *,
    fail: bool,
    conversion_manager: DoclingConverterManager,
    orchestrator_config: RQOrchestratorConfig,
    scratch_dir: Path,
) -> str:
    if fail:
        raise ValueError("conversion failed")
    return "converted"


@pytest.fixture
def rq_queue():
    redis_url = os.environ.get("TEST_REDIS_URL")
    if redis_url is None:
        pytest.skip("Set TEST_REDIS_URL to run real Redis worker tests")
    with Redis.from_url(redis_url) as connection:
        connection.ping()
        queue = Queue(name=f"metrics-{uuid4().hex}", connection=connection)
        yield queue, redis_url
        for job_id in queue.finished_job_registry.get_job_ids():
            queue.finished_job_registry.remove(job_id, delete_job=True)
        for job_id in queue.failed_job_registry.get_job_ids():
            queue.failed_job_registry.remove(job_id, delete_job=True)
        queue.delete(delete_jobs=True)


@pytest.mark.parametrize("fail,retries", [(False, 0), (True, 0), (True, 1)])
def test_queue_wait_recorded_once_before_job_execution(
    rq_queue, tmp_path, monkeypatch, fail, retries
):
    queue, redis_url = rq_queue
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    try:
        monkeypatch.setattr(metrics, "get_meter", provider.get_meter)
        job = queue.enqueue(
            finish_job, fail=fail, retry=Retry(max=retries) if retries else None
        )
        worker = InstrumentedRQWorker(
            [queue],
            connection=queue.connection,
            orchestrator_config=RQOrchestratorConfig(redis_url=redis_url),
            cm_config=DoclingConverterManagerConfig(),
            scratch_dir=tmp_path,
        )
        previous_sum = 0.0
        for attempt in range(retries + 1):
            enqueued_at = job.enqueued_at
            assert enqueued_at is not None
            before_work = datetime.now(timezone.utc)
            worker.work(burst=True, max_jobs=1)
            job.refresh()

            expected_status = JobStatus.FAILED if fail else JobStatus.FINISHED
            if attempt < retries:
                expected_status = JobStatus.QUEUED
                assert job.enqueued_at > enqueued_at
            assert job.get_status() == expected_status
            data = reader.get_metrics_data()
            assert data is not None, (
                "Worker must emit queue-wait metrics without tracing"
            )
            histogram = next(
                metric
                for resource in data.resource_metrics
                for scope in resource.scope_metrics
                for metric in scope.metrics
                if metric.name == "docling.rq.queue.wait.duration"
            )
            assert histogram.unit == "s"
            (point,) = histogram.data.data_points
            assert point.count == attempt + 1
            assert point.attributes == {"rq.queue.name": queue.name}
            assert job.started_at is not None
            wait = point.sum - previous_sum
            assert (before_work - enqueued_at).total_seconds() <= wait
            assert wait <= (job.started_at - enqueued_at).total_seconds()
            previous_sum = point.sum
    finally:
        provider.shutdown()


@pytest.mark.parametrize(
    "enable_metrics,enable_otlp,instance_id",
    [
        (True, True, None),
        (True, True, "configured-worker"),
        (False, True, None),
        (True, False, None),
    ],
)
def test_worker_cli_exports_on_shutdown_without_traces(
    rq_queue, tmp_path, enable_metrics, enable_otlp, instance_id
):
    queue, redis_url = rq_queue
    received: list[ExportMetricsServiceRequest] = []

    def export(request: ExportMetricsServiceRequest, context: grpc.ServicerContext):
        received.append(request)
        return ExportMetricsServiceResponse()

    with (
        ThreadPoolExecutor(max_workers=1) as executor,
        (tmp_path / "worker.log").open("w+") as log,
    ):
        server = grpc.server(executor)
        server.add_generic_rpc_handlers(
            [
                grpc.method_handlers_generic_handler(
                    "opentelemetry.proto.collector.metrics.v1.MetricsService",
                    {
                        "Export": grpc.unary_unary_rpc_method_handler(
                            export,
                            request_deserializer=ExportMetricsServiceRequest.FromString,
                            response_serializer=ExportMetricsServiceResponse.SerializeToString,
                        )
                    },
                )
            ]
        )
        port = server.add_insecure_port("127.0.0.1:0")
        server.start()
        env = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("OTEL_", "DOCLING_SERVE_"))
        }
        env.update(
            DOCLING_SERVE_ENG_RQ_REDIS_URL=redis_url,
            DOCLING_SERVE_ENG_RQ_QUEUE_NAME=queue.name,
            DOCLING_SERVE_OTEL_ENABLE_TRACES="false",
            DOCLING_SERVE_OTEL_ENABLE_METRICS=str(enable_metrics).lower(),
            DOCLING_SERVE_OTEL_ENABLE_OTLP_METRICS=str(enable_otlp).lower(),
            DOCLING_SERVE_OTEL_SERVICE_NAME="queue-test",
            OTEL_EXPORTER_OTLP_METRICS_ENDPOINT=f"http://127.0.0.1:{port}",
            OTEL_METRIC_EXPORT_INTERVAL="3600000",
        )
        if instance_id is not None:
            env["OTEL_RESOURCE_ATTRIBUTES"] = f"service.instance.id={instance_id}"
        job = queue.enqueue(finish_job, fail=False)
        process = subprocess.Popen(
            [sys.executable, "-m", "docling_serve", "rq-worker"],
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.monotonic() + 60
            while (
                job.get_status(refresh=True) != JobStatus.FINISHED
                and process.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
            assert job.get_status(refresh=True) == JobStatus.FINISHED
            assert received == [], (
                "Long export interval should defer export until shutdown"
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                server.stop(grace=0).wait()
        log.seek(0)
        assert process.returncode == 0, log.read()
        if enable_metrics and enable_otlp:
            assert received, "Worker shutdown must flush the OTLP histogram"
            (resource,) = received[0].resource_metrics
            job.refresh()
            assert any(
                attribute.key == "service.instance.id"
                and attribute.value.string_value == (instance_id or job.worker_name)
                for attribute in resource.resource.attributes
            )
            assert any(
                attribute.key == "service.name"
                and attribute.value.string_value == "queue-test-worker"
                for attribute in resource.resource.attributes
            )
            (scope,) = resource.scope_metrics
            (metric,) = scope.metrics
            assert metric.name == "docling.rq.queue.wait.duration"
            assert metric.unit == "s"
            (point,) = metric.histogram.data_points
            assert point.count == 1
            assert point.sum > 0
            assert {a.key: a.value.string_value for a in point.attributes} == {
                "rq.queue.name": queue.name
            }
        else:
            assert received == []

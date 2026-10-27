"""Unit tests for the RQ collector's snapshot health and empty-queue behavior."""

from unittest.mock import patch

from prometheus_client import CollectorRegistry

from docling_serve import rq_metrics_collector
from docling_serve.rq_metrics_collector import RQCollector


def _collector(**kwargs) -> RQCollector:
    # A throwaway registry keeps the module-level Summary out of the global one.
    return RQCollector(registry=CollectorRegistry(), **kwargs)


def _collect(collector: RQCollector) -> dict:
    return {metric.name: metric for metric in collector.collect()}


def test_failed_collection_never_emits_partial_snapshot():
    collector = _collector()
    with (
        patch.object(rq_metrics_collector, "get_workers_stats", return_value=[]),
        patch.object(
            rq_metrics_collector,
            "get_jobs_by_queue",
            side_effect=ConnectionError("unavailable"),
        ),
    ):
        metrics = _collect(collector)

    assert "rq_jobs" not in metrics
    assert "rq_workers" not in metrics
    success = metrics["rq_collection_success"].samples[0]
    assert success.value == 0


def test_successful_collection_marks_health_and_timestamp():
    collector = _collector()
    with (
        patch.object(rq_metrics_collector, "get_workers_stats", return_value=[]),
        patch.object(
            rq_metrics_collector,
            "get_jobs_by_queue",
            return_value={"convert": {"queued": 4}},
        ),
        patch.object(rq_metrics_collector.time, "time", return_value=100.0),
    ):
        metrics = _collect(collector)

    assert metrics["rq_collection_success"].samples[0].value == 1
    rq_jobs = metrics["rq_jobs"].samples[0]
    assert (rq_jobs.labels, rq_jobs.value) == (
        {"queue": "convert", "status": "queued"},
        4,
    )
    last_success = metrics["rq_collection_last_success_timestamp_seconds"].samples[0]
    assert last_success.value == 100.0


def test_failed_collection_retains_last_success_timestamp():
    collector = _collector()
    with (
        patch.object(rq_metrics_collector, "get_workers_stats", return_value=[]),
        patch.object(rq_metrics_collector, "get_jobs_by_queue", return_value={}),
        patch.object(rq_metrics_collector.time, "time", return_value=100.0),
    ):
        _collect(collector)
    with (
        patch.object(rq_metrics_collector, "get_workers_stats", return_value=[]),
        patch.object(
            rq_metrics_collector,
            "get_jobs_by_queue",
            side_effect=ConnectionError("unavailable"),
        ),
    ):
        metrics = _collect(collector)

    assert metrics["rq_collection_success"].samples[0].value == 0
    last_success = metrics["rq_collection_last_success_timestamp_seconds"].samples[0]
    assert last_success.value == 100.0


def test_never_successful_collector_omits_last_success_time():
    collector = _collector()
    with patch.object(
        rq_metrics_collector,
        "get_workers_stats",
        side_effect=ConnectionError("unavailable"),
    ):
        metrics = _collect(collector)

    assert metrics["rq_collection_success"].samples[0].value == 0
    assert "rq_collection_last_success_timestamp_seconds" not in metrics


def test_configured_empty_queue_is_reported_as_zero():
    class _Queues:
        @staticmethod
        def all(_connection):
            return []

    with (
        patch.object(rq_metrics_collector, "Queue", _Queues),
        patch.object(
            rq_metrics_collector,
            "get_queue_jobs",
            return_value={"queued": 0},
        ) as queue_jobs,
    ):
        jobs = rq_metrics_collector.get_jobs_by_queue(object(), queue_names=["convert"])

    assert jobs == {"convert": {"queued": 0}}
    assert queue_jobs.call_args.args[1] == "convert"

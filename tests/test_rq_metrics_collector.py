"""Unit tests for the aggregate metrics in the RQ collector."""

from unittest.mock import patch

from prometheus_client import CollectorRegistry

from docling_serve import rq_metrics_collector
from docling_serve.rq_metrics_collector import RQCollector


def _collector() -> RQCollector:
    # A throwaway registry keeps the module-level Summary out of the global one.
    return RQCollector(registry=CollectorRegistry())


def _worker(name: str, state: str, queues: list[str]) -> dict:
    return {
        "name": name,
        "queues": queues,
        "state": state,
        "successful_job_count": 0,
        "failed_job_count": 0,
        "total_working_time": 0,
    }


def _collect(collector: RQCollector) -> dict:
    return {metric.name: metric for metric in collector.collect()}


def test_worker_count_aggregates_queue_memberships_by_state():
    workers = [
        _worker("worker-one", "busy", ["convert"]),
        _worker("worker-two", "busy", ["convert"]),
        _worker("worker-three", "idle", ["convert"]),
    ]
    with (
        patch.object(rq_metrics_collector, "get_workers_stats", return_value=workers),
        patch.object(
            rq_metrics_collector,
            "get_jobs_by_queue",
            return_value={"convert": {"queued": 0}},
        ),
    ):
        metrics = _collect(_collector())

    samples = metrics["rq_worker_count"].samples
    assert (
        next(
            s.value
            for s in samples
            if s.labels == {"queue": "convert", "state": "busy"}
        )
        == 2
    )
    assert (
        next(
            s.value
            for s in samples
            if s.labels == {"queue": "convert", "state": "idle"}
        )
        == 1
    )


def test_worker_count_has_no_worker_identifiers():
    workers = [_worker("worker-one", "busy", ["convert"])]
    with (
        patch.object(rq_metrics_collector, "get_workers_stats", return_value=workers),
        patch.object(
            rq_metrics_collector,
            "get_jobs_by_queue",
            return_value={"convert": {"queued": 0}},
        ),
    ):
        metrics = _collect(_collector())

    assert all(
        set(s.labels) == {"queue", "state"} for s in metrics["rq_worker_count"].samples
    )


def test_worker_count_reports_zero_for_unseen_states():
    workers = [_worker("worker-one", "busy", ["convert"])]
    with (
        patch.object(rq_metrics_collector, "get_workers_stats", return_value=workers),
        patch.object(
            rq_metrics_collector,
            "get_jobs_by_queue",
            return_value={"convert": {"queued": 0}},
        ),
    ):
        metrics = _collect(_collector())

    samples = metrics["rq_worker_count"].samples
    assert (
        next(
            s.value
            for s in samples
            if s.labels == {"queue": "convert", "state": "idle"}
        )
        == 0
    )


def test_worker_count_counts_multi_queue_worker_once_per_queue():
    workers = [_worker("worker-one", "busy", ["convert", "chunk"])]
    with (
        patch.object(rq_metrics_collector, "get_workers_stats", return_value=workers),
        patch.object(
            rq_metrics_collector,
            "get_jobs_by_queue",
            return_value={"convert": {"queued": 0}, "chunk": {"queued": 0}},
        ),
    ):
        metrics = _collect(_collector())

    busy = [
        s for s in metrics["rq_worker_count"].samples if s.labels["state"] == "busy"
    ]
    assert {s.labels["queue"] for s in busy} == {"convert", "chunk"}
    assert all(s.value == 1 for s in busy)


def test_worker_count_empty_fleet_reports_zero():
    with (
        patch.object(rq_metrics_collector, "get_workers_stats", return_value=[]),
        patch.object(
            rq_metrics_collector,
            "get_jobs_by_queue",
            return_value={"convert": {"queued": 0}},
        ),
    ):
        metrics = _collect(_collector())

    samples = metrics["rq_worker_count"].samples
    assert {s.labels["queue"] for s in samples} == {"convert"}
    assert all(s.value == 0 for s in samples)

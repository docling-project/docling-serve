# Heavily based on https://github.com/mdawar/rq-exporter
import logging
import time
from collections.abc import Iterable

from prometheus_client import Summary
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import REGISTRY, Collector
from redis import Redis
from redis.exceptions import RedisError
from rq import Queue, Worker
from rq.job import JobStatus

logger = logging.getLogger(__name__)


def get_redis_connection(url: str):
    return Redis.from_url(url)


def get_workers_stats(connection):
    """Get the RQ workers stats."""

    workers = Worker.all(connection)

    return [
        {
            "name": w.name,
            "queues": w.queue_names(),
            "state": w.get_state(),
            "successful_job_count": w.successful_job_count,
            "failed_job_count": w.failed_job_count,
            "total_working_time": w.total_working_time,
        }
        for w in workers
    ]


def get_queue_jobs(connection, queue_name):
    """Get the jobs by status of a Queue."""

    queue = Queue(connection=connection, name=queue_name)

    return {
        JobStatus.QUEUED: queue.count,
        JobStatus.STARTED: queue.started_job_registry.count,
        JobStatus.FINISHED: queue.finished_job_registry.count,
        JobStatus.FAILED: queue.failed_job_registry.count,
        JobStatus.DEFERRED: queue.deferred_job_registry.count,
        JobStatus.SCHEDULED: queue.scheduled_job_registry.count,
    }


def get_jobs_by_queue(connection, queue_names: Iterable[str] = ()):
    """Get the current jobs by queue.

    ``Queue.all()`` only returns queues that already exist in Redis, so a
    freshly deployed or fully drained queue would disappear from the metrics
    entirely. ``queue_names`` are always reported, emitting an observed zero
    for an empty queue instead of going missing.
    """

    queues = {q.name for q in Queue.all(connection)}
    queues.update(queue_names)

    return {name: get_queue_jobs(connection, name) for name in sorted(queues)}


class RQCollector(Collector):
    """RQ stats collector.

    A scrape either publishes a complete snapshot or only the collection
    health gauges: a partial read (e.g. Redis blip mid-collection) must not
    surface as a real drop in queue or worker counts.
    """

    def __init__(
        self, connection=None, *, queue_names: Iterable[str] = (), registry=REGISTRY
    ):
        self.connection = connection
        self.queue_names = tuple(queue_names)
        self.last_success_timestamp: float | None = None

        # RQ data collection count and time in seconds
        self.summary = Summary(
            "rq_request_processing_seconds",
            "Time spent collecting RQ data",
            registry=registry,
        )

    def collect(self):
        """Collect RQ metrics as one all-or-nothing snapshot."""
        logger.debug("Collecting the RQ metrics...")

        collection_success = GaugeMetricFamily(
            "rq_collection_success",
            "Whether this RQ metrics snapshot was collected successfully",
        )
        try:
            with self.summary.time():
                snapshot = list(self._collect_snapshot())
        except (RedisError, OSError, ValueError, TypeError) as exc:
            logger.warning("RQ metrics collection failed (%s)", type(exc).__name__)
            collection_success.add_metric([], 0)
        else:
            self.last_success_timestamp = time.time()
            collection_success.add_metric([], 1)
            yield from snapshot
        yield collection_success
        if self.last_success_timestamp is not None:
            last_success = GaugeMetricFamily(
                "rq_collection_last_success_timestamp_seconds",
                "Unix timestamp of the last successful complete RQ metrics snapshot",
            )
            last_success.add_metric([], self.last_success_timestamp)
            yield last_success

        logger.debug("RQ metrics collection finished")

    def _collect_snapshot(self):
        rq_workers = GaugeMetricFamily(
            "rq_workers",
            "RQ workers",
            labels=["name", "state", "queues"],
        )
        rq_workers_success = CounterMetricFamily(
            "rq_workers_success",
            "RQ workers success count",
            labels=["name", "queues"],
        )
        rq_workers_failed = CounterMetricFamily(
            "rq_workers_failed",
            "RQ workers fail count",
            labels=["name", "queues"],
        )
        rq_workers_working_time = CounterMetricFamily(
            "rq_workers_working_time",
            "RQ workers spent seconds",
            labels=["name", "queues"],
        )
        rq_jobs = GaugeMetricFamily(
            "rq_jobs",
            "RQ jobs by state",
            labels=["queue", "status"],
        )

        workers = get_workers_stats(self.connection)
        for worker in workers:
            label_queues = ",".join(worker["queues"])
            rq_workers.add_metric(
                [worker["name"], worker["state"], label_queues],
                1,
            )
            rq_workers_success.add_metric(
                [worker["name"], label_queues],
                worker["successful_job_count"],
            )
            rq_workers_failed.add_metric(
                [worker["name"], label_queues],
                worker["failed_job_count"],
            )
            rq_workers_working_time.add_metric(
                [worker["name"], label_queues],
                worker["total_working_time"],
            )

        yield rq_workers
        yield rq_workers_success
        yield rq_workers_failed
        yield rq_workers_working_time

        for queue_name, jobs in get_jobs_by_queue(
            self.connection, self.queue_names
        ).items():
            for status, count in jobs.items():
                rq_jobs.add_metric([queue_name, status], count)

        yield rq_jobs

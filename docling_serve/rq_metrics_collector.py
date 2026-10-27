# Heavily based on https://github.com/mdawar/rq-exporter
import logging
from collections import Counter

from prometheus_client import Summary
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import REGISTRY, Collector
from redis import Redis
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


def get_jobs_by_queue(connection):
    """Get the current jobs by queue"""

    queues = Queue.all(connection)

    return {q.name: get_queue_jobs(connection, q.name) for q in queues}


class RQCollector(Collector):
    """RQ stats collector."""

    def __init__(self, connection=None, *, registry=REGISTRY):
        self.connection = connection

        # RQ data collection count and time in seconds
        self.summary = Summary(
            "rq_request_processing_seconds",
            "Time spent collecting RQ data",
            registry=registry,
        )

    def collect(self):
        """Collect RQ Metrics."""
        logger.debug("Collecting the RQ metrics...")

        with self.summary.time():
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
            jobs_by_queue = get_jobs_by_queue(self.connection)
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

            # Aggregate queue memberships by state. Worker names are unbounded
            # labels; the per-queue totals are the fleet-health signal.
            worker_counts = Counter(
                (queue_name, worker["state"])
                for worker in workers
                for queue_name in worker["queues"]
            )
            rq_worker_count = GaugeMetricFamily(
                "rq_worker_count",
                "RQ worker queue memberships by state",
                labels=["queue", "state"],
            )
            states = {"idle", "busy", "suspended", "started"} | {
                state for _, state in worker_counts
            }
            for queue_name in jobs_by_queue:
                for state in sorted(states):
                    rq_worker_count.add_metric(
                        [queue_name, state], worker_counts[queue_name, state]
                    )
            yield rq_worker_count

            for queue_name, jobs in jobs_by_queue.items():
                for status, count in jobs.items():
                    rq_jobs.add_metric([queue_name, status], count)

            yield rq_jobs

        logger.debug("RQ metrics collection finished")

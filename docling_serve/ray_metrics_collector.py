"""Prometheus metrics collector for Ray orchestrator."""

# Example Grafana / PromQL queries for the metrics exposed here. Replace `acme`
# with a tenant_id, or drop the {tenant_id=...} selector and wrap in sum() to
# aggregate across all tenants. Use rate()/increase() only on the *_total
# counters, never on the *_pending / *_active gauges.
#
# --- Documents for a tenant ---
#   # lifetime documents processed / succeeded / failed (cumulative counters)
#   ray_tenant_documents_total{tenant_id="acme"}
#   ray_tenant_documents_succeeded_total{tenant_id="acme"}
#   ray_tenant_documents_failed_total{tenant_id="acme"}
#   # documents processed in the last hour
#   increase(ray_tenant_documents_total{tenant_id="acme"}[1h])
#
# --- Tasks for a tenant ---
#   # current snapshot (gauges)
#   ray_tenant_tasks_pending{tenant_id="acme"}   # waiting in queue
#   ray_tenant_tasks_active{tenant_id="acme"}     # dispatched or running
#   # currently running, derived from loss-proof counters
#   ray_tenant_tasks_started_total{tenant_id="acme"}
#     - ray_tenant_tasks_succeeded_total{tenant_id="acme"}
#     - ray_tenant_tasks_failed_total{tenant_id="acme"}
#   # lifetime totals
#   ray_tenant_tasks_enqueued_total{tenant_id="acme"}
#   ray_tenant_tasks_succeeded_total{tenant_id="acme"}
#   ray_tenant_tasks_failed_total{tenant_id="acme"}
#
# --- Processing rate (derived) ---
#   # documents/sec (multiply by 60 for /min); window must span >= 2 scrapes
#   rate(ray_tenant_documents_total{tenant_id="acme"}[5m])
#   # task completion rate (succeeded + failed), per second
#   rate(ray_tenant_tasks_succeeded_total{tenant_id="acme"}[5m])
#     + rate(ray_tenant_tasks_failed_total{tenant_id="acme"}[5m])
#   # throughput across all tenants
#   sum(rate(ray_tenant_documents_succeeded_total[5m]))
#   # failure ratio (0-1)
#   rate(ray_tenant_tasks_failed_total{tenant_id="acme"}[5m])
#     / (rate(ray_tenant_tasks_succeeded_total{tenant_id="acme"}[5m])
#        + rate(ray_tenant_tasks_failed_total{tenant_id="acme"}[5m]))

import asyncio
import concurrent.futures
import logging
from dataclasses import dataclass
from typing import Any

from prometheus_client import Summary
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector

logger = logging.getLogger(__name__)

# Thread pool for running async operations from sync context. The Prometheus
# Collector.collect() API is synchronous, but the Redis client is async; we run
# the whole collection as a single coroutine in a dedicated thread/event loop to
# avoid "Future attached to a different loop" errors.
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="ray_metrics"
)

# Number of Redis reads issued per tenant in _collect_from_manager (counters,
# stats, queue size, active count, limits). Used to size concurrency so the
# in-flight reads stay within the connection pool.
_READS_PER_TENANT = 5

# Hard ceiling for the timeout of a single scrape's Redis work.
_COLLECT_TIMEOUT_S = 30


@dataclass
class TenantSnapshot:
    """All per-tenant values read from Redis in a single scrape."""

    tenant_id: str
    counters: Any  # TenantTaskCounters
    stats: Any  # TenantStats
    queue_size: int
    active_count: int
    limits: Any  # TenantLimits


@dataclass
class CollectedData:
    """Everything one scrape needs, gathered over a single Redis connection."""

    tenants: list  # list[TenantSnapshot]
    num_tenants_with_any: int


async def _collect_from_manager(redis_manager) -> CollectedData:
    """Gather every metric value over a single (already connected) manager.

    The two tenant-list reads run concurrently; then each tenant's reads run
    concurrently, with a semaphore bounding the total in-flight reads to stay
    within the connection pool. This replaces the previous design that opened
    and tore down a fresh connection for every single value.
    """
    tenants_with_any, tenants_with_counters = await asyncio.gather(
        redis_manager.get_all_tenants_with_any_tasks(),
        redis_manager.get_all_tenants_with_task_counters(),
    )
    # Union: idle-but-historically-active tenants must keep being scraped,
    # otherwise their counters would vanish and reappear, looking like a reset
    # to rate()/increase().
    tenants = sorted(set(tenants_with_any) | set(tenants_with_counters))

    max_conn = getattr(redis_manager, "max_connections", None) or 50
    # Leave a little headroom under the pool size; never below 1.
    tenant_concurrency = max(1, min(16, (max_conn - 1) // _READS_PER_TENANT))
    semaphore = asyncio.Semaphore(tenant_concurrency)

    async def _one(tenant_id: str) -> TenantSnapshot:
        async with semaphore:
            counters, stats, queue_size, active_count, limits = await asyncio.gather(
                redis_manager.get_tenant_task_counters(tenant_id),
                redis_manager.get_tenant_stats(tenant_id),
                redis_manager.get_tenant_queue_size(tenant_id),
                redis_manager.get_tenant_active_task_count(tenant_id),
                redis_manager.get_tenant_limits(tenant_id),
            )
            return TenantSnapshot(
                tenant_id=tenant_id,
                counters=counters,
                stats=stats,
                queue_size=queue_size,
                active_count=active_count,
                limits=limits,
            )

    results = await asyncio.gather(*(_one(t) for t in tenants), return_exceptions=True)

    snapshots: list = []
    for tenant_id, result in zip(tenants, results):
        if isinstance(result, Exception):
            logger.error(
                "Error collecting metrics for tenant %s: %s",
                tenant_id,
                result,
                exc_info=result,
            )
            continue
        snapshots.append(result)

    return CollectedData(tenants=snapshots, num_tenants_with_any=len(tenants_with_any))


def collect_metrics_data(redis_manager) -> CollectedData:
    """Run one full collection in a dedicated thread over a single connection.

    Creates a fresh RedisStateManager in the thread's event loop (using the
    original manager only for config), connects once, gathers all values, and
    disconnects once.

    Raises:
        TimeoutError: if the collection takes longer than _COLLECT_TIMEOUT_S.
    """

    def run_in_thread() -> CollectedData:
        from docling_jobkit.orchestrators.ray.redis_helper import (
            RedisStateManager,
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            thread_redis_manager = RedisStateManager(
                redis_url=redis_manager.redis_url,
                results_ttl=redis_manager.results_ttl,
                results_prefix=redis_manager.results_prefix,
                sub_channel=redis_manager.sub_channel,
                max_connections=redis_manager.max_connections,
                socket_timeout=redis_manager.socket_timeout,
                socket_connect_timeout=redis_manager.socket_connect_timeout,
                max_concurrent_tasks=redis_manager.max_concurrent_tasks,
                max_queued_tasks=redis_manager.max_queued_tasks,
                max_documents=redis_manager.max_documents,
                log_level=redis_manager.log_level,
            )

            async def runner() -> CollectedData:
                await thread_redis_manager.connect()
                try:
                    return await _collect_from_manager(thread_redis_manager)
                finally:
                    await thread_redis_manager.disconnect()

            return loop.run_until_complete(runner())
        finally:
            loop.close()

    future = _executor.submit(run_in_thread)
    try:
        return future.result(timeout=_COLLECT_TIMEOUT_S)
    except concurrent.futures.TimeoutError:
        logger.error("Timeout collecting Ray metrics from Redis")
        raise


# Per-tenant monotonic lifecycle counters exposed to Prometheus. The name is the
# Redis hash field; the Prometheus metric name is derived by stripping the
# trailing "_total" (CounterMetricFamily re-appends it) and prefixing "ray_".
# These are cumulative and read straight from Redis, so transitions that happen
# between two scrapes are never lost.
_LIFECYCLE_COUNTERS = [
    ("ray_tenant_tasks_enqueued", "tasks_enqueued_total", "Tasks enqueued"),
    ("ray_tenant_tasks_dispatched", "tasks_dispatched_total", "Tasks dispatched"),
    ("ray_tenant_tasks_started", "tasks_started_total", "Tasks started"),
    ("ray_tenant_tasks_succeeded", "tasks_succeeded_total", "Tasks succeeded"),
    ("ray_tenant_tasks_failed", "tasks_failed_total", "Tasks failed"),
]

# Per-tenant cumulative document counters, read from the tenant:{id}:stats hash
# (TenantStats). Tuple is (prometheus_name, stats_attr, help). These are
# best-effort: stats is written as a post-finalize follow-up, and only
# documents_succeeded / documents_failed reflect the real per-document counts
# from the conversion result. total_documents (and failure-path failed counts)
# fall back to the task's source-spec count, which is not the document count for
# expanding sources such as S3 buckets. Exposed as-is for now.
_STATS_COUNTERS = [
    ("ray_tenant_documents", "total_documents", "Documents processed (terminal)"),
    (
        "ray_tenant_documents_succeeded",
        "successful_documents",
        "Documents successfully converted (terminal)",
    ),
    ("ray_tenant_documents_failed", "failed_documents", "Documents failed (terminal)"),
]


class RayCollector(Collector):
    """Ray orchestrator metrics collector for Prometheus.

    Collects metrics about task queues, resource usage, and limits
    for the Ray orchestrator with per-tenant granularity.
    """

    def __init__(self, redis_manager):
        """Initialize Ray metrics collector.

        Args:
            redis_manager: RedisStateManager instance for querying Redis state
        """
        self.redis_manager = redis_manager

        # Ray data collection count and time in seconds
        self.summary = Summary(
            "ray_request_processing_seconds",
            "Time spent collecting Ray data",
        )

    def collect(self):
        """Collect Ray metrics from Redis.

        Yields Prometheus metric families:

        Monotonic per-tenant lifecycle counters (cumulative, loss-proof across
        scrapes) for the queued -> dispatched -> started -> terminal transitions.
        Instantaneous occupancy is derived in Grafana from counter differences,
        e.g. currently-running =
        tasks_started_total - tasks_succeeded_total - tasks_failed_total.

        Plus cumulative per-tenant document counters from the stats hash
        (documents processed / succeeded / failed); best-effort, see
        _STATS_COUNTERS.

        Plus cheap O(1) snapshot gauges for current depth:
        - Per-tenant pending tasks (queue length)
        - Per-tenant active tasks (dispatched-or-running, active-set size)
        - Per-tenant active documents
        - Per-tenant limits (concurrent tasks, queued tasks, documents)
        - System-wide totals and number of tenants with tasks

        All values are read over a single Redis connection per scrape (see
        collect_metrics_data), so scrape cost stays low even with many tenants.
        """
        logger.debug("Collecting Ray metrics...")

        with self.summary.time():
            # --- Monotonic lifecycle counters (per tenant) ---
            counter_families = {
                field: CounterMetricFamily(name, doc, labels=["tenant_id"])
                for name, field, doc in _LIFECYCLE_COUNTERS
            }

            # --- Cumulative document counters (per tenant, from stats) ---
            stats_counter_families = {
                attr: CounterMetricFamily(name, doc, labels=["tenant_id"])
                for name, attr, doc in _STATS_COUNTERS
            }

            # --- Snapshot gauges (current depth) ---
            tenant_tasks_pending = GaugeMetricFamily(
                "ray_tenant_tasks_pending",
                "Number of tasks waiting in tenant's queue (not yet dispatched to actors)",
                labels=["tenant_id"],
            )
            tenant_tasks_active = GaugeMetricFamily(
                "ray_tenant_tasks_active",
                "Number of tasks currently in the active set (dispatched or running)",
                labels=["tenant_id"],
            )
            tenant_documents_active = GaugeMetricFamily(
                "ray_tenant_documents_active",
                "Number of documents currently being processed by tenant",
                labels=["tenant_id"],
            )
            tenant_limit_max_concurrent = GaugeMetricFamily(
                "ray_tenant_limit_max_concurrent_tasks",
                "Tenant's maximum concurrent tasks limit",
                labels=["tenant_id"],
            )
            tenant_limit_max_queued = GaugeMetricFamily(
                "ray_tenant_limit_max_queued_tasks",
                "Tenant's maximum queued tasks limit (0 means unlimited)",
                labels=["tenant_id"],
            )
            tenant_limit_max_documents = GaugeMetricFamily(
                "ray_tenant_limit_max_documents",
                "Tenant's maximum documents limit (0 means unlimited)",
                labels=["tenant_id"],
            )

            # Total snapshot gauges (no labels)
            total_tasks_pending = GaugeMetricFamily(
                "ray_total_tasks_pending",
                "Total number of pending tasks across all tenants (in queue, not yet dispatched to actors)",
            )
            total_tasks_active = GaugeMetricFamily(
                "ray_total_tasks_active",
                "Total number of active tasks across all tenants (dispatched or running)",
            )
            total_documents_active = GaugeMetricFamily(
                "ray_total_documents_active",
                "Total number of active documents across all tenants",
            )
            tenants_with_tasks = GaugeMetricFamily(
                "ray_tenants_with_tasks",
                "Number of tenants with tasks in the system",
            )

            try:
                data = collect_metrics_data(self.redis_manager)

                total_pending = 0
                total_active = 0
                total_docs = 0

                for snap in data.tenants:
                    tenant_id = snap.tenant_id

                    # Monotonic lifecycle counters
                    for field, family in counter_families.items():
                        family.add_metric([tenant_id], getattr(snap.counters, field))

                    # Cumulative document counters (best-effort, from stats)
                    for attr, family in stats_counter_families.items():
                        family.add_metric([tenant_id], getattr(snap.stats, attr))

                    # Queue depth (pending tasks)
                    tenant_tasks_pending.add_metric([tenant_id], snap.queue_size)
                    total_pending += snap.queue_size

                    # Active tasks (dispatched or running)
                    tenant_tasks_active.add_metric([tenant_id], snap.active_count)
                    total_active += snap.active_count

                    # Active documents (from limits)
                    limits = snap.limits
                    tenant_documents_active.add_metric(
                        [tenant_id], limits.active_documents
                    )
                    total_docs += limits.active_documents

                    tenant_limit_max_concurrent.add_metric(
                        [tenant_id], limits.max_concurrent_tasks
                    )

                    # Handle None values for optional limits (0 = unlimited)
                    max_queued = (
                        limits.max_queued_tasks
                        if limits.max_queued_tasks is not None
                        else 0
                    )
                    tenant_limit_max_queued.add_metric([tenant_id], max_queued)

                    max_docs = (
                        limits.max_documents if limits.max_documents is not None else 0
                    )
                    tenant_limit_max_documents.add_metric([tenant_id], max_docs)

                # Set total snapshot gauges
                total_tasks_pending.add_metric([], total_pending)
                total_tasks_active.add_metric([], total_active)
                total_documents_active.add_metric([], total_docs)
                tenants_with_tasks.add_metric([], data.num_tenants_with_any)

            except Exception as e:
                logger.error(f"Error collecting Fair Ray metrics: {e}", exc_info=True)
                # Return empty metrics on error

            # Yield all metrics
            yield from counter_families.values()
            yield from stats_counter_families.values()
            yield tenant_tasks_pending
            yield tenant_tasks_active
            yield tenant_documents_active
            yield tenant_limit_max_concurrent
            yield tenant_limit_max_queued
            yield tenant_limit_max_documents
            yield total_tasks_pending
            yield total_tasks_active
            yield total_documents_active
            yield tenants_with_tasks

        logger.debug("Fair Ray metrics collection finished")

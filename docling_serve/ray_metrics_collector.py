"""Prometheus metrics collector for Ray orchestrator."""

import asyncio
import concurrent.futures
import logging
from typing import Any

from prometheus_client import Summary
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector

logger = logging.getLogger(__name__)

# Thread pool for running async operations from sync context
# This avoids event loop conflicts by isolating async operations in a separate thread
_executor = concurrent.futures.ThreadPoolExecutor(
    max_workers=1, thread_name_prefix="ray_metrics"
)


def run_async_with_new_connection(redis_manager, coro_func, *args, **kwargs) -> Any:
    """Run async coroutine with a fresh Redis connection in a separate thread.

    This creates a new RedisStateManager connection in the thread's event loop,
    avoiding "Future attached to a different loop" errors that occur when using
    a connection created in a different event loop.

    Args:
        redis_manager: Original RedisStateManager (used for config only)
        coro_func: Async function to call (e.g., redis_manager.get_all_tenants_with_tasks)
        *args: Arguments to pass to coro_func
        **kwargs: Keyword arguments to pass to coro_func

    Returns:
        Result of the coroutine

    Raises:
        TimeoutError: If coroutine takes longer than 30 seconds
    """

    def run_in_thread():
        """Run coroutine in a new event loop with fresh Redis connection."""
        from docling_jobkit.orchestrators.ray.redis_helper import (
            RedisStateManager,
        )

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            # Create a new RedisStateManager in this thread's event loop
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

            async def run_with_connection():
                """Connect, run the coroutine, and disconnect."""
                await thread_redis_manager.connect()
                try:
                    # Get the method from the new manager and call it
                    method = getattr(thread_redis_manager, coro_func.__name__)
                    return await method(*args, **kwargs)
                finally:
                    await thread_redis_manager.disconnect()

            return loop.run_until_complete(run_with_connection())
        finally:
            loop.close()

    # Submit to thread pool and wait for result with timeout
    future = _executor.submit(run_in_thread)
    try:
        return future.result(timeout=30)  # 30 second timeout
    except concurrent.futures.TimeoutError:
        logger.error("Timeout waiting for async operation in metrics collector")
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
                # Union of tenants with live tasks and tenants with cumulative
                # counters. Idle-but-historically-active tenants must keep being
                # scraped, otherwise their counters would vanish and reappear,
                # looking like a reset to rate()/increase().
                tenants_with_any = run_async_with_new_connection(
                    self.redis_manager,
                    self.redis_manager.get_all_tenants_with_any_tasks,
                )
                tenants_with_counters = run_async_with_new_connection(
                    self.redis_manager,
                    self.redis_manager.get_all_tenants_with_task_counters,
                )
                tenants = sorted(set(tenants_with_any) | set(tenants_with_counters))

                # Accumulators for snapshot totals
                total_pending = 0
                total_active = 0
                total_docs = 0

                # Collect per-tenant metrics
                for tenant_id in tenants:
                    try:
                        # Monotonic counters
                        counters = run_async_with_new_connection(
                            self.redis_manager,
                            self.redis_manager.get_tenant_task_counters,
                            tenant_id,
                        )
                        for field, family in counter_families.items():
                            family.add_metric([tenant_id], getattr(counters, field))

                        # Cumulative document counters (best-effort, from stats)
                        stats = run_async_with_new_connection(
                            self.redis_manager,
                            self.redis_manager.get_tenant_stats,
                            tenant_id,
                        )
                        for attr, family in stats_counter_families.items():
                            family.add_metric([tenant_id], getattr(stats, attr))

                        # Queue depth (pending tasks) - O(1) LLEN
                        queue_size = run_async_with_new_connection(
                            self.redis_manager,
                            self.redis_manager.get_tenant_queue_size,
                            tenant_id,
                        )
                        tenant_tasks_pending.add_metric([tenant_id], queue_size)
                        total_pending += queue_size

                        # Active tasks (dispatched or running) - O(1) SCARD
                        active_count = run_async_with_new_connection(
                            self.redis_manager,
                            self.redis_manager.get_tenant_active_task_count,
                            tenant_id,
                        )
                        tenant_tasks_active.add_metric([tenant_id], active_count)
                        total_active += active_count

                        # Tenant limits (includes active documents)
                        limits = run_async_with_new_connection(
                            self.redis_manager,
                            self.redis_manager.get_tenant_limits,
                            tenant_id,
                        )

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
                            limits.max_documents
                            if limits.max_documents is not None
                            else 0
                        )
                        tenant_limit_max_documents.add_metric([tenant_id], max_docs)

                    except Exception as e:
                        logger.error(
                            f"Error collecting metrics for tenant {tenant_id}: {e}",
                            exc_info=True,
                        )
                        continue

                # Set total snapshot gauges
                total_tasks_pending.add_metric([], total_pending)
                total_tasks_active.add_metric([], total_active)
                total_documents_active.add_metric([], total_docs)
                tenants_with_tasks.add_metric([], len(tenants_with_any))

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

"""Prometheus metrics collector for Ray orchestrator."""

import asyncio
import concurrent.futures
import logging
from typing import Any

from prometheus_client import Summary
from prometheus_client.core import GaugeMetricFamily
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

        Yields Prometheus metric families for:
        - Per-tenant pending tasks
        - Per-tenant running tasks
        - Per-tenant active documents
        - Per-tenant limits (concurrent tasks, queued tasks, documents)
        - Total pending tasks
        - Total running tasks
        - Total active documents
        - Number of tenants with tasks
        """
        logger.debug("Collecting Ray metrics...")

        with self.summary.time():
            # Define metric families
            tenant_tasks_pending = GaugeMetricFamily(
                "ray_tenant_tasks_pending",
                "Number of tasks waiting in tenant's queue (not yet dispatched to actors)",
                labels=["tenant_id"],
            )
            tenant_tasks_dispatched = GaugeMetricFamily(
                "ray_tenant_tasks_dispatched",
                "Number of tasks dispatched to actors but not yet started processing (status=PENDING)",
                labels=["tenant_id"],
            )
            tenant_tasks_running = GaugeMetricFamily(
                "ray_tenant_tasks_running",
                "Number of tasks actively being processed (status=STARTED)",
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

            # Total metrics (no labels)
            total_tasks_pending = GaugeMetricFamily(
                "ray_total_tasks_pending",
                "Total number of pending tasks across all tenants (in queue, not yet dispatched to actors)",
            )
            total_tasks_dispatched = GaugeMetricFamily(
                "ray_total_tasks_dispatched",
                "Total number of dispatched tasks across all tenants (sent to actors but not yet started, status=PENDING)",
            )
            total_tasks_running = GaugeMetricFamily(
                "ray_total_tasks_running",
                "Total number of running tasks across all tenants (actively being processed, status=STARTED)",
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
                # Get all users with tasks (queued OR active) using a fresh connection
                tenants = run_async_with_new_connection(
                    self.redis_manager,
                    self.redis_manager.get_all_tenants_with_any_tasks,
                )

                # Accumulators for totals
                total_pending = 0
                total_dispatched = 0
                total_running = 0
                total_docs = 0

                # Collect per-user metrics
                for tenant_id in tenants:
                    try:
                        # Get queue size (pending tasks)
                        queue_size = run_async_with_new_connection(
                            self.redis_manager,
                            self.redis_manager.get_tenant_queue_size,
                            tenant_id,
                        )
                        tenant_tasks_pending.add_metric([tenant_id], queue_size)
                        total_pending += queue_size

                        # Get dispatched task count (sent to actors but not yet running)
                        dispatched_count = run_async_with_new_connection(
                            self.redis_manager,
                            self.redis_manager.get_tenant_dispatched_task_count,
                            tenant_id,
                        )
                        tenant_tasks_dispatched.add_metric(
                            [tenant_id], dispatched_count
                        )
                        total_dispatched += dispatched_count

                        # Get running task count (actively being processed)
                        running_count = run_async_with_new_connection(
                            self.redis_manager,
                            self.redis_manager.get_tenant_running_task_count,
                            tenant_id,
                        )
                        tenant_tasks_running.add_metric([tenant_id], running_count)
                        total_running += running_count

                        # Get user limits (includes active documents)
                        limits = run_async_with_new_connection(
                            self.redis_manager,
                            self.redis_manager.get_tenant_limits,
                            tenant_id,
                        )

                        # Active documents
                        tenant_documents_active.add_metric(
                            [tenant_id], limits.active_documents
                        )
                        total_docs += limits.active_documents

                        # Tenant limits
                        tenant_limit_max_concurrent.add_metric(
                            [tenant_id], limits.max_concurrent_tasks
                        )

                        # Handle None values for optional limits (use 0 to indicate unlimited)
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
                            f"Error collecting metrics for user {tenant_id}: {e}",
                            exc_info=True,
                        )
                        continue

                # Set total metrics
                total_tasks_pending.add_metric([], total_pending)
                total_tasks_dispatched.add_metric([], total_dispatched)
                total_tasks_running.add_metric([], total_running)
                total_documents_active.add_metric([], total_docs)
                tenants_with_tasks.add_metric([], len(tenants))

            except Exception as e:
                logger.error(f"Error collecting Fair Ray metrics: {e}", exc_info=True)
                # Return empty metrics on error

            # Yield all metrics
            yield tenant_tasks_pending
            yield tenant_tasks_dispatched
            yield tenant_tasks_running
            yield tenant_documents_active
            yield tenant_limit_max_concurrent
            yield tenant_limit_max_queued
            yield tenant_limit_max_documents
            yield total_tasks_pending
            yield total_tasks_dispatched
            yield total_tasks_running
            yield total_documents_active
            yield tenants_with_tasks

        logger.debug("Fair Ray metrics collection finished")

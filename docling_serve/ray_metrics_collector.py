"""Prometheus metrics collector for Ray orchestrator."""

# Example Grafana / PromQL queries for the metrics exposed here. Replace `acme`
# with a tenant_id, or drop the {tenant_id=...} selector and wrap in sum() to
# aggregate across all tenants. Use rate()/increase() only on the *_total
# counters, never on the *_pending / *_active gauges.
#
# Only one docling-serve pod (the leader) exports these series at a time, so the
# pod label changes when leadership moves, and during a handover two pods can
# briefly export the same values. Aggregate with max without (pod, instance),
# never sum, and never select a pod.
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
import atexit
import logging
import os
import socket
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily
from prometheus_client.registry import Collector

from docling_jobkit.orchestrators.ray.models import TenantSnapshot

logger = logging.getLogger(__name__)

# Only one docling-serve process computes the tenant metrics: they describe the
# whole cluster, so every pod exporting them would multiply the Redis load and
# duplicate every series. The holder of this lock refreshes and exports them;
# the other processes export only the refresher health metrics.
_LEADER_KEY = "docling:ray:metrics:leader"

# Extend the lock only if this process still holds it.
_RENEW_LEADER_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

# Release the lock only if this process still holds it.
_RELEASE_LEADER_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

# A snapshot older than this many refresh intervals is no longer exported: the
# gauges would report a stale depth. The age gauge still shows the problem.
_MAX_AGE_INTERVALS = 5


@dataclass
class CollectedData:
    """Everything one refresh gathers from Redis."""

    tenants: list[TenantSnapshot]
    num_tenants_with_any: int


@dataclass
class RefresherState:
    """What the collector reads from the refresher at scrape time."""

    data: Optional[CollectedData]
    refreshed_at: Optional[float]  # time.time() of the last successful refresh
    refresh_duration: Optional[float]
    refresh_failures: int
    is_leader: bool


async def _collect_from_manager(redis_manager) -> CollectedData:
    """Gather every metric value over a single (already connected) manager.

    Tenant discovery reads the tenant registry and the per-tenant values are
    read in bulk pipelines, so the cost depends on the number of tenants, not
    on the size of the Redis keyspace.
    """
    tenants_with_any, tenants_with_counters = await asyncio.gather(
        redis_manager.get_all_tenants_with_any_tasks(),
        redis_manager.get_all_tenants_with_task_counters(),
    )
    # Union: idle-but-historically-active tenants must keep being scraped,
    # otherwise their counters would vanish and reappear, looking like a reset
    # to rate()/increase().
    tenants = sorted(set(tenants_with_any) | set(tenants_with_counters))
    snapshots = await redis_manager.get_tenant_snapshots(tenants)
    return CollectedData(tenants=snapshots, num_tenants_with_any=len(tenants_with_any))


def _clone_manager(redis_manager):
    """Build a RedisStateManager for the refresher thread's own event loop.

    The original manager belongs to the API event loop; it is only used here
    for its configuration.
    """
    from docling_jobkit.orchestrators.ray.redis_helper import RedisStateManager

    return RedisStateManager(
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


class RaySnapshotRefresher:
    """Refresh the Ray tenant metrics from Redis in a background thread.

    Prometheus scrapes then serve the last snapshot from memory and never wait
    on Redis. The refresh runs only in the process holding the leader lock.
    """

    def __init__(self, redis_manager, interval: float = 30.0):
        self.redis_manager = redis_manager
        self.interval = interval
        self.instance_id = (
            f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        )
        self._lock = threading.Lock()
        self._state = RefresherState(
            data=None,
            refreshed_at=None,
            refresh_duration=None,
            refresh_failures=0,
            is_leader=False,
        )
        self._thread: Optional[threading.Thread] = None
        self._loop_ref: Optional[asyncio.AbstractEventLoop] = None
        self._stop_event: Optional[asyncio.Event] = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="ray_metrics", daemon=True
        )
        self._thread.start()
        # Release the leader lock on a graceful shutdown, so another process
        # takes over at once instead of after the lock TTL.
        atexit.register(self.stop)

    def stop(self, timeout: float = 5.0) -> None:
        """Stop refreshing and release the leader lock if this process holds it."""
        loop, event = self._loop_ref, self._stop_event
        if loop is None or event is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(event.set)
        except RuntimeError:  # the loop closed in the meantime
            return
        if self._thread is not None:
            self._thread.join(timeout)

    def state(self) -> RefresherState:
        with self._lock:
            return RefresherState(**vars(self._state))

    def _run(self) -> None:
        asyncio.run(self._loop())

    async def _loop(self) -> None:
        self._loop_ref = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        manager = _clone_manager(self.redis_manager)
        await manager.connect()
        try:
            while not self._stop_event.is_set():
                await self.refresh_once(manager)
                try:
                    await asyncio.wait_for(
                        self._stop_event.wait(), timeout=self.interval
                    )
                except asyncio.TimeoutError:
                    pass
        finally:
            await self._release_leadership(manager)
            await manager.disconnect()

    async def refresh_once(self, manager) -> None:
        """Take or keep the leader lock and, as leader, refresh the snapshot."""
        try:
            is_leader = await self._acquire_leadership(manager)
        except Exception as exc:
            logger.error("Error acquiring the Ray metrics leader lock: %s", exc)
            self._record_failure()
            return

        if not is_leader:
            with self._lock:
                self._state.is_leader = False
                self._state.data = None
            return

        start = time.monotonic()
        try:
            data = await asyncio.wait_for(
                _collect_from_manager(manager), timeout=self.interval
            )
        except Exception as exc:
            logger.error("Error refreshing Ray metrics: %s", exc, exc_info=True)
            self._record_failure(is_leader=True)
            return

        with self._lock:
            self._state.is_leader = True
            self._state.data = data
            self._state.refreshed_at = time.time()
            self._state.refresh_duration = time.monotonic() - start

    def _record_failure(self, is_leader: bool = False) -> None:
        with self._lock:
            self._state.refresh_failures += 1
            self._state.is_leader = is_leader

    async def _acquire_leadership(self, manager) -> bool:
        redis = manager._ensure_redis()
        ttl_ms = int(self.interval * 3 * 1000)
        if await redis.set(_LEADER_KEY, self.instance_id, nx=True, px=ttl_ms):
            return True
        renewed = await redis.eval(
            _RENEW_LEADER_SCRIPT, 1, _LEADER_KEY, self.instance_id, ttl_ms
        )
        return bool(renewed)

    async def _release_leadership(self, manager) -> None:
        try:
            redis = manager._ensure_redis()
            await redis.eval(_RELEASE_LEADER_SCRIPT, 1, _LEADER_KEY, self.instance_id)
        except Exception as exc:
            logger.debug("Could not release the Ray metrics leader lock: %s", exc)


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

    Exposes per-tenant task and document metrics for the Ray orchestrator from
    the snapshot kept by a RaySnapshotRefresher, so a scrape never touches Redis.
    Only the process holding the leader lock exports the tenant metrics; every
    process exports the refresher health metrics.
    """

    def __init__(self, redis_manager, refresh_interval: float = 30.0, start=True):
        """Initialize Ray metrics collector.

        Args:
            redis_manager: RedisStateManager whose configuration the refresher
                uses to open its own connection
            refresh_interval: Seconds between two snapshot refreshes
            start: Start the background refresher thread
        """
        self.refresher = RaySnapshotRefresher(redis_manager, refresh_interval)
        if start:
            self.refresher.start()

    def collect(self):
        """Yield the Prometheus metric families from the last snapshot.

        Monotonic per-tenant lifecycle counters (cumulative, loss-proof across
        scrapes) for the queued -> dispatched -> started -> terminal transitions.
        Instantaneous occupancy is derived in Grafana from counter differences,
        e.g. currently-running =
        tasks_started_total - tasks_succeeded_total - tasks_failed_total.

        Plus cumulative per-tenant document counters from the stats hash
        (documents processed / succeeded / failed); best-effort, see
        _STATS_COUNTERS.

        Plus snapshot gauges for current depth:
        - Per-tenant pending tasks (queue length)
        - Per-tenant active tasks (dispatched-or-running, active-set size)
        - Per-tenant active documents
        - Per-tenant limits (concurrent tasks, queued tasks, documents)
        - System-wide totals and number of tenants with tasks

        Plus the refresher health: leader flag, snapshot age, refresh duration
        and refresh failures.
        """
        state = self.refresher.state()

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

        data = state.data
        age = (
            time.time() - state.refreshed_at if state.refreshed_at is not None else None
        )
        max_age = self.refresher.interval * _MAX_AGE_INTERVALS
        if data is not None and age is not None and age <= max_age:
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
                tenant_documents_active.add_metric([tenant_id], limits.active_documents)
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

        # --- Refresher health (every process) ---
        leader = GaugeMetricFamily(
            "ray_metrics_snapshot_leader",
            "1 if this process refreshes and exports the Ray tenant metrics",
        )
        leader.add_metric([], 1 if state.is_leader else 0)
        snapshot_age = GaugeMetricFamily(
            "ray_metrics_snapshot_age_seconds",
            "Seconds since the Ray tenant metrics snapshot was last refreshed",
        )
        if state.is_leader and age is not None:
            snapshot_age.add_metric([], age)
        refresh_duration = GaugeMetricFamily(
            "ray_metrics_snapshot_refresh_duration_seconds",
            "Duration of the last successful Ray tenant metrics refresh",
        )
        if state.is_leader and state.refresh_duration is not None:
            refresh_duration.add_metric([], state.refresh_duration)
        refresh_failures = CounterMetricFamily(
            "ray_metrics_snapshot_refresh_failures",
            "Failed Ray tenant metrics refreshes",
        )
        refresh_failures.add_metric([], state.refresh_failures)

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
        yield leader
        yield snapshot_age
        yield refresh_duration
        yield refresh_failures

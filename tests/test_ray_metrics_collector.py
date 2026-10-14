"""Tests for the RayCollector Prometheus exposition and its snapshot refresher.

The collector serves the snapshot kept by RaySnapshotRefresher, so the
exposition tests set the refresher state directly and never touch Redis. The
refresh and leader-lock logic is covered separately against AsyncMock managers.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from docling_jobkit.orchestrators.ray.models import (
    TenantLimits,
    TenantSnapshot,
    TenantStats,
    TenantTaskCounters,
)

from docling_serve.ray_metrics_collector import (
    CollectedData,
    RayCollector,
    RaySnapshotRefresher,
    _collect_from_manager,
)


def _canned_data() -> CollectedData:
    return CollectedData(
        tenants=[
            TenantSnapshot(
                tenant_id="tenant-a",
                counters=TenantTaskCounters(
                    tasks_enqueued_total=4,
                    tasks_dispatched_total=4,
                    tasks_started_total=4,
                    tasks_succeeded_total=3,
                    tasks_failed_total=1,
                ),
                stats=TenantStats(
                    total_tasks=4,
                    total_documents=10,
                    successful_documents=8,
                    failed_documents=2,
                ),
                queue_size=2,
                active_count=1,
                limits=TenantLimits(),
            ),
            # tenant-b is idle (no live tasks) but still carries counters.
            TenantSnapshot(
                tenant_id="tenant-b",
                counters=TenantTaskCounters(
                    tasks_enqueued_total=7, tasks_succeeded_total=7
                ),
                stats=TenantStats(),
                queue_size=0,
                active_count=0,
                limits=TenantLimits(),
            ),
        ],
        num_tenants_with_any=1,
    )


def _collector(
    data=None, is_leader=True, age: float = 1.0, duration: float = 0.2
) -> RayCollector:
    collector = RayCollector(MagicMock(), refresh_interval=30.0, start=False)
    state = collector.refresher._state
    state.data = data
    state.is_leader = is_leader
    state.refreshed_at = time.time() - age if data is not None else None
    state.refresh_duration = duration if data is not None else None
    return collector


def _samples(collector: RayCollector) -> tuple[dict, str]:
    registry = CollectorRegistry()
    registry.register(collector)
    text = generate_latest(registry).decode("utf-8")
    samples = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            key = (sample.name, tuple(sorted(sample.labels.items())))
            samples[key] = sample.value
    return samples, text


def test_lifecycle_counters_exposed_with_total_suffix():
    samples, _ = _samples(_collector(_canned_data()))

    # CounterMetricFamily appends _total to the exposed sample name.
    assert (
        samples[("ray_tenant_tasks_enqueued_total", (("tenant_id", "tenant-a"),))] == 4
    )
    assert (
        samples[("ray_tenant_tasks_succeeded_total", (("tenant_id", "tenant-a"),))] == 3
    )
    assert samples[("ray_tenant_tasks_failed_total", (("tenant_id", "tenant-a"),))] == 1


def test_document_counters_exposed_from_stats():
    samples, _ = _samples(_collector(_canned_data()))
    # CounterMetricFamily appends _total; values come from the stats hash.
    assert samples[("ray_tenant_documents_total", (("tenant_id", "tenant-a"),))] == 10
    assert (
        samples[("ray_tenant_documents_succeeded_total", (("tenant_id", "tenant-a"),))]
        == 8
    )
    assert (
        samples[("ray_tenant_documents_failed_total", (("tenant_id", "tenant-a"),))]
        == 2
    )


def test_idle_tenant_with_counters_is_still_scraped():
    samples, _ = _samples(_collector(_canned_data()))
    # tenant-b has no live tasks but its cumulative counters must still appear,
    # otherwise rate()/increase() would see a phantom counter reset.
    assert (
        samples[("ray_tenant_tasks_succeeded_total", (("tenant_id", "tenant-b"),))] == 7
    )


def test_snapshot_gauges_report_current_depth():
    samples, _ = _samples(_collector(_canned_data()))
    assert samples[("ray_tenant_tasks_pending", (("tenant_id", "tenant-a"),))] == 2
    assert samples[("ray_tenant_tasks_active", (("tenant_id", "tenant-a"),))] == 1
    # totals
    assert samples[("ray_total_tasks_pending", ())] == 2
    assert samples[("ray_total_tasks_active", ())] == 1


def test_removed_lossy_metrics_are_gone():
    _, text = _samples(_collector(_canned_data()))
    # The old transient "running" gauge (and its total) lost data and is fully
    # removed; "dispatched" now lives on as a monotonic counter instead.
    assert "ray_tenant_tasks_running" not in text
    assert "ray_total_tasks_running" not in text


def test_refresher_health_metrics():
    samples, _ = _samples(_collector(_canned_data(), age=4.0, duration=0.25))
    assert samples[("ray_metrics_snapshot_leader", ())] == 1
    assert 4.0 <= samples[("ray_metrics_snapshot_age_seconds", ())] < 10.0
    assert samples[("ray_metrics_snapshot_refresh_duration_seconds", ())] == 0.25
    assert samples[("ray_metrics_snapshot_refresh_failures_total", ())] == 0


def test_follower_exports_no_tenant_series():
    samples, _ = _samples(_collector(data=None, is_leader=False))
    assert samples[("ray_metrics_snapshot_leader", ())] == 0
    assert not any(name.startswith("ray_tenant_") for name, _ in samples)
    assert ("ray_total_tasks_pending", ()) not in samples
    assert ("ray_metrics_snapshot_age_seconds", ()) not in samples


def test_stale_snapshot_is_not_exported():
    # 5 intervals of 30 s is the limit; the age gauge still reports it.
    samples, _ = _samples(_collector(_canned_data(), age=200.0))
    assert not any(name.startswith("ray_tenant_") for name, _ in samples)
    assert samples[("ray_metrics_snapshot_age_seconds", ())] >= 200.0


def test_collect_from_manager_reads_snapshots_for_tenant_union():
    manager = AsyncMock()
    manager.get_all_tenants_with_any_tasks.return_value = ["tenant-a"]
    manager.get_all_tenants_with_task_counters.return_value = ["tenant-b", "tenant-a"]
    manager.get_tenant_snapshots.side_effect = lambda tenants: [
        TenantSnapshot(
            tenant_id=t,
            counters=TenantTaskCounters(),
            stats=TenantStats(),
            queue_size=0,
            active_count=0,
            limits=TenantLimits(),
        )
        for t in tenants
    ]

    data = asyncio.run(_collect_from_manager(manager))

    assert data.num_tenants_with_any == 1
    manager.get_tenant_snapshots.assert_awaited_once_with(["tenant-a", "tenant-b"])
    assert [s.tenant_id for s in data.tenants] == ["tenant-a", "tenant-b"]


class _FakeLockRedis:
    """The SET NX PX / renew / release subset of Redis the leader lock uses."""

    def __init__(self) -> None:
        self.holder: str | None = None

    async def set(self, key, value, nx=False, px=None):
        if nx and self.holder is not None:
            return None
        self.holder = value
        return True

    async def eval(self, script, numkeys, key, value, *args):
        if self.holder != value:
            return 0
        if "DEL" in script:
            self.holder = None
        return 1


def _manager_for(redis: _FakeLockRedis) -> AsyncMock:
    manager = AsyncMock()
    manager._ensure_redis = MagicMock(return_value=redis)
    manager.get_all_tenants_with_any_tasks.return_value = []
    manager.get_all_tenants_with_task_counters.return_value = []
    manager.get_tenant_snapshots.return_value = []
    return manager


def test_only_one_refresher_is_leader():
    redis = _FakeLockRedis()
    first = RaySnapshotRefresher(MagicMock(), interval=30.0)
    second = RaySnapshotRefresher(MagicMock(), interval=30.0)
    first_manager, second_manager = _manager_for(redis), _manager_for(redis)

    async def scenario():
        await first.refresh_once(first_manager)
        await second.refresh_once(second_manager)
        # The leader keeps the lock on its next refresh.
        await first.refresh_once(first_manager)

    asyncio.run(scenario())

    assert first.state().is_leader
    assert first.state().data is not None
    assert not second.state().is_leader
    assert second.state().data is None
    second_manager.get_tenant_snapshots.assert_not_awaited()

    # Once the leader releases the lock, the other process takes over.
    async def handover():
        await first._release_leadership(first_manager)
        await second.refresh_once(second_manager)

    asyncio.run(handover())
    assert second.state().is_leader


def test_failed_refresh_keeps_previous_snapshot():
    redis = _FakeLockRedis()
    refresher = RaySnapshotRefresher(MagicMock(), interval=30.0)
    manager = _manager_for(redis)

    asyncio.run(refresher.refresh_once(manager))
    previous = refresher.state()

    manager.get_all_tenants_with_any_tasks.side_effect = RuntimeError("redis down")
    asyncio.run(refresher.refresh_once(manager))
    state = refresher.state()

    assert state.refresh_failures == 1
    assert state.is_leader
    assert state.data is previous.data
    assert state.refreshed_at == previous.refreshed_at

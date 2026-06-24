"""Tests for the RayCollector Prometheus exposition.

Verifies that the monotonic lifecycle counters and cumulative document counters
are exposed (with the Prometheus ``_total`` suffix), that a tenant which is idle
but still has cumulative counters keeps being scraped, and that the snapshot
gauges report current depth. ``collect_metrics_data`` (which opens a single Redis
connection per scrape) is patched to return canned data, keeping the exposition
test hermetic; the gather logic itself is covered separately against an
AsyncMock manager.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from docling_jobkit.orchestrators.ray.models import (
    TenantLimits,
    TenantStats,
    TenantTaskCounters,
)

from docling_serve.ray_metrics_collector import (
    CollectedData,
    RayCollector,
    TenantSnapshot,
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


# RayCollector.__init__ registers a Summary on the global registry, so it can
# only be built once per process. Cache the collection result across tests.
_CACHE: dict = {}


def _collect_samples():
    if _CACHE:
        return _CACHE["samples"], _CACHE["text"]

    registry = CollectorRegistry()
    with patch(
        "docling_serve.ray_metrics_collector.collect_metrics_data",
        return_value=_canned_data(),
    ):
        registry.register(RayCollector(MagicMock()))
        text = generate_latest(registry).decode("utf-8")

    samples = {}
    for family in text_string_to_metric_families(text):
        for sample in family.samples:
            key = (sample.name, tuple(sorted(sample.labels.items())))
            samples[key] = sample.value
    _CACHE["samples"] = samples
    _CACHE["text"] = text
    return samples, text


def test_lifecycle_counters_exposed_with_total_suffix():
    samples, _ = _collect_samples()

    # CounterMetricFamily appends _total to the exposed sample name.
    assert (
        samples[("ray_tenant_tasks_enqueued_total", (("tenant_id", "tenant-a"),))] == 4
    )
    assert (
        samples[("ray_tenant_tasks_succeeded_total", (("tenant_id", "tenant-a"),))] == 3
    )
    assert samples[("ray_tenant_tasks_failed_total", (("tenant_id", "tenant-a"),))] == 1


def test_document_counters_exposed_from_stats():
    samples, _ = _collect_samples()
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
    samples, _ = _collect_samples()
    # tenant-b has no live tasks but its cumulative counters must still appear,
    # otherwise rate()/increase() would see a phantom counter reset.
    assert (
        samples[("ray_tenant_tasks_succeeded_total", (("tenant_id", "tenant-b"),))] == 7
    )


def test_snapshot_gauges_report_current_depth():
    samples, _ = _collect_samples()
    assert samples[("ray_tenant_tasks_pending", (("tenant_id", "tenant-a"),))] == 2
    assert samples[("ray_tenant_tasks_active", (("tenant_id", "tenant-a"),))] == 1
    # totals
    assert samples[("ray_total_tasks_pending", ())] == 2
    assert samples[("ray_total_tasks_active", ())] == 1


def test_removed_lossy_metrics_are_gone():
    _, text = _collect_samples()
    # The old transient "running" gauge (and its total) lost data and is fully
    # removed; "dispatched" now lives on as a monotonic counter instead.
    assert "ray_tenant_tasks_running" not in text
    assert "ray_total_tasks_running" not in text


def test_collect_from_manager_uses_single_manager_and_unions_tenants():
    """The gather opens no per-call connections and scrapes the tenant union."""
    manager = AsyncMock()
    manager.max_connections = 50
    manager.get_all_tenants_with_any_tasks.return_value = ["tenant-a"]
    manager.get_all_tenants_with_task_counters.return_value = ["tenant-a", "tenant-b"]
    manager.get_tenant_task_counters.side_effect = lambda t: TenantTaskCounters(
        tasks_enqueued_total=1
    )
    manager.get_tenant_stats.side_effect = lambda t: TenantStats(total_documents=3)
    manager.get_tenant_queue_size.side_effect = lambda t: 5
    manager.get_tenant_active_task_count.side_effect = lambda t: 1
    manager.get_tenant_limits.side_effect = lambda t: TenantLimits()

    data = asyncio.run(_collect_from_manager(manager))

    assert data.num_tenants_with_any == 1
    assert {s.tenant_id for s in data.tenants} == {"tenant-a", "tenant-b"}
    # connect/disconnect are owned by collect_metrics_data, not the gather.
    manager.connect.assert_not_called()
    manager.disconnect.assert_not_called()


def test_collect_from_manager_skips_tenant_that_errors():
    manager = AsyncMock()
    manager.max_connections = 50
    manager.get_all_tenants_with_any_tasks.return_value = ["good", "bad"]
    manager.get_all_tenants_with_task_counters.return_value = []

    def _counters(tenant_id):
        if tenant_id == "bad":
            raise RuntimeError("redis blew up")
        return TenantTaskCounters(tasks_enqueued_total=1)

    manager.get_tenant_task_counters.side_effect = _counters
    manager.get_tenant_stats.side_effect = lambda t: TenantStats()
    manager.get_tenant_queue_size.side_effect = lambda t: 0
    manager.get_tenant_active_task_count.side_effect = lambda t: 0
    manager.get_tenant_limits.side_effect = lambda t: TenantLimits()

    data = asyncio.run(_collect_from_manager(manager))

    # The failing tenant is dropped; the healthy one still reported.
    assert {s.tenant_id for s in data.tenants} == {"good"}

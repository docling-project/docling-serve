"""Tests for the RayCollector Prometheus exposition.

Verifies that the monotonic lifecycle counters are exposed (with the Prometheus
``_total`` suffix), that a tenant which is idle but still has cumulative counters
keeps being scraped, and that the snapshot gauges report current depth. The
collector queries Redis via ``run_async_with_new_connection`` (a thread-pool that
opens a fresh connection); here that helper is patched to call the mocked
manager's method directly, keeping the test hermetic.
"""

from unittest.mock import MagicMock, patch

from prometheus_client import CollectorRegistry, generate_latest
from prometheus_client.parser import text_string_to_metric_families

from docling_jobkit.orchestrators.ray.models import TenantLimits, TenantTaskCounters

from docling_serve.ray_metrics_collector import RayCollector


def _sync_shim(redis_manager, coro_func, *args, **kwargs):
    """Call the (mocked) manager method directly instead of in a thread."""
    return coro_func(*args, **kwargs)


def _make_manager():
    manager = MagicMock()
    manager.get_all_tenants_with_any_tasks = MagicMock(return_value=["tenant-a"])
    # tenant-b is idle (no live tasks) but still carries cumulative counters.
    manager.get_all_tenants_with_task_counters = MagicMock(
        return_value=["tenant-a", "tenant-b"]
    )

    counters = {
        "tenant-a": TenantTaskCounters(
            tasks_enqueued_total=4,
            tasks_dispatched_total=4,
            tasks_started_total=4,
            tasks_succeeded_total=3,
            tasks_failed_total=1,
        ),
        "tenant-b": TenantTaskCounters(tasks_enqueued_total=7, tasks_succeeded_total=7),
    }
    queue_size = {"tenant-a": 2, "tenant-b": 0}
    active = {"tenant-a": 1, "tenant-b": 0}

    manager.get_tenant_task_counters = MagicMock(side_effect=lambda t: counters[t])
    manager.get_tenant_queue_size = MagicMock(side_effect=lambda t: queue_size[t])
    manager.get_tenant_active_task_count = MagicMock(side_effect=lambda t: active[t])
    manager.get_tenant_limits = MagicMock(side_effect=lambda t: TenantLimits())
    return manager


# RayCollector.__init__ registers a Summary on the global registry, so it can
# only be built once per process. Cache the collection result across tests.
_CACHE: dict = {}


def _collect_samples():
    if _CACHE:
        return _CACHE["samples"], _CACHE["text"]

    manager = _make_manager()
    registry = CollectorRegistry()
    with patch(
        "docling_serve.ray_metrics_collector.run_async_with_new_connection",
        _sync_shim,
    ):
        registry.register(RayCollector(manager))
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

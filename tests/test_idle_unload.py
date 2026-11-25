# SPDX-License-Identifier: MIT

import asyncio
import ctypes
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from hypothesis import given, settings, strategies as st

from docling_serve import idle_unload as idle


def controller(timeout=10):
    orchestrator = SimpleNamespace(
        task_queue=asyncio.Queue(), clear_converters=AsyncMock()
    )
    return orchestrator, idle.IdleModelUnloader(orchestrator, timeout)


@settings(max_examples=1000, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["put", "get", "done", "tick", "clean"]),
            st.integers(min_value=0),
        )
    ),
    st.floats(min_value=0, exclude_min=True, allow_infinity=False, allow_nan=False),
)
def test_activity_schedule(events, timeout):
    async def scenario():
        now, last, queued, active, armed, cleanups = 0, 0, 0, 0, True, 0
        with (
            patch.object(idle.time, "monotonic", side_effect=lambda: now),
            patch.object(idle, "release_memory", return_value=True),
        ):
            orch, unloader = controller(timeout)
            for event, amount in events[:64]:
                if event == "put":
                    await orch.task_queue.put("job")
                    queued += 1
                    armed = True
                elif event == "get" and queued:
                    assert await orch.task_queue.get() == "job"
                    queued -= 1
                    active += 1
                elif event == "done" and active:
                    orch.task_queue.task_done()
                    active -= 1
                    last = now
                elif event == "tick":
                    now += min(amount, 1000000)
                elif event == "clean":
                    expected = armed and queued + active == 0 and now - last >= timeout
                    assert await unloader.unload_if_idle() == expected
                    if expected:
                        cleanups += 1
                        armed = False
                assert orch.clear_converters.await_count == cleanups

    asyncio.run(scenario())


async def test_deadline_overlap_rearm_and_stop(monkeypatch):
    now = 0
    monkeypatch.setattr(idle.time, "monotonic", lambda: now)
    monkeypatch.setattr(idle, "release_memory", lambda: True)
    orch, unloader = controller()
    for _ in range(2):
        orch.task_queue.put_nowait("job")
        await orch.task_queue.get()
    now = 100
    assert not await unloader.unload_if_idle()
    orch.task_queue.task_done()
    assert not await unloader.unload_if_idle()
    orch.task_queue.task_done()  # includes failed conversions' finally blocks
    now = 109
    assert not await unloader.unload_if_idle()
    now = 110
    assert await unloader.unload_if_idle()
    assert not await unloader.unload_if_idle()
    orch.task_queue.put_nowait("next")
    assert await orch.task_queue.get() == "next"
    orch.task_queue.task_done()
    now = 120
    assert await unloader.unload_if_idle()
    unloader.stop()
    now = 200
    assert not await unloader.unload_if_idle()
    with pytest.raises(ValueError):
        orch.task_queue.task_done()


async def test_arrival_during_cleanup_waits_and_rearms(monkeypatch):
    now = 0
    monkeypatch.setattr(idle.time, "monotonic", lambda: now)
    monkeypatch.setattr(idle, "release_memory", lambda: True)
    orch, unloader = controller()
    started, release = asyncio.Event(), asyncio.Event()

    async def clear():
        started.set()
        await release.wait()

    orch.clear_converters.side_effect = clear
    now = 10
    cleanup = asyncio.create_task(unloader.unload_if_idle())
    await started.wait()
    orch.task_queue.put_nowait("next")
    worker = asyncio.create_task(orch.task_queue.get())
    await asyncio.sleep(0)
    assert not worker.done()
    release.set()
    assert await cleanup
    assert await worker == "next"
    orch.task_queue.task_done()
    now = 20
    assert await unloader.unload_if_idle()


@pytest.mark.parametrize("failure", ["clear", "allocator"])
async def test_failure_retries_after_interval(monkeypatch, failure):
    now = 0
    monkeypatch.setattr(idle.time, "monotonic", lambda: now)
    release = Mock(return_value=failure != "allocator")
    monkeypatch.setattr(idle, "release_memory", release)
    orch, unloader = controller()
    if failure == "clear":
        orch.clear_converters.side_effect = RuntimeError("retry")
    now = 10
    assert not await unloader.unload_if_idle()
    assert release.call_count == 1
    now = 19
    assert not await unloader.unload_if_idle()
    orch.clear_converters.side_effect = None
    release.return_value = True
    now = 20
    assert await unloader.unload_if_idle()


def test_requires_empty_prestart_queue():
    orch, _ = controller()
    orch.task_queue.put_nowait("queued")
    with pytest.raises(ValueError):
        idle.IdleModelUnloader(orch, 1)


@pytest.mark.parametrize("torch_kind", ["absent", "unified", "cuda", "cold"])
def test_allocator_signatures_and_initialized_devices(monkeypatch, torch_kind):
    funcs = {
        name: Mock()
        for name in ("mi_collect", "malloc_trim", "malloc_zone_pressure_relief")
    }
    monkeypatch.setattr(idle.ctypes, "CDLL", lambda _: SimpleNamespace(**funcs))
    empty_cache = Mock()
    torch = (
        SimpleNamespace(accelerator=SimpleNamespace(empty_cache=empty_cache))
        if torch_kind == "unified"
        else SimpleNamespace(
            cuda=SimpleNamespace(
                is_initialized=lambda: torch_kind == "cuda", empty_cache=empty_cache
            )
        )
    )
    with patch.dict(sys.modules):
        if torch_kind == "absent":
            sys.modules.pop("torch", None)
        else:
            sys.modules["torch"] = torch
        assert idle.release_memory()
        assert ("torch" in sys.modules) == (torch_kind != "absent")
    assert empty_cache.call_count == int(torch_kind in ("unified", "cuda"))
    funcs["mi_collect"].assert_called_once_with(True)
    assert funcs["mi_collect"].argtypes == [ctypes.c_bool]
    assert funcs["mi_collect"].restype is None
    funcs["malloc_trim"].assert_called_once_with(0)
    assert funcs["malloc_trim"].argtypes == [ctypes.c_size_t]
    assert funcs["malloc_trim"].restype is ctypes.c_int
    funcs["malloc_zone_pressure_relief"].assert_called_once_with(None, 0)
    assert funcs["malloc_zone_pressure_relief"].argtypes == [
        ctypes.c_void_p,
        ctypes.c_size_t,
    ]
    assert funcs["malloc_zone_pressure_relief"].restype is ctypes.c_size_t


def test_missing_symbols_and_independent_failure(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    monkeypatch.setattr(idle.ctypes, "CDLL", lambda _: SimpleNamespace())
    assert idle.release_memory()
    trim = Mock()
    monkeypatch.setattr(
        idle.ctypes,
        "CDLL",
        lambda _: SimpleNamespace(
            mi_collect=Mock(side_effect=RuntimeError()), malloc_trim=trim
        ),
    )
    assert not idle.release_memory()
    trim.assert_called_once_with(0)


async def test_real_converter_caches_release_and_lazy_rebuild(monkeypatch, tmp_path):
    import weakref

    from docling.datamodel.service.options import ConvertDocumentsOptions
    from docling_jobkit.convert.manager import (
        DoclingConverterManager,
        DoclingConverterManagerConfig,
    )
    from docling_jobkit.orchestrators.local.orchestrator import (
        LocalOrchestrator,
        LocalOrchestratorConfig,
    )

    class LightweightConverter:
        def __init__(self, **kwargs):
            pass

    monkeypatch.setattr(
        "docling_jobkit.convert.manager.DocumentConverter", LightweightConverter
    )
    monkeypatch.setattr(idle, "release_memory", lambda: True)
    now = 0
    monkeypatch.setattr(idle.time, "monotonic", lambda: now)
    managers = [
        DoclingConverterManager(DoclingConverterManagerConfig()) for _ in range(2)
    ]
    orch = LocalOrchestrator(LocalOrchestratorConfig(scratch_dir=tmp_path), managers[0])
    orch.worker_cms.append(managers[1])
    options = managers[0].get_pdf_pipeline_opts(ConvertDocumentsOptions())
    refs = [weakref.ref(cm.get_converter(options)) for cm in managers]
    live = managers[1].get_converter(options)
    unloader = idle.IdleModelUnloader(orch, 1)
    now = 1
    assert await unloader.unload_if_idle()
    assert refs[0]() is None
    assert refs[1]() is live  # active external references are never destroyed
    assert managers[1].get_converter(options) is not live
    assert managers[0].get_converter(options) is not None


async def test_cancelled_admission_preserves_queued_job():
    orch, unloader = controller()
    async with unloader.lock:
        orch.task_queue.put_nowait("retained")
        admission = asyncio.create_task(orch.task_queue.get())
        await asyncio.sleep(0)
        orch.task_queue.put_nowait("second")
        admission.cancel()
        with pytest.raises(asyncio.CancelledError):
            await admission
    assert orch.task_queue.get_nowait() == "retained"
    orch.task_queue.task_done()
    assert orch.task_queue.get_nowait() == "second"
    orch.task_queue.task_done()
    await asyncio.wait_for(orch.task_queue.join(), 1)


def test_gc_failure_does_not_suppress_native_cleanup(monkeypatch):
    monkeypatch.setitem(sys.modules, "torch", None)
    trim = Mock()
    monkeypatch.setattr(idle.gc, "collect", Mock(side_effect=RuntimeError("gc")))
    monkeypatch.setattr(
        idle.ctypes, "CDLL", lambda _: SimpleNamespace(malloc_trim=trim)
    )
    assert not idle.release_memory()
    trim.assert_called_once_with(0)


def test_device_failure_still_purges_native_pages(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "torch",
        SimpleNamespace(
            accelerator=SimpleNamespace(
                empty_cache=Mock(side_effect=RuntimeError("device"))
            )
        ),
    )
    trim = Mock(return_value=0)
    monkeypatch.setattr(
        idle.ctypes, "CDLL", lambda _: SimpleNamespace(malloc_trim=trim)
    )
    assert not idle.release_memory()
    trim.assert_called_once_with(0)


async def test_timer_stops_and_uses_retry_deadline(monkeypatch):
    now = 0
    monkeypatch.setattr(idle.time, "monotonic", lambda: now)
    orch, unloader = controller()
    orch.clear_converters.side_effect = RuntimeError("retry")
    monkeypatch.setattr(idle, "release_memory", lambda: True)
    now = 10
    with patch.object(
        idle.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)
    ) as sleep:
        with pytest.raises(asyncio.CancelledError):
            await unloader.run()
        sleep.assert_awaited_once_with(10)
    unloader.stop()
    await unloader.run()


async def test_cancel_yielding_cleanup_releases_gate_without_native_purge(monkeypatch):
    now = 0
    monkeypatch.setattr(idle.time, "monotonic", lambda: now)
    orch, unloader = controller()
    entered = asyncio.Event()

    async def clear():
        entered.set()
        await asyncio.Event().wait()

    orch.clear_converters.side_effect = clear
    release = Mock()
    monkeypatch.setattr(idle, "release_memory", release)
    now = 10
    task = asyncio.create_task(unloader.run())
    await entered.wait()
    unloader.stop()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.assert_not_called()
    orch.task_queue.put_nowait("retained")
    assert await orch.task_queue.get() == "retained"
    orch.task_queue.task_done()


async def test_windows_cleanup_runs_once_without_process_symbol_lookup(monkeypatch):
    now = 0
    monkeypatch.setattr(idle.time, "monotonic", lambda: now)
    collect, empty_cache = Mock(), Mock()
    monkeypatch.setattr(idle.gc, "collect", collect)
    torch = SimpleNamespace(accelerator=SimpleNamespace(empty_cache=empty_cache))
    monkeypatch.setattr(
        idle, "sys", SimpleNamespace(platform="win32", modules={"torch": torch})
    )
    lookup = Mock(side_effect=TypeError("CDLL(None) is unsupported on Windows"))
    monkeypatch.setattr(idle.ctypes, "CDLL", lookup)
    orch, unloader = controller()
    now = 10
    assert await unloader.unload_if_idle()
    now = 20
    assert not await unloader.unload_if_idle()
    orch.clear_converters.assert_awaited_once()
    collect.assert_called_once_with()
    empty_cache.assert_called_once_with()
    lookup.assert_not_called()

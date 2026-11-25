# SPDX-License-Identifier: MIT

"""Opt-in local-engine cache cleanup after all jobs have been idle."""

import asyncio
import ctypes
import gc
import logging
import sys
import time
from typing import TYPE_CHECKING

import psutil

if TYPE_CHECKING:
    from docling_jobkit.orchestrators.local.orchestrator import LocalOrchestrator

_log = logging.getLogger(__name__)


def release_memory() -> bool:
    """Purge unused caches without importing torch or loading another allocator."""
    success = True
    try:
        gc.collect()
    except Exception:
        _log.warning("Unable to collect Python cycles", exc_info=True)
        success = False
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            accelerator = getattr(torch, "accelerator", None)
            if accelerator is not None and hasattr(accelerator, "empty_cache"):
                accelerator.empty_cache()  # no-op when its allocator is uninitialized
            elif hasattr(torch, "cuda") and torch.cuda.is_initialized():
                torch.cuda.empty_cache()
        except Exception:
            _log.warning("Unable to release device cache", exc_info=True)
            success = False
    if sys.platform == "win32":
        return success  # CDLL(None) is unavailable; Python/device cleanup still ran.
    try:
        process = ctypes.CDLL(None)
        for name, argtypes, restype, args in (
            ("mi_collect", [ctypes.c_bool], None, (True,)),
            ("malloc_trim", [ctypes.c_size_t], ctypes.c_int, (0,)),
            (
                "malloc_zone_pressure_relief",
                [ctypes.c_void_p, ctypes.c_size_t],
                ctypes.c_size_t,
                (None, 0),
            ),
        ):
            function = getattr(process, name, None)
            if function is not None:
                try:
                    function.argtypes = argtypes
                    function.restype = restype
                    function(*args)
                except Exception:
                    _log.warning(
                        "Unable to release allocator cache via %s", name, exc_info=True
                    )
                    success = False
    except OSError:
        _log.warning("Unable to inspect process allocator symbols", exc_info=True)
        success = False
    return success


class _ActivityQueue(asyncio.Queue[str]):
    def __init__(self, owner: "IdleModelUnloader"):
        super().__init__()
        self.owner = owner
        self.outstanding = 0
        self.available = asyncio.Event()

    def put_nowait(self, item: str) -> None:
        super().put_nowait(item)
        self.outstanding += 1
        self.owner.armed = True
        self.available.set()

    async def get(self) -> str:
        # Wait outside the gate, then dequeue under it. Cancellation never takes a job.
        while True:
            await self.available.wait()
            async with self.owner.lock:
                if not self.empty():
                    item = super().get_nowait()
                    if self.empty():
                        self.available.clear()
                    return item
                self.available.clear()

    def task_done(self) -> None:
        super().task_done()
        self.outstanding -= 1
        self.owner.last_activity = time.monotonic()


class IdleModelUnloader:
    """Install before local workers start; stop before cancelling those workers."""

    def __init__(self, orchestrator: "LocalOrchestrator", timeout: float):
        if not orchestrator.task_queue.empty() or getattr(
            orchestrator.task_queue, "_unfinished_tasks", 0
        ):
            raise ValueError("Idle unloading requires an empty pre-start local queue")
        self.orchestrator = orchestrator
        self.timeout = timeout
        self.lock = asyncio.Lock()
        self.last_activity = time.monotonic()
        self.retry_after = self.last_activity
        self.armed = True
        self.stopped = False
        self.queue = _ActivityQueue(self)
        orchestrator.task_queue = self.queue

    def stop(self) -> None:
        self.stopped = True

    async def unload_if_idle(self) -> bool:
        async with self.lock:
            now = time.monotonic()
            if (
                self.stopped
                or not self.armed
                or self.queue.outstanding
                or now - self.last_activity < self.timeout
                or now < self.retry_after
            ):
                return False
            try:
                before = psutil.Process().memory_info().rss
                success = True
                try:
                    await self.orchestrator.clear_converters()
                except Exception:
                    _log.warning("Unable to clear converter caches", exc_info=True)
                    success = False
                success = release_memory() and success
                after = psutil.Process().memory_info().rss
                _log.info(
                    "Idle model cleanup: RSS before=%d after=%d released=%d bytes",
                    before,
                    after,
                    before - after,
                )
                if not success:
                    raise RuntimeError("An idle memory cleanup stage failed")
            except Exception:
                _log.warning("Idle model cleanup failed; will retry", exc_info=True)
                self.retry_after = time.monotonic() + self.timeout
                return False
            # Enqueues may have arrived while clear_converters yielded.
            self.armed = bool(self.queue.outstanding)
            return True

    async def run(self) -> None:
        while not self.stopped:
            await self.unload_if_idle()
            delay = self.timeout
            if self.armed and not self.queue.outstanding:
                delay = (
                    max(self.last_activity + self.timeout, self.retry_after)
                    - time.monotonic()
                )
            await asyncio.sleep(max(delay, 0))

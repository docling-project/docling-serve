"""Cached capacity snapshot for the /v1/capacity endpoint."""

import time
from typing import Optional

from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
    SystemCapacity,
)

_cached: Optional[SystemCapacity] = None
_cached_at: float = 0.0
_CACHE_TTL: float = 2.0


async def get_cached_capacity(
    orchestrator: BaseOrchestrator,
) -> Optional[SystemCapacity]:
    global _cached, _cached_at
    now = time.monotonic()
    if _cached is None or (now - _cached_at) > _CACHE_TTL:
        _cached = await orchestrator.get_capacity()
        _cached_at = now
    return _cached

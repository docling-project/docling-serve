from functools import lru_cache

from docling_serve.engines.async_local.orchestrator import AsyncLocalOrchestrator


@lru_cache
def get_orchestrator() -> AsyncLocalOrchestrator:
    return AsyncLocalOrchestrator()

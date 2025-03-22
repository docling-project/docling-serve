from functools import lru_cache

from docling_serve.datamodel.engines import AsyncEngine
from docling_serve.engines.async_orchestrator import BaseAsyncOrchestrator
from docling_serve.settings import docling_serve_settings


@lru_cache
def get_async_orchestrator() -> BaseAsyncOrchestrator:
    if docling_serve_settings.eng_kind == AsyncEngine.LOCAL:
        from docling_serve.engines.async_local.orchestrator import (
            AsyncLocalOrchestrator,
        )

        return AsyncLocalOrchestrator()
    elif docling_serve_settings.eng_kind == AsyncEngine.KFP:
        from docling_serve.engines.async_kfp.orchestrator import AsyncKfpOrchestrator

        return AsyncKfpOrchestrator()

    raise RuntimeError(f"Engine {docling_serve_settings.eng_kind} not recognized.")

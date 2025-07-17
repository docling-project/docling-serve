from functools import lru_cache

from docling_jobkit.orchestrators.base_orchestrator import BaseOrchestrator

from docling_serve.settings import AsyncEngine, docling_serve_settings


@lru_cache
def get_async_orchestrator() -> BaseOrchestrator:
    if docling_serve_settings.eng_kind == AsyncEngine.LOCAL:
        from docling_jobkit.convert.manager import (
            DoclingConverterManager,
            DoclingConverterManagerConfig,
        )
        from docling_jobkit.orchestrators.local.orchestrator import (
            LocalOrchestrator,
            LocalOrchestratorConfig,
        )

        local_config = LocalOrchestratorConfig(
            num_workers=docling_serve_settings.eng_loc_num_workers,
        )

        cm_config = DoclingConverterManagerConfig(
            artifacts_path=docling_serve_settings.artifacts_path,
            options_cache_size=docling_serve_settings.options_cache_size,
            enable_remote_services=docling_serve_settings.enable_remote_services,
            allow_external_plugins=docling_serve_settings.allow_external_plugins,
            max_num_pages=docling_serve_settings.max_num_pages,
            max_file_size=docling_serve_settings.max_file_size,
        )
        cm = DoclingConverterManager(config=cm_config)

        return LocalOrchestrator(config=local_config, converter_manager=cm)
    elif docling_serve_settings.eng_kind == AsyncEngine.KFP:
        from docling_jobkit.orchestrators.kfp.orchestrator import (
            KfpOrchestrator,
            KfpOrchestratorConfig,
        )

        kfp_config = KfpOrchestratorConfig(
            endpoint=docling_serve_settings.eng_kfp_endpoint,
            token=docling_serve_settings.eng_kfp_token,
            ca_cert_path=docling_serve_settings.eng_kfp_ca_cert_path,
            self_callback_endpoint=docling_serve_settings.eng_kfp_self_callback_endpoint,
            self_callback_token_path=docling_serve_settings.eng_kfp_self_callback_token_path,
            self_callback_ca_cert_path=docling_serve_settings.eng_kfp_self_callback_ca_cert_path,
        )

        return KfpOrchestrator(config=kfp_config)

    raise RuntimeError(f"Engine {docling_serve_settings.eng_kind} not recognized.")

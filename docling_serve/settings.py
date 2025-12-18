import enum
import sys
from pathlib import Path
from typing import Optional, Union

from pydantic import AnyUrl, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


class UvicornSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="UVICORN_", env_file=".env", extra="allow"
    )

    host: str = "0.0.0.0"
    port: int = 5001
    reload: bool = False
    root_path: str = ""
    proxy_headers: bool = True
    timeout_keep_alive: int = 60
    ssl_certfile: Optional[Path] = None
    ssl_keyfile: Optional[Path] = None
    ssl_keyfile_password: Optional[str] = None
    workers: Union[int, None] = None


class AsyncEngine(str, enum.Enum):
    LOCAL = "local"
    KFP = "kfp"
    RQ = "rq"


class DoclingServeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCLING_SERVE_",
        env_file=".env",
        env_parse_none_str="",
        extra="allow",
    )

    enable_ui: bool = False
    api_host: str = "localhost"
    artifacts_path: Optional[Path] = None
    static_path: Optional[Path] = None
    scratch_path: Optional[Path] = None
    single_use_results: bool = True
    result_removal_delay: float = 300  # 5 minutes
    load_models_at_boot: bool = True
    options_cache_size: int = 2
    enable_remote_services: bool = False
    allow_external_plugins: bool = False
    show_version_info: bool = True

    api_key: str = ""

    max_document_timeout: float = 3_600 * 24 * 7  # 7 days
    max_num_pages: int = sys.maxsize
    max_file_size: int = sys.maxsize

    # Threading pipeline
    queue_max_size: Optional[int] = None
    ocr_batch_size: Optional[int] = None
    layout_batch_size: Optional[int] = None
    table_batch_size: Optional[int] = None
    batch_polling_interval_seconds: Optional[float] = None

    sync_poll_interval: int = 2  # seconds
    max_sync_wait: int = 120  # 2 minutes

    cors_origins: list[str] = ["*"]
    cors_methods: list[str] = ["*"]
    cors_headers: list[str] = ["*"]

    eng_kind: AsyncEngine = AsyncEngine.LOCAL
    # Local engine
    eng_loc_num_workers: int = 2
    eng_loc_share_models: bool = False
    # RQ engine
    eng_rq_redis_url: str = ""
    eng_rq_results_prefix: str = "docling:results"
    eng_rq_sub_channel: str = "docling:updates"
    # KFP engine
    eng_kfp_endpoint: Optional[AnyUrl] = None
    eng_kfp_token: Optional[str] = None
    eng_kfp_ca_cert_path: Optional[str] = None
    eng_kfp_self_callback_endpoint: Optional[str] = None
    eng_kfp_self_callback_token_path: Optional[Path] = None
    eng_kfp_self_callback_ca_cert_path: Optional[Path] = None

    eng_kfp_experimental: bool = False

    # OpenTelemetry settings
    otel_enable_metrics: bool = True
    otel_enable_traces: bool = True
    otel_enable_prometheus: bool = True
    otel_enable_otlp_metrics: bool = False
    otel_service_name: str = "docling-serve"

    @model_validator(mode="after")
    def engine_settings(self) -> Self:
        # Validate KFP engine settings
        if self.eng_kind == AsyncEngine.KFP:
            if self.eng_kfp_endpoint is None:
                raise ValueError("KFP endpoint is required when using the KFP engine.")

        if self.eng_kind == AsyncEngine.KFP:
            if not self.eng_kfp_experimental:
                raise ValueError(
                    "KFP is not yet working. To enable the development version, you must set DOCLING_SERVE_ENG_KFP_EXPERIMENTAL=true."
                )

        if self.eng_kind == AsyncEngine.RQ:
            if not self.eng_rq_redis_url:
                raise ValueError("RQ Redis url is required when using the RQ engine.")

        return self


uvicorn_settings = UvicornSettings()
docling_serve_settings = DoclingServeSettings()

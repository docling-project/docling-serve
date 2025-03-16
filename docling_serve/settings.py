from pathlib import Path
from typing import Optional, Union

from pydantic_settings import BaseSettings, SettingsConfigDict

from docling_serve.datamodel.engines import AsyncEngine


class UvicornSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="UVICORN_", env_file=".env", extra="allow"
    )

    host: str = "0.0.0.0"
    port: int = 5001
    reload: bool = False
    root_path: str = ""
    proxy_headers: bool = True
    workers: Union[int, None] = None


class DoclingServeSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCLING_SERVE_",
        env_file=".env",
        env_parse_none_str="",
        extra="allow",
    )

    enable_ui: bool = False
    artifacts_path: Optional[Path] = None
    options_cache_size: int = 2

    eng_kind: AsyncEngine = AsyncEngine.LOCAL
    eng_loc_num_workers: int = 2


uvicorn_settings = UvicornSettings()
docling_serve_settings = DoclingServeSettings()

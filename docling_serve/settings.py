from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DOCLING_",
        env_file="docling_serve/.env",
    )
    document_timeout: Optional[float] = None

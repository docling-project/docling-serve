import tempfile
from functools import lru_cache
from pathlib import Path

from docling_serve.settings import docling_serve_settings


@lru_cache
def get_scratch() -> Path:
    scratch_dir = (
        docling_serve_settings.scratch_path
        if docling_serve_settings.scratch_path is not None
        else Path(tempfile.mkdtemp(prefix="docling_"))
    )
    scratch_dir.mkdir(exist_ok=True, parents=True)
    return scratch_dir

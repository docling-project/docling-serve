import os

from docling_serve.app import app
from docling_serve.helper_functions import _str_to_bool

# Launch the FastAPI server
if __name__ == "__main__":
    from uvicorn import run

    port = int(os.getenv("PORT", "5001"))
    workers = int(os.getenv("UVICORN_WORKERS", "1"))
    reload = _str_to_bool(os.getenv("RELOAD", "False"))
    run(
        app,
        host="0.0.0.0",
        port=port,
        workers=workers,
        timeout_keep_alive=600,
        reload=reload,
    )

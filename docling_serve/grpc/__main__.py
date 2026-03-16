import asyncio
import logging
import platform
import sys
from typing import Annotated

import typer
from rich.console import Console

from docling_serve.settings import docling_serve_settings

from .server import serve

console = Console()
err_console = Console(stderr=True)
app = typer.Typer(no_args_is_help=True, rich_markup_mode="rich")


@app.command()
def run(
    host: Annotated[
        str,
        typer.Option(help="Host to bind the gRPC server."),
    ] = "0.0.0.0",
    port: Annotated[
        int,
        typer.Option(help="Port to bind the gRPC server."),
    ] = 50051,
    artifacts_path: Annotated[
        str | None,
        typer.Option(
            help=(
                "If set to a valid directory, the model weights will be loaded from this path."
            )
        ),
    ] = None,
) -> None:
    if artifacts_path:
        docling_serve_settings.artifacts_path = artifacts_path

    logging.basicConfig(level=logging.INFO)
    console.print("Starting Docling Serve gRPC server 🚀")
    console.print(f"Listening on [bold]{host}:{port}[/]")
    asyncio.run(serve(host=host, port=port))


@app.command()
def version() -> None:
    console.print(
        f"Python: {platform.python_version()} ({sys.implementation.cache_tag})"
    )


def main() -> None:
    app()


if __name__ == "__main__":
    main()

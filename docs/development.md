# Development

## Install dependencies

### CPU only

```sh
# Install uv if not already available
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync --extra cpu
```

### Cuda GPU

For GPU support use the following command:

```sh
# Install dependencies
uv sync
```

### Gradio UI and different OCR backends

`/ui` endpoint using `gradio` and different OCR backends can be enabled via package extras:

```sh
# Enable ui and rapidocr
uv sync --extra ui --extra rapidocr
```

```sh
# Enable tesserocr
uv sync --extra tesserocr
```

See `[project.optional-dependencies]` section in `pyproject.toml` for full list of options and runtime options with `uv run docling-serve --help`.

### Run the server

The `docling-serve` executable is a convenient script for launching the webserver both in
development and production mode.

```sh
# Run the server in development mode
# - reload is enabled by default
# - listening on the 127.0.0.1 address
# - ui is enabled by default
docling-serve dev

# Run the server in production mode
# - reload is disabled by default
# - listening on the 0.0.0.0 address
# - ui is disabled by default
docling-serve run
```

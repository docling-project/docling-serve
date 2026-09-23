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

### Different OCR backends

Different OCR backends can be enabled via package extras:

```sh
# Enable rapidocr
uv sync --extra rapidocr
```

```sh
# Enable tesserocr
uv sync --extra tesserocr
```

See `[project.optional-dependencies]` section in `pyproject.toml` for full list of options and runtime options with `uv run docling-serve --help`.

### Web UI

The web UI in `ui/` is a React + Vite + TypeScript app styled with Tailwind CSS and shadcn/ui. It uses [`@docling/docling-client`](https://github.com/docling-project/docling-ts) to talk to the API. The production build is written to `docling_serve/ui_static/`, which is included in the wheel and served at `/ui`. Python-only installs never need Node; CI and the container build create the bundle.

```sh
# Build the bundle served by `docling-serve dev` / `docling-serve run --enable-ui`
npm --prefix ui ci
npm --prefix ui run build

# Or develop with hot reload on http://localhost:5173, proxying the API of a
# running docling-serve (default http://localhost:5001, override with DOCLING_SERVE_URL)
npm --prefix ui run dev
```

The UI components in `ui/src/components/ui/` come from shadcn/ui; add more with `npx shadcn@latest add <component>` from the `ui/` directory. The Docling theme colours live in `ui/src/index.css`.

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

# Configuration

### Options

The `docling-serve` executable allows is controlled with both command line
options and environment variables.

<details>
<summary>`docling-serve` help message</summary>

```sh
$ docling-serve dev --help
                                                                                                              
 Usage: docling-serve dev [OPTIONS]                                                                           
                                                                                                              
 Run a Docling Serve app in development mode. 🧪                                                              
 This is equivalent to docling-serve run but with reload                                                      
 enabled and listening on the 127.0.0.1 address.                                                              
                                                                                                              
 Options can be set also with the corresponding ENV variable, with the exception                              
 of --enable-ui, --host and --reload.                                                                         
                                                                                                              
╭─ Options ──────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --host                                   TEXT     The host to serve on. For local development in localhost │
│                                                   use 127.0.0.1. To enable public access, e.g. in a        │
│                                                   container, use all the IP addresses available with       │
│                                                   0.0.0.0.                                                 │
│                                                   [default: 127.0.0.1]                                     │
│ --port                                   INTEGER  The port to serve on. [default: 5001]                    │
│ --reload           --no-reload                    Enable auto-reload of the server when (code) files       │
│                                                   change. This is resource intensive, use it only during   │
│                                                   development.                                             │
│                                                   [default: reload]                                        │
│ --root-path                              TEXT     The root path is used to tell your app that it is being  │
│                                                   served to the outside world with some path prefix set up │
│                                                   in some termination proxy or similar.                    │
│ --proxy-headers    --no-proxy-headers             Enable/Disable X-Forwarded-Proto, X-Forwarded-For,       │
│                                                   X-Forwarded-Port to populate remote address info.        │
│                                                   [default: proxy-headers]                                 │
│ --artifacts-path                          PATH     If set to a valid directory, the model weights will be  │
│                                                    loaded from this path.                                  │
│                                                    [default: None]                                         │
│ --enable-ui        --no-enable-ui                 Enable the development UI. [default: enable-ui]          │
│ --help                                            Show this message and exit.                              │
╰────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
```

</details>

#### Environment variables

The environment variables controlling the `uvicorn` execution can be specified with the `UVICORN_` prefix:

- `UVICORN_WORKERS`: Number of workers to use.
- `UVICORN_RELOAD`: If `True`, this will enable auto-reload when you modify files, useful for development.

The environment variables controlling specifics of the Docling Serve app can be specified with the
`DOCLING_SERVE_` prefix:

- `DOCLING_SERVE_ARTIFACTS_PATH`: if set Docling will use only the local weights of models, for example `/opt/app-root/src/.cache/docling/models`.
- `DOCLING_SERVE_ENABLE_UI`: If `True`, The Gradio UI will be available at `/ui`.

Others:

- `TESSDATA_PREFIX`: Tesseract data location, example `/usr/share/tesseract/tessdata/`.

# Docling Serve Client SDK

`docling-serve-client` is the standalone client SDK distribution for
`docling-serve`.

```python
from docling.service_client import DoclingServiceClient
```

The package depends on the published `docling-serve` package for shared request
and response models.

## Install From A Repo Branch

For now, install this client directly from this repository and select both the git ref and the
client package subdirectory:

```bash
pip install "docling-serve-client @ git+https://github.com/docling-project/docling-serve.git@main#subdirectory=docling-serve-client"
```

## Local Development

From this package directory:

```bash
uv sync
uv run pytest
uv run pre-commit run --all-files
```

## Examples

The package includes its own test fixtures and examples.

```bash
uv run python examples/convert_compat.py
uv run python examples/task_api.py
uv run python examples/batch_and_chunk.py
```

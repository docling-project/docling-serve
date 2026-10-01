# Extraction source/target smoke

Updated 2026-10-01. Historical live verification ran on September 23 using Ray/Redis/MinIO, Granite Vision 4.1 through LM Studio and NuExtract3 GGUF through llama-server. It covered PDF/DOCX matrices, Markdown/HTML, multi-document prefixes, encrypted PDF, selected pages, schema failure and callbacks. NuExtract3's API route is verified.

## Portable local setup

From the Serve repository root, install the locked development environment and smoke-only dependencies:

```bash
uv sync --all-extras
uv pip install python-docx
cp scripts/extraction-smoke.example.yaml extraction-smoke.yaml
```

Start Redis on 6379, MinIO on 9000 and a local Ray cluster (for example, `ray start --head --port=6380`). Create MinIO buckets `source`, `target` and `artifacts`. The example uses local MinIO's test credentials; replace them when needed. Supply existing model services: Granite on 1234 and NuExtract3 llama-server on 1235. A sibling Docling checkout is unnecessary: Serve's lock uses HTTPS Git sources.

```bash
DOCLING_SERVE_CONFIG_FILE=extraction-smoke.yaml \
DOCLING_DEVICE=cpu DOCLINGCORE_ALLOWED_PRIVATE_IPS='["127.0.0.1"]' \
uv run --no-sync docling-serve run --host 127.0.0.1 --port 5001
```

The private-IP override is only for this local HTTP fixture server. Run the matrix in another terminal:

```bash
uv run --no-sync python -m scripts.local_smoke.extraction_matrix \
  --model granite --source file --target inbody
uv run --no-sync python -m scripts.local_smoke.extraction_matrix \
  --model nuextract --source http --target presigned
uv run --no-sync python -m scripts.local_smoke.extraction_matrix \
  --model nuextract --source s3 --target s3 --callback-url
```

Flags: `--doc-format pdf|docx|md|html`, `--page-range 2-3`, `--schema-fail`, repeatable `--s3-doc`, `--engine-url` and `--engine-model`. `SMOKE_PDF_A` selects an alternate local fixture; default is `tests/2206.01062v1.pdf`.

## Expected outcomes

| Case | Expected |
|---|---|
| File/HTTP → in-body/presigned/S3 | Successful extraction and schema-valid items |
| S3 → S3 | One stored JSON document envelope per expanded source; exact counts |
| S3 → in-body/presigned | HTTP 422 admission rejection |
| NuExtract3 on DOCX/Markdown/HTML | One document-scoped text result |
| Granite on unpaginated text | Explicit channel failure |
| `--schema-fail` | Kept raw text, validation failed, no extracted data, failed document |
| `--page-range 2-3` | Ordered page 2 then page 3 scopes |
| Callbacks | Expected event counts and artifacts present before document completion; arrival order is not guaranteed |

The October 1 script fixes require an actual HTTP 422 for expected rejection; unrelated network/polling errors cannot pass. Offline callback checks live in `tests/test_extraction_smoke.py`. Fixtures/services and run outputs are local; only the extraction runners, shared helper, safe configuration example and this handoff belong in Git. Each live run uses a fresh storage prefix and does not delete previous artifacts.

The smaller `scripts/smoke_extraction_lmstudio.py` runner and `scripts/local_smoke/extraction_s3_to_s3_lmstudio.py` also remain available. The latter submits an inline file to S3 despite its historical filename. The benchmark harness now lives in the standalone [docling-extractbench repository](https://github.ibm.com/docling-project/docling-extractbench/), with its own README and locked dependencies.

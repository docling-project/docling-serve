# Document Streaming (fork-owned)

This is the gRPC-native streaming contract discussed with Docling Studio
([docling-serve#563](https://github.com/docling-project/docling-serve/issues/563)).
Upstream REST remains submit+poll / WebSocket. **This stream is owned by the
fork** — we are not blocking on upstream merge of the experimental gRPC PRs.

## Why cut the cord

Maintainer silence on #504 / #546 means waiting for an official green light
blocks Studio live-mode and Pipestream embedding pipelines indefinitely. The
streaming envelope only **imports** `ai.docling.core.v1` types, so keeping
pace with docling-core is a proto regen + converter parity pass — not a
fork of the document model.

## Contract

Proto: `proto/ai/docling/serve/v1/docling_serve_stream.proto`

```text
DoclingStreamingService.StreamDocument
  → stream StreamDocumentResponse   # the DocumentStreamEnvelope
```

`StreamDocumentResponse` oneof payload:

| Arm | Purpose | Phase |
|-----|---------|-------|
| `status` | Queue / phase / batch counters / progress % | 1 (now) |
| `source_result` | Per-source success/failure | 1 (now, single-source) |
| `final_document` | Full `DoclingDocument` (core proto) | 1 (now) |
| `error` | Terminal or recoverable errors | 1 (now) |
| `part` (`DocumentNode`) | Live item as it hydrates | 3 (reserved) |

`DocumentNode` reuses core messages (`BaseTextItem`, `TableItem`,
`PictureItem`, …) instead of re-listing every text variant — when core adds
a text kind to `BaseTextItem`, the stream inherits it automatically.

## Emission honesty

- **Phase 1 (implemented):** status around a real convert task, then
  `source_result` + `final_document`. Same underlying orchestrator as unary
  convert / `Watch*`. We do **not** invent page yields from a finished doc.
- **Phase 2:** fan-out `source_result` / `final_document` as each batch
  source completes (jobkit progress callbacks).
- **Phase 3:** emit `DocumentNode` parts when docling/jobkit grow incremental
  hooks. Until then the `part` arm stays unused.

## Sync story

1. Merge / pull docling-core proto updates into the sibling checkout (or
   install the fork wheel).
2. `uv run python scripts/gen_grpc.py`
3. `uv run python scripts/buf_check.py`
4. Run schema validator + converter tests.

Serve REST-parity RPCs stay on `DoclingServeService`. Streaming is a
**separate** service on the same port so experimental clients (Studio,
Connect-ES, Pipestream) can depend on it without coupling to every REST
mirror change.

## Studio / FE bridge

Browsers do not speak raw gRPC. Use Connect-ES or a grpc→SSE bridge; the
envelope's `request_id` + `sequence_number` are designed for multiplexing
and ordered reconstruction after buffering.

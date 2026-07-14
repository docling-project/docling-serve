# gRPC Architecture Discussion Draft

## What This Is

This is a 1:1 gRPC server for Docling Serve that follows the Pydantic model while using gRPC and protobuf conventions. The semantic source of truth is still the Pydantic domain model, and the protobuf IDL is the transport contract for gRPC clients.

## Approach and Feedback Request

We aligned early that a REST to gRPC field by field mirror is not a good design goal by itself. REST and gRPC solve different transport and client needs, so strict endpoint symmetry can make both sides worse.

Instead, the approach is semantic parity: the same document meaning, the same options, and the same outcomes, exposed through a gRPC native API shape. We would like feedback on whether this balance feels right for maintainability and client usability.

## How Mapping and Parity Work

At startup, the gRPC server validates schema compatibility by crawling the Pydantic model and comparing it to protobuf descriptors. This gives fast feedback when model changes happen, and it fails hard on unsafe type drift.

To avoid breakage while the codebase evolves, we explicitly track intentional differences and keep that set small. For example, fallback fields like `label_raw` are proto only on purpose so unknown future enum values do not break clients.

At runtime, conversion is model driven. The server hydrates protobuf messages from Pydantic objects, not from ad hoc JSON transforms. This keeps behavior consistent with the existing application paths and reduces duplicate logic.

In tests, new fields are caught in two places: conversion tests for field level correctness and startup schema validation tests for type/cardinality drift. So when the model changes, both runtime and CI surface mismatches quickly.

Feature parity is preserved because gRPC and REST both execute the same underlying conversion and chunking pipeline. Additional format options are still available, but protobuf remains the primary structured payload.

## Future Direction

Streaming is no longer speculative — see [streaming.md](streaming.md).

The fork owns `DoclingStreamingService.StreamDocument` with a
`StreamDocumentResponse` envelope (`status | source_result | final_document |
error`, plus reserved `part` / `DocumentNode` for pipeline-incremental
yields). Phase 1 is live now without pretending page-by-page hydration.

Still ahead:

- page by page / item yielding once docling/jobkit expose hooks
- Connect-ES / SSE bridge for Docling Studio live bbox overlay
- Java gRPC client preferring the stream over poll-shaped `AsyncOperations`

This lets gRPC clients start consuming useful results earlier, rather than
waiting for full document completion — without coupling Studio to an
unmerged upstream PR.


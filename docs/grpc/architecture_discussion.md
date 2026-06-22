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

A next step is deeper streaming support over gRPC, built around incremental pipeline output:

- page by page yielding during parse and enrichment
- document part yielding for tables, pictures, and text blocks
- live status and progress monitoring streams
- richer partial result streaming for long running jobs

This would let gRPC clients start consuming useful results earlier, rather than waiting for full document completion.


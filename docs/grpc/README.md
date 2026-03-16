# gRPC Support in Docling Serve

The gRPC layer provides a protobuf-based API that mirrors the REST endpoints with 1:1 feature parity. The Pydantic models in docling-serve are the **source of truth**; the gRPC proto definitions and mapping layer adhere to that spec. This design keeps mainline development unchanged—gRPC is a first-class consumer of the same domain models.

**Status:** Experimental. The gRPC server is available as a separate entry point and may evolve as streaming features are added.

## Running the gRPC Server

The gRPC server runs independently from the REST server. Use the `docling-serve-grpc` entry point:

```sh
docling-serve-grpc run --host 0.0.0.0 --port 50051
```

Default port is 50051. The REST server (default port 5001) is not started when running the gRPC server—run them separately if both are needed.

### With the Container Image

Override the entrypoint to start the gRPC server instead of the REST server:

```sh
docker run -p 50051:50051 quay.io/docling-project/docling-serve -- docling-serve-grpc run --host 0.0.0.0 --port 50051
```

## File Upload via FileSource

gRPC does not use multipart form data. File uploads use the `FileSource` message with **base64-encoded content**:

```protobuf
message FileSource {
  string base64_string = 1;  // Base64-encoded file content
  string filename = 2;        // Original filename
}
```

In a `Source` oneof:

```json
{
  "source": {
    "file": {
      "base64_string": "<base64-encoded-bytes>",
      "filename": "document.pdf"
    }
  }
}
```

This is the standard gRPC pattern for binary payloads. Encode your file with base64 before sending; decode on receipt.

## Differences from REST

| Aspect | REST | gRPC |
|--------|------|------|
| **Transport** | HTTP/1.1, JSON | HTTP/2, Protocol Buffers |
| **File upload** | `multipart/form-data` | Base64 in `FileSource.base64_string` |
| **Document conversion** | `POST /v1/convert/source` or `/v1/convert/file` | `ConvertSource` RPC (sources in request body) |
| **Task status** | Poll `GET /v1/status/poll/{id}` or WebSocket `/v1/status/ws/{id}` | `PollTaskStatus` RPC or `Watch*` streaming RPCs |
| **Streaming** | WebSocket for status updates | Server-streaming `WatchConvertSource`, `WatchChunkHierarchicalSource`, etc. |
| **Health** | `GET /health` | `Health` RPC (includes `version` field) |
| **Metrics/version/docs** | `GET /metrics`, `GET /version`, OpenAPI docs | Health RPC returns version; no OpenAPI |

The gRPC API does not expose REST-only endpoints such as `/metrics` or `/version` directly; use the `Health` RPC for version information. For production observability, run the REST server in parallel or use gRPC health checks.

## Protobuf Definitions

Proto files are under `proto/ai/docling/`:

- `serve/v1/docling_serve.proto` – Service and RPC definitions
- `serve/v1/docling_serve_types.proto` – Request/response types, enums
- `core/v1/docling_document.proto` – DoclingDocument structure (document schema)

Regenerate Python stubs with:

```sh
uv run python scripts/gen_grpc.py
```

## End-to-End Testing

Two E2E test scripts are provided. Both require a running gRPC server.

**Start the server:**

```sh
docling-serve-grpc run --port 50051
```

**Python client** (`tests/e2e_grpc_client.py`) — covers Health, ConvertSource, streaming, Watch, JSON/MD export, error paths, async workflow, chunking (hierarchical + hybrid), and admin RPCs:

```sh
uv run python tests/e2e_grpc_client.py [--port 50051] [--pdf PATH]
```

**grpcurl script** (`tests/e2e_grpcurl.sh`) — shell-based tests using grpcurl (starts its own server):

```sh
./tests/e2e_grpcurl.sh [port]
```

PDF-dependent tests use `tests/2206.01062v1.pdf`. If the file is absent, those tests are skipped gracefully. Any PDF can be substituted with the `--pdf` flag.

## Schema Validation

At startup, the gRPC server validates that the `DoclingDocument` protobuf definition matches the Pydantic schema from docling-core. Incompatible type mismatches cause startup failure; new fields in either schema produce warnings. See [schema_validation.md](schema_validation.md) for details. For a reference on the protobuf descriptor API used by the validator, see [descriptor_api_guide.md](descriptor_api_guide.md).

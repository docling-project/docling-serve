### Docling gRPC Architecture & Python Jargon Cheat Sheet

This overview is designed for a Java developer to quickly internalize and present the gRPC implementation in `docling-serve`. It highlights the 1:1 parity with the REST API and the technical "hardening" added to bridge Python's dynamism with gRPC's rigidity.

---

### 🏛️ Architecture Overview

The gRPC server is an extension of the existing `docling-serve` application, sharing the same core logic and configuration.

*   **Service Layer (`server.py`)**: Implements `DoclingServeServiceServicer` using `grpc.aio` (asynchronous gRPC). It acts as the entry point, handling request routing, API key validation, and status streaming.
*   **Shared Orchestrator**: The gRPC server shares a singleton `Orchestrator` instance with the FastAPI/REST server. This ensures that task queuing, model warm-ups, and document processing are consistent across both protocols.
*   **The Contract (`proto/`)**: Protobuf definitions (v3) mirror the Pydantic models used by the REST API. It uses a "wrapper" message style (e.g., `ConvertSourceRequest` wraps `ConvertDocumentRequest`) to adhere to gRPC best practices and Google API style guides.
*   **Mapping Layer (`mapping.py`)**: Responsible for the "DTO" translation. It converts Protobuf messages into Pydantic models (for the Orchestrator) and results back into Protobuf.
*   **The "Doc" Converter (`docling_document_converter.py`)**: A specialized, ~1000-line manual mapping for the deeply nested `DoclingDocument` structure.
*   **Schema Safety (`schema_validator.py`)**: A sophisticated reflection-based tool that runs at server startup to verify that the Pydantic models and Protobuf descriptors are perfectly aligned.

---

### 🔄 Data Flow

`gRPC Client` → `Protobuf Message` → `mapping.py` → `Pydantic Model` → `Orchestrator` → `docling engine` → `Pydantic Result` → `document_converter.py` → `Protobuf Message` → `gRPC Response`.

---

### 🐍 Python Jargon for Java Developers

| Python Term | Java Equivalent / Explanation |
| :--- | :--- |
| **`asyncio`** | **Project Loom / Event Loop**. Think of it as a highly efficient, single-threaded event loop (like Vert.x or Node.js). Use `await` where you'd wait for a `Future`. |
| **Pydantic** | **Jackson + Lombok + Bean Validation**. It's the "source of truth" for data modeling, validation, and serialization. |
| **Type Hinting** | **Static Typing**. PEP 484 hints (e.g., `list[str]`) are used by Pydantic for validation, though Python itself doesn't enforce them at runtime. |
| **`grpc.aio`** | The asynchronous version of the gRPC library, compatible with Python's event loop. |
| **Duck Typing** | **Structural Typing**. If an object has the right methods, it "fits" the interface. We "harden" this using the `schema_validator`. |
| **Dunder Methods** | **Magic Methods**. Methods starting with double-underscores (e.g., `__init__` for constructors). |

---

### 💡 Points for "Strong" Presentation (and how to handle "Weak" ones)

#### ✅ Strong Points (Brag about these)
*   **Reflection-Based Startup Validation**: Mention that the `schema_validator.py` uses reflection on both Pydantic and Protobuf to ensure they stay in sync. This provides **compile-like safety** in a dynamic environment, preventing runtime "missing field" errors.
*   **Shared Orchestration**: Highlight that we aren't duplicating logic. By sharing the `Orchestrator`, we get the same model caching and worker management as the production REST API.
*   **Async Streaming**: We've implemented `Watch` RPCs that internally poll and stream status updates, providing a better DX than the REST polling loop.

#### 🛠️ "POC" Points (If they ask "why like this?")
*   **Manual Mapping**: If asked why we have a 1000-line converter instead of an auto-mapper: *"Docling's document structure is extremely complex. Manual mapping ensures 100% precision and allows us to optimize the Protobuf structure for binary efficiency where auto-mappers often fail."*
*   **Single-Use Cleanup**: If asked about the task deletion logic: *"This follows the REST API's 'single-use' results configuration. In this POC, we use `asyncio.create_task` for lightweight background cleanup, but it's designed to be replaced by a more robust persistent storage cleaner if needed."*

---

### 📂 Quick Reference Files
*   **Contract**: `proto/ai/docling/serve/v1/docling_serve.proto`
*   **Implementation**: `docling_serve/grpc/server.py`
*   **Safety Check**: `docling_serve/grpc/schema_validator.py`
*   **Complex Mapping**: `docling_serve/grpc/docling_document_converter.py`

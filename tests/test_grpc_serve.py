"""gRPC server tests for docling-serve.

TEST STATUS (as of 2026-02-15):
- test_health: ✅ PASSES - Basic health check works
- test_convert_source_async: ✅ PASSES - Async endpoint accepts requests and returns task IDs
- test_convert_source_sync: ❌ FAILS - Two issues found:
  1. Worker fails with "EasyOCR is not installed" error
  2. Error handling bug: task_result is None but code tries task_result.result without null check
- test_api_key_validation: ⏭️ SKIPPED when no API key configured

BUGS FOUND:
1. **Missing dependency handling**: Worker crashes when EasyOCR not installed instead of graceful fallback
2. **Error handling bug in server.py line 145**:
   ```python
   if not hasattr(task_result.result, "content"):  # AttributeError if task_result is None
   ```
   Should check `task_result is not None` before accessing `.result`
3. **Async context.abort() not awaited** (line 143): RuntimeWarning about unawaited coroutine

CONFIGURATION:
- gRPC message size limits increased to 50MB for tests
- Orchestrator queue properly started/stopped in fixtures
"""

import base64
import importlib.util
import os

import grpc
import pytest
import pytest_asyncio

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2,
    docling_serve_pb2_grpc,
    docling_serve_types_pb2,
)
from docling_serve.grpc.server import DoclingServeGrpcService
from docling_serve.orchestrator_factory import get_async_orchestrator
from docling_serve.settings import docling_serve_settings

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def grpc_server():
    """Start a gRPC server for testing."""
    get_async_orchestrator.cache_clear()
    orchestrator = get_async_orchestrator()
    original_single_use = docling_serve_settings.single_use_results
    docling_serve_settings.single_use_results = False
    # Increase max message size for tests
    options = [
        ("grpc.max_send_message_length", 50 * 1024 * 1024),
        ("grpc.max_receive_message_length", 50 * 1024 * 1024),
    ]
    server = grpc.aio.server(options=options)
    service = DoclingServeGrpcService(orchestrator=orchestrator)
    await service.start()
    docling_serve_pb2_grpc.add_DoclingServeServiceServicer_to_server(service, server)

    port = server.add_insecure_port("[::]:0")
    await server.start()

    yield f"localhost:{port}"

    await service.close()
    docling_serve_settings.single_use_results = original_single_use
    get_async_orchestrator.cache_clear()
    await server.stop(grace=1)


@pytest_asyncio.fixture
async def grpc_channel(grpc_server):
    """Create a gRPC channel."""
    options = [
        ("grpc.max_send_message_length", 50 * 1024 * 1024),
        ("grpc.max_receive_message_length", 50 * 1024 * 1024),
    ]
    async with grpc.aio.insecure_channel(grpc_server, options=options) as channel:
        yield channel


@pytest_asyncio.fixture
async def grpc_stub(grpc_channel):
    """Create a gRPC stub."""
    return docling_serve_pb2_grpc.DoclingServeServiceStub(grpc_channel)


def get_metadata():
    """Get metadata with API key if configured."""
    if docling_serve_settings.api_key:
        return (("x-api-key", docling_serve_settings.api_key),)
    return ()


def _available_ocr_engine() -> int | None:
    if importlib.util.find_spec("easyocr"):
        return docling_serve_types_pb2.OCR_ENGINE_EASYOCR
    if importlib.util.find_spec("rapidocr"):
        return docling_serve_types_pb2.OCR_ENGINE_RAPIDOCR
    return None


@pytest.mark.asyncio
async def test_health(grpc_stub):
    """Test Health RPC."""
    request = docling_serve_pb2.HealthRequest()
    response = await grpc_stub.Health(request, metadata=get_metadata())
    assert response.status == "ok"


@pytest.mark.asyncio
async def test_convert_source_sync(grpc_stub):
    """Test ConvertSource RPC with a simple PDF.

    CURRENT STATUS: FAILS

    Issues found:
    1. Worker fails: "EasyOCR is not installed. Please install it via `pip install easyocr`"
    2. Server error handling bug at line 145: AttributeError when task_result is None
       - Code tries to access task_result.result without checking if task_result is None first
    3. context.abort() is async but not awaited (line 143)

    This test validates the synchronous conversion flow where the server waits
    for task completion before returning results.
    """
    pdf_path = os.path.join(os.path.dirname(__file__), "2206.01062v1.pdf")

    with open(pdf_path, "rb") as f:
        pdf_content = base64.b64encode(f.read()).decode("utf-8")

    request = docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    ),
                )
            ],
            options=docling_serve_types_pb2.ConvertDocumentOptions(
                do_ocr=False,
                force_ocr=False,
                to_formats=[docling_serve_types_pb2.OUTPUT_FORMAT_JSON],
            ),
        )
    )

    response = await grpc_stub.ConvertSource(request, metadata=get_metadata())

    # Verify we got a document response
    assert response.response.HasField("document")
    # Check that we have a filename
    assert len(response.response.document.filename) > 0
    assert response.response.document.doc.schema_name == "DoclingDocument"


@pytest.mark.asyncio
@pytest.mark.ocr
async def test_convert_source_sync_ocr(grpc_stub):
    """Test ConvertSource RPC with OCR enabled.

    Skips if no supported OCR engine is installed.
    """
    ocr_engine = _available_ocr_engine()
    if ocr_engine is None:
        pytest.skip("No OCR engine installed (install easyocr or rapidocr extras).")

    pdf_path = os.path.join(os.path.dirname(__file__), "2206.01062v1.pdf")

    with open(pdf_path, "rb") as f:
        pdf_content = base64.b64encode(f.read()).decode("utf-8")

    request = docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    ),
                )
            ],
            options=docling_serve_types_pb2.ConvertDocumentOptions(
                do_ocr=True,
                force_ocr=False,
                ocr_engine=ocr_engine,
                ocr_lang=["en"],
            ),
        )
    )

    response = await grpc_stub.ConvertSource(request, metadata=get_metadata())

    # Verify we got a document response
    assert response.response.HasField("document")
    # Check that we have a filename
    assert len(response.response.document.filename) > 0
    assert response.response.document.doc.schema_name == "DoclingDocument"


@pytest.mark.asyncio
async def test_convert_source_async(grpc_stub):
    """Test ConvertSourceAsync RPC.

    Tests that async endpoint accepts requests and returns task IDs.
    Uses HTTP source to avoid base64 encoding overhead.
    """
    request = docling_serve_pb2.ConvertSourceAsyncRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    http=docling_serve_types_pb2.HttpSource(
                        url="https://arxiv.org/pdf/2501.17887",
                    ),
                )
            ]
        )
    )

    response = await grpc_stub.ConvertSourceAsync(request, metadata=get_metadata())

    # Verify we got a valid task ID
    assert len(response.response.task_id) > 0
    # Verify task type is set
    assert response.response.task_type == "convert"
    # Verify status is a valid enum value (1 = PENDING)
    assert response.response.task_status >= 0


@pytest.mark.asyncio
async def test_convert_source_multiple_formats(grpc_stub):
    pdf_path = os.path.join(os.path.dirname(__file__), "2206.01062v1.pdf")

    with open(pdf_path, "rb") as f:
        pdf_content = base64.b64encode(f.read()).decode("utf-8")

    request = docling_serve_pb2.ConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    ),
                )
            ],
            options=docling_serve_types_pb2.ConvertDocumentOptions(
                do_ocr=False,
                force_ocr=False,
                to_formats=[
                    docling_serve_types_pb2.OUTPUT_FORMAT_MD,
                    docling_serve_types_pb2.OUTPUT_FORMAT_TEXT,
                    docling_serve_types_pb2.OUTPUT_FORMAT_HTML,
                    docling_serve_types_pb2.OUTPUT_FORMAT_DOCTAGS,
                ],
            ),
        )
    )

    response = await grpc_stub.ConvertSource(request, metadata=get_metadata())

    assert response.response.document.exports.md
    assert response.response.document.exports.text
    assert response.response.document.exports.html
    assert response.response.document.exports.doctags
    assert response.response.document.doc.schema_name == "DoclingDocument"


@pytest.mark.asyncio
async def test_chunk_hierarchical_source_sync(grpc_stub):
    """Test ChunkHierarchicalSource RPC with the real pipeline."""
    pdf_path = os.path.join(os.path.dirname(__file__), "2206.01062v1.pdf")

    with open(pdf_path, "rb") as f:
        pdf_content = base64.b64encode(f.read()).decode("utf-8")

    request = docling_serve_pb2.ChunkHierarchicalSourceRequest(
        request=docling_serve_types_pb2.HierarchicalChunkRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    ),
                )
            ],
            convert_options=docling_serve_types_pb2.ConvertDocumentOptions(
                do_ocr=False,
                force_ocr=False,
                to_formats=[docling_serve_types_pb2.OUTPUT_FORMAT_TEXT],
            ),
            include_converted_doc=True,
            chunking_options=docling_serve_types_pb2.HierarchicalChunkerOptions(
                use_markdown_tables=True,
                include_raw_text=False,
            ),
        )
    )

    response = await grpc_stub.ChunkHierarchicalSource(request, metadata=get_metadata())

    assert len(response.response.chunks) > 0
    first_chunk = response.response.chunks[0]
    assert len(first_chunk.text) > 0
    assert len(first_chunk.filename) > 0
    assert response.response.processing_time > 0
    # We asked for the converted doc to be included
    assert len(response.response.documents) > 0
    assert response.response.documents[0].content.doc.schema_name == "DoclingDocument"


@pytest.mark.asyncio
async def test_chunk_hybrid_source_sync(grpc_stub):
    """Test ChunkHybridSource RPC with the real pipeline."""
    pdf_path = os.path.join(os.path.dirname(__file__), "2206.01062v1.pdf")

    with open(pdf_path, "rb") as f:
        pdf_content = base64.b64encode(f.read()).decode("utf-8")

    request = docling_serve_pb2.ChunkHybridSourceRequest(
        request=docling_serve_types_pb2.HybridChunkRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    ),
                )
            ],
            convert_options=docling_serve_types_pb2.ConvertDocumentOptions(
                do_ocr=False,
                force_ocr=False,
                to_formats=[docling_serve_types_pb2.OUTPUT_FORMAT_TEXT],
            ),
            include_converted_doc=False,
            chunking_options=docling_serve_types_pb2.HybridChunkerOptions(
                use_markdown_tables=True,
                include_raw_text=True,
                max_tokens=512,
                merge_peers=True,
            ),
        )
    )

    response = await grpc_stub.ChunkHybridSource(request, metadata=get_metadata())

    assert len(response.response.chunks) > 0
    first_chunk = response.response.chunks[0]
    assert len(first_chunk.text) > 0
    assert len(first_chunk.filename) > 0
    assert response.response.processing_time > 0
    # The pipeline may or may not return a converted document.
    if response.response.documents:
        assert len(response.response.documents[0].content.filename) > 0


@pytest.mark.asyncio
async def test_api_key_validation(grpc_channel):
    """Test API key validation if configured."""
    if not docling_serve_settings.api_key:
        pytest.skip("API key not configured")

    stub = docling_serve_pb2_grpc.DoclingServeServiceStub(grpc_channel)
    request = docling_serve_pb2.HealthRequest()

    # Test without API key
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await stub.Health(request)

    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED

    # Test with wrong API key
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await stub.Health(request, metadata=(("x-api-key", "wrong-key"),))

    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED

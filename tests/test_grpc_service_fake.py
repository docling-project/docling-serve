import asyncio
import base64

import grpc
import pytest
import pytest_asyncio

from docling.datamodel.base_models import ConversionStatus
from docling_jobkit.datamodel.result import (
    ChunkedDocumentResult,
    ChunkedDocumentResultItem,
    DoclingTaskResult,
    ExportDocumentResponse,
    ExportResult,
)
from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskProcessingMeta, TaskStatus, TaskType
from docling_jobkit.orchestrators.base_orchestrator import TaskNotFoundError

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2,
    docling_serve_pb2_grpc,
    docling_serve_types_pb2,
)
from docling_serve.grpc.server import DoclingServeGrpcService
from docling_serve.settings import docling_serve_settings

pytestmark = pytest.mark.unit


class FakeOrchestrator:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.results: dict[str, DoclingTaskResult] = {}
        self.positions: dict[str, int] = {}
        self.cleared_converters = False
        self.cleared_results: list[float] = []
        self.deleted_tasks: list[str] = []
        self._stop = asyncio.Event()
        self._counter = 0

    async def warm_up_caches(self) -> None:
        return

    async def process_queue(self) -> None:
        await self._stop.wait()

    async def enqueue(self, *, task_type, sources, convert_options, target, **kwargs) -> Task:
        self._counter += 1
        task_id = f"task-{self._counter}"
        task = Task(
            task_id=task_id,
            task_type=task_type,
            task_status=TaskStatus.SUCCESS,
            sources=sources,
            target=target,
            convert_options=convert_options,
        )
        self.tasks[task_id] = task
        self.positions[task_id] = 0
        if task_type == TaskType.CONVERT:
            export = ExportResult(
                content=ExportDocumentResponse(filename="doc.md", md_content="hello"),
                status=ConversionStatus.SUCCESS,
            )
            self.results[task_id] = DoclingTaskResult(
                result=export,
                processing_time=0.1,
                num_converted=1,
                num_succeeded=1,
                num_failed=0,
            )
        return task

    async def task_status(self, *, task_id: str, wait: float | None = None) -> Task:
        try:
            return self.tasks[task_id]
        except KeyError as exc:
            raise TaskNotFoundError(task_id) from exc

    async def get_queue_position(self, *, task_id: str) -> int:
        return self.positions.get(task_id, 0)

    async def task_result(self, *, task_id: str):
        return self.results.get(task_id)

    async def clear_converters(self) -> None:
        self.cleared_converters = True

    async def clear_results(self, *, older_than: float) -> None:
        self.cleared_results.append(older_than)

    async def delete_task(self, *, task_id: str) -> None:
        self.deleted_tasks.append(task_id)


@pytest_asyncio.fixture
async def grpc_server():
    original_single_use = docling_serve_settings.single_use_results
    docling_serve_settings.single_use_results = False
    options = [
        ("grpc.max_send_message_length", 50 * 1024 * 1024),
        ("grpc.max_receive_message_length", 50 * 1024 * 1024),
    ]
    server = grpc.aio.server(options=options)
    orchestrator = FakeOrchestrator()
    service = DoclingServeGrpcService(orchestrator=orchestrator)
    await service.start()
    docling_serve_pb2_grpc.add_DoclingServeServiceServicer_to_server(service, server)

    port = server.add_insecure_port("[::]:0")
    await server.start()

    yield {"address": f"localhost:{port}", "orchestrator": orchestrator}

    await service.close()
    docling_serve_settings.single_use_results = original_single_use
    await server.stop(grace=1)


@pytest_asyncio.fixture
async def grpc_channel(grpc_server):
    options = [
        ("grpc.max_send_message_length", 50 * 1024 * 1024),
        ("grpc.max_receive_message_length", 50 * 1024 * 1024),
    ]
    async with grpc.aio.insecure_channel(grpc_server["address"], options=options) as channel:
        yield channel


@pytest_asyncio.fixture
async def grpc_stub(grpc_channel):
    return docling_serve_pb2_grpc.DoclingServeServiceStub(grpc_channel)


@pytest.fixture
def orchestrator(grpc_server):
    return grpc_server["orchestrator"]


@pytest.mark.asyncio
async def test_get_convert_result(grpc_stub, orchestrator):
    task_id = "convert-1"
    export = ExportResult(
        content=ExportDocumentResponse(filename="doc.md", md_content="hello"),
        status=ConversionStatus.SUCCESS,
    )
    orchestrator.results[task_id] = DoclingTaskResult(
        result=export,
        processing_time=0.5,
        num_converted=1,
        num_succeeded=1,
        num_failed=0,
    )

    response = await grpc_stub.GetConvertResult(
        docling_serve_pb2.GetConvertResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id=task_id)
        )
    )

    assert response.response.document.md_content == "hello"


@pytest.mark.asyncio
async def test_get_convert_result_not_found(grpc_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.GetConvertResult(
            docling_serve_pb2.GetConvertResultRequest(
                request=docling_serve_types_pb2.TaskResultRequest(task_id="missing")
            )
        )

    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_get_chunk_result(grpc_stub, orchestrator):
    task_id = "chunk-1"
    chunk = ChunkedDocumentResultItem(
        filename="doc.md",
        chunk_index=0,
        text="chunk text",
        doc_items=[],
    )
    doc_export = ExportResult(
        content=ExportDocumentResponse(filename="doc.md", md_content="hello"),
        status=ConversionStatus.SUCCESS,
    )
    chunked = ChunkedDocumentResult(
        chunks=[chunk],
        documents=[doc_export],
    )
    orchestrator.results[task_id] = DoclingTaskResult(
        result=chunked,
        processing_time=0.2,
        num_converted=1,
        num_succeeded=1,
        num_failed=0,
    )

    response = await grpc_stub.GetChunkResult(
        docling_serve_pb2.GetChunkResultRequest(
            request=docling_serve_types_pb2.TaskResultRequest(task_id=task_id)
        )
    )

    assert len(response.response.chunks) == 1
    assert response.response.chunks[0].text == "chunk text"


@pytest.mark.asyncio
async def test_get_chunk_result_not_found(grpc_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.GetChunkResult(
            docling_serve_pb2.GetChunkResultRequest(
                request=docling_serve_types_pb2.TaskResultRequest(task_id="missing")
            )
        )

    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_poll_task_status(grpc_stub, orchestrator):
    task_id = "status-1"
    orchestrator.tasks[task_id] = Task(
        task_id=task_id,
        task_type=TaskType.CONVERT,
        task_status=TaskStatus.STARTED,
        sources=[],
        processing_meta=TaskProcessingMeta(num_docs=1),
    )

    response = await grpc_stub.PollTaskStatus(
        docling_serve_pb2.PollTaskStatusRequest(
            request=docling_serve_types_pb2.TaskStatusPollRequest(task_id=task_id)
        )
    )

    assert response.response.task_status == docling_serve_types_pb2.TASK_STATUS_STARTED
    assert response.response.task_meta.num_docs == 1


@pytest.mark.asyncio
async def test_poll_task_status_not_found(grpc_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await grpc_stub.PollTaskStatus(
            docling_serve_pb2.PollTaskStatusRequest(
                request=docling_serve_types_pb2.TaskStatusPollRequest(task_id="missing")
            )
        )

    assert exc_info.value.code() == grpc.StatusCode.NOT_FOUND


@pytest.mark.asyncio
async def test_clear_results_and_converters(grpc_stub, orchestrator):
    response = await grpc_stub.ClearResults(
        docling_serve_pb2.ClearResultsRequest(older_than=12)
    )
    assert response.response.status == "ok"
    assert orchestrator.cleared_results == [12]

    response = await grpc_stub.ClearConverters(docling_serve_pb2.ClearConvertersRequest())
    assert response.response.status == "ok"
    assert orchestrator.cleared_converters is True


@pytest.mark.asyncio
async def test_watch_convert_source(grpc_stub):
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.WatchConvertSourceRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ]
        )
    )

    async for response in grpc_stub.WatchConvertSource(request):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break


@pytest.mark.asyncio
async def test_watch_chunk_hierarchical_source(grpc_stub):
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.WatchChunkHierarchicalSourceRequest(
        request=docling_serve_types_pb2.HierarchicalChunkRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ],
            chunking_options=docling_serve_types_pb2.HierarchicalChunkerOptions(
                use_markdown_tables=True,
                include_raw_text=False,
            ),
        )
    )

    async for response in grpc_stub.WatchChunkHierarchicalSource(request):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break


@pytest.mark.asyncio
async def test_watch_chunk_hybrid_source(grpc_stub):
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.WatchChunkHybridSourceRequest(
        request=docling_serve_types_pb2.HybridChunkRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ],
            chunking_options=docling_serve_types_pb2.HybridChunkerOptions(
                use_markdown_tables=True,
                include_raw_text=False,
                max_tokens=64,
            ),
        )
    )

    async for response in grpc_stub.WatchChunkHybridSource(request):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break


@pytest.mark.asyncio
async def test_convert_source_stream(grpc_stub):
    pdf_content = base64.b64encode(b"dummy").decode("utf-8")
    request = docling_serve_pb2.ConvertSourceStreamRequest(
        request=docling_serve_types_pb2.ConvertDocumentRequest(
            sources=[
                docling_serve_types_pb2.Source(
                    file=docling_serve_types_pb2.FileSource(
                        base64_string=pdf_content,
                        filename="test.pdf",
                    )
                )
            ]
        )
    )

    responses = [response async for response in grpc_stub.ConvertSourceStream(request)]
    assert len(responses) == 1
    assert responses[0].response.HasField("document")


# --------------- API key enforcement for streaming RPCs ---------------


@pytest_asyncio.fixture
async def api_key_server():
    """Server with API key required."""
    original_key = docling_serve_settings.api_key
    docling_serve_settings.api_key = "test-secret-key"
    original_single_use = docling_serve_settings.single_use_results
    docling_serve_settings.single_use_results = False

    options = [
        ("grpc.max_send_message_length", 50 * 1024 * 1024),
        ("grpc.max_receive_message_length", 50 * 1024 * 1024),
    ]
    server = grpc.aio.server(options=options)
    orchestrator = FakeOrchestrator()
    service = DoclingServeGrpcService(orchestrator=orchestrator)
    await service.start()
    docling_serve_pb2_grpc.add_DoclingServeServiceServicer_to_server(service, server)

    port = server.add_insecure_port("[::]:0")
    await server.start()

    yield f"localhost:{port}"

    await service.close()
    await server.stop(grace=1)
    docling_serve_settings.api_key = original_key
    docling_serve_settings.single_use_results = original_single_use


@pytest_asyncio.fixture
async def api_key_stub(api_key_server):
    options = [
        ("grpc.max_send_message_length", 50 * 1024 * 1024),
        ("grpc.max_receive_message_length", 50 * 1024 * 1024),
    ]
    async with grpc.aio.insecure_channel(api_key_server, options=options) as channel:
        yield docling_serve_pb2_grpc.DoclingServeServiceStub(channel)


def _dummy_convert_request():
    return docling_serve_types_pb2.ConvertDocumentRequest(
        sources=[
            docling_serve_types_pb2.Source(
                file=docling_serve_types_pb2.FileSource(
                    base64_string=base64.b64encode(b"dummy").decode("utf-8"),
                    filename="test.pdf",
                )
            )
        ]
    )


def _dummy_hierarchical_request():
    return docling_serve_types_pb2.HierarchicalChunkRequest(
        sources=[
            docling_serve_types_pb2.Source(
                file=docling_serve_types_pb2.FileSource(
                    base64_string=base64.b64encode(b"dummy").decode("utf-8"),
                    filename="test.pdf",
                )
            )
        ],
    )


def _dummy_hybrid_request():
    return docling_serve_types_pb2.HybridChunkRequest(
        sources=[
            docling_serve_types_pb2.Source(
                file=docling_serve_types_pb2.FileSource(
                    base64_string=base64.b64encode(b"dummy").decode("utf-8"),
                    filename="test.pdf",
                )
            )
        ],
    )


@pytest.mark.asyncio
async def test_api_key_health_rejected(api_key_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        await api_key_stub.Health(docling_serve_pb2.HealthRequest())
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_api_key_health_accepted(api_key_stub):
    response = await api_key_stub.Health(
        docling_serve_pb2.HealthRequest(),
        metadata=(("x-api-key", "test-secret-key"),),
    )
    assert response.status == "ok"


@pytest.mark.asyncio
async def test_api_key_watch_convert_rejected(api_key_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        async for _ in api_key_stub.WatchConvertSource(
            docling_serve_pb2.WatchConvertSourceRequest(request=_dummy_convert_request())
        ):
            pass
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_api_key_watch_chunk_hierarchical_rejected(api_key_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        async for _ in api_key_stub.WatchChunkHierarchicalSource(
            docling_serve_pb2.WatchChunkHierarchicalSourceRequest(
                request=_dummy_hierarchical_request()
            )
        ):
            pass
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_api_key_watch_chunk_hybrid_rejected(api_key_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        async for _ in api_key_stub.WatchChunkHybridSource(
            docling_serve_pb2.WatchChunkHybridSourceRequest(
                request=_dummy_hybrid_request()
            )
        ):
            pass
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_api_key_convert_source_stream_rejected(api_key_stub):
    with pytest.raises(grpc.aio.AioRpcError) as exc_info:
        async for _ in api_key_stub.ConvertSourceStream(
            docling_serve_pb2.ConvertSourceStreamRequest(request=_dummy_convert_request())
        ):
            pass
    assert exc_info.value.code() == grpc.StatusCode.UNAUTHENTICATED


@pytest.mark.asyncio
async def test_api_key_streaming_accepted_with_key(api_key_stub):
    """Streaming RPCs succeed when the correct API key is provided."""
    metadata = (("x-api-key", "test-secret-key"),)

    async for response in api_key_stub.WatchConvertSource(
        docling_serve_pb2.WatchConvertSourceRequest(request=_dummy_convert_request()),
        metadata=metadata,
    ):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break

    async for response in api_key_stub.WatchChunkHierarchicalSource(
        docling_serve_pb2.WatchChunkHierarchicalSourceRequest(
            request=_dummy_hierarchical_request()
        ),
        metadata=metadata,
    ):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break

    async for response in api_key_stub.WatchChunkHybridSource(
        docling_serve_pb2.WatchChunkHybridSourceRequest(
            request=_dummy_hybrid_request()
        ),
        metadata=metadata,
    ):
        assert response.response.task_status in (
            docling_serve_types_pb2.TASK_STATUS_SUCCESS,
            docling_serve_types_pb2.TASK_STATUS_PENDING,
            docling_serve_types_pb2.TASK_STATUS_STARTED,
        )
        break

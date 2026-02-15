from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Optional

import grpc

from docling.datamodel.base_models import OutputFormat
from docling_jobkit.datamodel.chunking import ChunkingExportOptions
from docling_jobkit.datamodel.task_meta import TaskType
from docling_jobkit.orchestrators.base_orchestrator import BaseOrchestrator, TaskNotFoundError

from docling_serve.orchestrator_factory import get_async_orchestrator
from docling_serve.settings import docling_serve_settings

from .gen.ai.docling.serve.v1 import (
    docling_serve_pb2,
    docling_serve_pb2_grpc,
    docling_serve_types_pb2,
)
from .mapping import (
    chunk_result_to_proto,
    clear_response_to_proto,
    convert_result_to_proto,
    requested_output_formats,
    task_status_to_proto,
    to_convert_options,
    to_hierarchical_chunk_options,
    to_hybrid_chunk_options,
    to_task_sources,
    to_task_target,
    with_single_use_cleanup,
)

_log = logging.getLogger(__name__)


class DoclingServeGrpcService(docling_serve_pb2_grpc.DoclingServeServiceServicer):
    def __init__(self, orchestrator: Optional[BaseOrchestrator] = None) -> None:
        self._orchestrator = orchestrator or get_async_orchestrator()
        self._queue_task: Optional[asyncio.Task] = None
        self._queue_lock = asyncio.Lock()
        self._requested_formats: dict[str, set[OutputFormat]] = {}

    async def start(self) -> None:
        await self._ensure_queue_started()

    async def close(self) -> None:
        if self._queue_task is None:
            return
        self._queue_task.cancel()
        try:
            await self._queue_task
        except asyncio.CancelledError:
            _log.info("Queue processor cancelled.")
        self._queue_task = None

    # -------------------- helpers --------------------

    @staticmethod
    async def _check_api_key(context: grpc.aio.ServicerContext) -> None:
        if not docling_serve_settings.api_key:
            return
        metadata = {k.lower(): v for k, v in context.invocation_metadata()}
        api_key = (
            metadata.get("api-key")
            or metadata.get("x-api-key")
            or metadata.get("api_key")
        )
        if api_key != docling_serve_settings.api_key:
            await context.abort(grpc.StatusCode.UNAUTHENTICATED, "API key required")

    async def _abort(
        self,
        context: grpc.aio.ServicerContext,
        code: grpc.StatusCode,
        message: str,
    ) -> None:
        await context.abort(code, message)

    async def _wait_task_complete(self, task_id: str) -> bool:
        start = asyncio.get_running_loop().time()
        while True:
            task = await self._orchestrator.task_status(task_id=task_id)
            if task.is_completed():
                return True
            await asyncio.sleep(docling_serve_settings.sync_poll_interval)
            elapsed = asyncio.get_running_loop().time() - start
            if docling_serve_settings.max_sync_wait and (
                elapsed > docling_serve_settings.max_sync_wait
            ):
                return False

    async def _ensure_queue_started(self) -> None:
        if self._queue_task is not None and not self._queue_task.done():
            return
        async with self._queue_lock:
            if self._queue_task is not None and not self._queue_task.done():
                return
            if docling_serve_settings.load_models_at_boot:
                await self._orchestrator.warm_up_caches()
            self._queue_task = asyncio.create_task(self._orchestrator.process_queue())

    async def _poll_status_stream(
        self,
        task_id: str,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_types_pb2.TaskStatusPollResponse]:
        while not context.done():
            task = await self._orchestrator.task_status(task_id=task_id)
            position = await self._orchestrator.get_queue_position(task_id=task_id)
            yield task_status_to_proto(task, position)
            if task.is_completed():
                return
            await asyncio.sleep(docling_serve_settings.sync_poll_interval)

    @staticmethod
    def _ensure_doc_format(options, requested_formats: set = frozenset()) -> None:
        if options is None:
            return
        # When no exports were requested, only generate JSON (for the proto
        # doc field).  The upstream default is [MARKDOWN] which would waste
        # cycles producing Markdown that is never returned.
        if not requested_formats:
            options.to_formats = [OutputFormat.JSON]
        elif OutputFormat.JSON not in options.to_formats:
            options.to_formats.append(OutputFormat.JSON)

    # -------------------- RPCs --------------------

    async def Health(
        self,
        request: docling_serve_pb2.HealthRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.HealthResponse:
        await self._check_api_key(context)
        return docling_serve_pb2.HealthResponse(status="ok")

    async def ConvertSource(
        self,
        request: docling_serve_pb2.ConvertSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ConvertSourceResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        requested_formats = requested_output_formats(
            request.request.options if request.request.HasField("options") else None
        )
        sources = to_task_sources(request.request.sources)
        options = to_convert_options(
            request.request.options if request.request.HasField("options") else None
        )
        self._ensure_doc_format(options, requested_formats)
        target = to_task_target(request.request.target if request.request.HasField("target") else None)

        task = await self._orchestrator.enqueue(
            task_type=TaskType.CONVERT,
            sources=sources,
            convert_options=options,
            target=target,
        )

        completed = await self._wait_task_complete(task.task_id)
        if not completed:
            await self._abort(
                context,
                grpc.StatusCode.DEADLINE_EXCEEDED,
                "Conversion is taking too long. Increase DOCLING_SERVE_MAX_SYNC_WAIT.",
            )
            return docling_serve_pb2.ConvertSourceResponse()

        task_result = await self._orchestrator.task_result(task_id=task.task_id)
        if task_result is None:
            await self._abort(context, grpc.StatusCode.NOT_FOUND, "Task result not found.")
            return docling_serve_pb2.ConvertSourceResponse()

        if not hasattr(task_result.result, "content"):
            await self._abort(
                context,
                grpc.StatusCode.INVALID_ARGUMENT,
                "Conversion result is not an in-body document.",
            )
            return docling_serve_pb2.ConvertSourceResponse()

        response = convert_result_to_proto(
            task_result.result,
            task_result.processing_time,
            requested_formats=requested_formats,
        )
        with_single_use_cleanup(self._orchestrator, task.task_id)

        return docling_serve_pb2.ConvertSourceResponse(response=response)

    async def ConvertSourceAsync(
        self,
        request: docling_serve_pb2.ConvertSourceAsyncRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ConvertSourceAsyncResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        requested_formats = requested_output_formats(
            request.request.options if request.request.HasField("options") else None
        )
        sources = to_task_sources(request.request.sources)
        options = to_convert_options(
            request.request.options if request.request.HasField("options") else None
        )
        self._ensure_doc_format(options, requested_formats)
        target = to_task_target(request.request.target if request.request.HasField("target") else None)

        task = await self._orchestrator.enqueue(
            task_type=TaskType.CONVERT,
            sources=sources,
            convert_options=options,
            target=target,
        )
        position = await self._orchestrator.get_queue_position(task_id=task.task_id)
        self._requested_formats[task.task_id] = requested_formats
        response = task_status_to_proto(task, position)
        return docling_serve_pb2.ConvertSourceAsyncResponse(response=response)

    async def ChunkHierarchicalSource(
        self,
        request: docling_serve_pb2.ChunkHierarchicalSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ChunkHierarchicalSourceResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        requested_formats = requested_output_formats(
            request.request.convert_options
            if request.request.HasField("convert_options")
            else None
        )
        sources = to_task_sources(request.request.sources)
        options = to_convert_options(
            request.request.convert_options
            if request.request.HasField("convert_options")
            else None
        )
        self._ensure_doc_format(options, requested_formats)
        target = to_task_target(request.request.target if request.request.HasField("target") else None)
        chunking_options = to_hierarchical_chunk_options(
            request.request.chunking_options if request.request.HasField("chunking_options") else None
        )

        export_options = ChunkingExportOptions(
            include_converted_doc=request.request.include_converted_doc
        )

        task = await self._orchestrator.enqueue(
            task_type=TaskType.CHUNK,
            sources=sources,
            convert_options=options,
            chunking_options=chunking_options,
            chunking_export_options=export_options,
            target=target,
        )

        completed = await self._wait_task_complete(task.task_id)
        if not completed:
            await self._abort(
                context,
                grpc.StatusCode.DEADLINE_EXCEEDED,
                "Chunking is taking too long. Increase DOCLING_SERVE_MAX_SYNC_WAIT.",
            )
            return docling_serve_pb2.ChunkHierarchicalSourceResponse()

        task_result = await self._orchestrator.task_result(task_id=task.task_id)
        if task_result is None:
            await self._abort(context, grpc.StatusCode.NOT_FOUND, "Task result not found.")
            return docling_serve_pb2.ChunkHierarchicalSourceResponse()

        if not hasattr(task_result.result, "chunks"):
            await self._abort(
                context,
                grpc.StatusCode.INVALID_ARGUMENT,
                "Chunking result is not an in-body response.",
            )
            return docling_serve_pb2.ChunkHierarchicalSourceResponse()

        response = chunk_result_to_proto(
            task_result.result,
            task_result.processing_time,
            requested_formats=requested_formats,
        )
        with_single_use_cleanup(self._orchestrator, task.task_id)

        return docling_serve_pb2.ChunkHierarchicalSourceResponse(response=response)

    async def ChunkHybridSource(
        self,
        request: docling_serve_pb2.ChunkHybridSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ChunkHybridSourceResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        requested_formats = requested_output_formats(
            request.request.convert_options
            if request.request.HasField("convert_options")
            else None
        )
        sources = to_task_sources(request.request.sources)
        options = to_convert_options(
            request.request.convert_options
            if request.request.HasField("convert_options")
            else None
        )
        self._ensure_doc_format(options, requested_formats)
        target = to_task_target(request.request.target if request.request.HasField("target") else None)
        chunking_options = to_hybrid_chunk_options(
            request.request.chunking_options if request.request.HasField("chunking_options") else None
        )

        export_options = ChunkingExportOptions(
            include_converted_doc=request.request.include_converted_doc
        )

        task = await self._orchestrator.enqueue(
            task_type=TaskType.CHUNK,
            sources=sources,
            convert_options=options,
            chunking_options=chunking_options,
            chunking_export_options=export_options,
            target=target,
        )

        completed = await self._wait_task_complete(task.task_id)
        if not completed:
            await self._abort(
                context,
                grpc.StatusCode.DEADLINE_EXCEEDED,
                "Chunking is taking too long. Increase DOCLING_SERVE_MAX_SYNC_WAIT.",
            )
            return docling_serve_pb2.ChunkHybridSourceResponse()

        task_result = await self._orchestrator.task_result(task_id=task.task_id)
        if task_result is None:
            await self._abort(context, grpc.StatusCode.NOT_FOUND, "Task result not found.")
            return docling_serve_pb2.ChunkHybridSourceResponse()

        if not hasattr(task_result.result, "chunks"):
            await self._abort(
                context,
                grpc.StatusCode.INVALID_ARGUMENT,
                "Chunking result is not an in-body response.",
            )
            return docling_serve_pb2.ChunkHybridSourceResponse()

        response = chunk_result_to_proto(
            task_result.result,
            task_result.processing_time,
            requested_formats=requested_formats,
        )
        with_single_use_cleanup(self._orchestrator, task.task_id)

        return docling_serve_pb2.ChunkHybridSourceResponse(response=response)

    async def ChunkHierarchicalSourceAsync(
        self,
        request: docling_serve_pb2.ChunkHierarchicalSourceAsyncRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ChunkHierarchicalSourceAsyncResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        requested_formats = requested_output_formats(
            request.request.convert_options
            if request.request.HasField("convert_options")
            else None
        )
        sources = to_task_sources(request.request.sources)
        options = to_convert_options(
            request.request.convert_options
            if request.request.HasField("convert_options")
            else None
        )
        self._ensure_doc_format(options, requested_formats)
        target = to_task_target(request.request.target if request.request.HasField("target") else None)
        chunking_options = to_hierarchical_chunk_options(
            request.request.chunking_options if request.request.HasField("chunking_options") else None
        )

        export_options = ChunkingExportOptions(
            include_converted_doc=request.request.include_converted_doc
        )

        task = await self._orchestrator.enqueue(
            task_type=TaskType.CHUNK,
            sources=sources,
            convert_options=options,
            chunking_options=chunking_options,
            chunking_export_options=export_options,
            target=target,
        )
        position = await self._orchestrator.get_queue_position(task_id=task.task_id)
        self._requested_formats[task.task_id] = requested_formats
        response = task_status_to_proto(task, position)
        return docling_serve_pb2.ChunkHierarchicalSourceAsyncResponse(response=response)

    async def ChunkHybridSourceAsync(
        self,
        request: docling_serve_pb2.ChunkHybridSourceAsyncRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ChunkHybridSourceAsyncResponse:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        requested_formats = requested_output_formats(
            request.request.convert_options
            if request.request.HasField("convert_options")
            else None
        )
        sources = to_task_sources(request.request.sources)
        options = to_convert_options(
            request.request.convert_options
            if request.request.HasField("convert_options")
            else None
        )
        self._ensure_doc_format(options, requested_formats)
        target = to_task_target(request.request.target if request.request.HasField("target") else None)
        chunking_options = to_hybrid_chunk_options(
            request.request.chunking_options if request.request.HasField("chunking_options") else None
        )

        export_options = ChunkingExportOptions(
            include_converted_doc=request.request.include_converted_doc
        )

        task = await self._orchestrator.enqueue(
            task_type=TaskType.CHUNK,
            sources=sources,
            convert_options=options,
            chunking_options=chunking_options,
            chunking_export_options=export_options,
            target=target,
        )
        position = await self._orchestrator.get_queue_position(task_id=task.task_id)
        self._requested_formats[task.task_id] = requested_formats
        response = task_status_to_proto(task, position)
        return docling_serve_pb2.ChunkHybridSourceAsyncResponse(response=response)

    async def PollTaskStatus(
        self,
        request: docling_serve_pb2.PollTaskStatusRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.PollTaskStatusResponse:
        await self._check_api_key(context)

        try:
            task = await self._orchestrator.task_status(
                task_id=request.request.task_id,
                wait=request.request.wait_time,
            )
            position = await self._orchestrator.get_queue_position(
                task_id=request.request.task_id
            )
        except TaskNotFoundError:
            await self._abort(context, grpc.StatusCode.NOT_FOUND, "Task not found.")
            return docling_serve_pb2.PollTaskStatusResponse()

        response = task_status_to_proto(task, position)
        return docling_serve_pb2.PollTaskStatusResponse(response=response)

    async def GetConvertResult(
        self,
        request: docling_serve_pb2.GetConvertResultRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.GetConvertResultResponse:
        await self._check_api_key(context)

        task_result = await self._orchestrator.task_result(
            task_id=request.request.task_id
        )
        if task_result is None:
            await self._abort(context, grpc.StatusCode.NOT_FOUND, "Task result not found.")
            return docling_serve_pb2.GetConvertResultResponse()

        if not hasattr(task_result.result, "content"):
            await self._abort(
                context,
                grpc.StatusCode.INVALID_ARGUMENT,
                "Conversion result is not an in-body document.",
            )
            return docling_serve_pb2.GetConvertResultResponse()

        requested_formats = self._requested_formats.pop(request.request.task_id, set())
        response = convert_result_to_proto(
            task_result.result,
            task_result.processing_time,
            requested_formats=requested_formats,
        )
        with_single_use_cleanup(self._orchestrator, request.request.task_id)
        return docling_serve_pb2.GetConvertResultResponse(response=response)

    async def GetChunkResult(
        self,
        request: docling_serve_pb2.GetChunkResultRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.GetChunkResultResponse:
        await self._check_api_key(context)

        task_result = await self._orchestrator.task_result(
            task_id=request.request.task_id
        )
        if task_result is None:
            await self._abort(context, grpc.StatusCode.NOT_FOUND, "Task result not found.")
            return docling_serve_pb2.GetChunkResultResponse()

        if not hasattr(task_result.result, "chunks"):
            await self._abort(
                context,
                grpc.StatusCode.INVALID_ARGUMENT,
                "Chunking result is not an in-body response.",
            )
            return docling_serve_pb2.GetChunkResultResponse()

        requested_formats = self._requested_formats.pop(request.request.task_id, set())
        response = chunk_result_to_proto(
            task_result.result,
            task_result.processing_time,
            requested_formats=requested_formats,
        )
        with_single_use_cleanup(self._orchestrator, request.request.task_id)
        return docling_serve_pb2.GetChunkResultResponse(response=response)

    async def ClearConverters(
        self,
        request: docling_serve_pb2.ClearConvertersRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ClearConvertersResponse:
        await self._check_api_key(context)
        await self._orchestrator.clear_converters()
        return docling_serve_pb2.ClearConvertersResponse(
            response=clear_response_to_proto()
        )

    async def ClearResults(
        self,
        request: docling_serve_pb2.ClearResultsRequest,
        context: grpc.aio.ServicerContext,
    ) -> docling_serve_pb2.ClearResultsResponse:
        await self._check_api_key(context)
        older_than = request.older_than if request.HasField("older_than") else 3600
        await self._orchestrator.clear_results(older_than=older_than)
        return docling_serve_pb2.ClearResultsResponse(
            response=clear_response_to_proto()
        )

    async def ConvertSourceStream(
        self,
        request: docling_serve_pb2.ConvertSourceStreamRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_pb2.ConvertSourceStreamResponse]:
        await self._check_api_key(context)

        response = await self.ConvertSource(
            docling_serve_pb2.ConvertSourceRequest(request=request.request),
            context,
        )
        yield docling_serve_pb2.ConvertSourceStreamResponse(response=response.response)

    async def WatchConvertSource(
        self,
        request: docling_serve_pb2.WatchConvertSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_pb2.WatchConvertSourceResponse]:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        sources = to_task_sources(request.request.sources)
        options = to_convert_options(
            request.request.options if request.request.HasField("options") else None
        )
        target = to_task_target(request.request.target if request.request.HasField("target") else None)

        task = await self._orchestrator.enqueue(
            task_type=TaskType.CONVERT,
            sources=sources,
            convert_options=options,
            target=target,
        )

        async for status in self._poll_status_stream(task.task_id, context):
            yield docling_serve_pb2.WatchConvertSourceResponse(response=status)

    async def WatchChunkHierarchicalSource(
        self,
        request: docling_serve_pb2.WatchChunkHierarchicalSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_pb2.WatchChunkHierarchicalSourceResponse]:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        sources = to_task_sources(request.request.sources)
        options = to_convert_options(
            request.request.convert_options
            if request.request.HasField("convert_options")
            else None
        )
        target = to_task_target(request.request.target if request.request.HasField("target") else None)
        chunking_options = to_hierarchical_chunk_options(
            request.request.chunking_options if request.request.HasField("chunking_options") else None
        )
        export_options = ChunkingExportOptions(
            include_converted_doc=request.request.include_converted_doc
        )

        task = await self._orchestrator.enqueue(
            task_type=TaskType.CHUNK,
            sources=sources,
            convert_options=options,
            chunking_options=chunking_options,
            chunking_export_options=export_options,
            target=target,
        )

        async for status in self._poll_status_stream(task.task_id, context):
            yield docling_serve_pb2.WatchChunkHierarchicalSourceResponse(response=status)

    async def WatchChunkHybridSource(
        self,
        request: docling_serve_pb2.WatchChunkHybridSourceRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_pb2.WatchChunkHybridSourceResponse]:
        await self._check_api_key(context)
        await self._ensure_queue_started()

        sources = to_task_sources(request.request.sources)
        options = to_convert_options(
            request.request.convert_options
            if request.request.HasField("convert_options")
            else None
        )
        target = to_task_target(request.request.target if request.request.HasField("target") else None)
        chunking_options = to_hybrid_chunk_options(
            request.request.chunking_options if request.request.HasField("chunking_options") else None
        )
        export_options = ChunkingExportOptions(
            include_converted_doc=request.request.include_converted_doc
        )

        task = await self._orchestrator.enqueue(
            task_type=TaskType.CHUNK,
            sources=sources,
            convert_options=options,
            chunking_options=chunking_options,
            chunking_export_options=export_options,
            target=target,
        )

        async for status in self._poll_status_stream(task.task_id, context):
            yield docling_serve_pb2.WatchChunkHybridSourceResponse(response=status)


async def serve(host: str, port: int) -> None:
    from .schema_validator import validate_docling_document_schema

    validate_docling_document_schema()

    server = grpc.aio.server()
    service = DoclingServeGrpcService()
    await service.start()
    docling_serve_pb2_grpc.add_DoclingServeServiceServicer_to_server(service, server)
    server.add_insecure_port(f"{host}:{port}")
    await server.start()
    _log.info("gRPC server started on %s:%s", host, port)
    try:
        await server.wait_for_termination()
    finally:
        await service.close()

"""Fork-owned document streaming service (DocumentStreamEnvelope).

Phase 1 is honest: status events around a real conversion, then
``final_document`` payload(s). ``DocumentNode`` parts are reserved until the
pipeline can emit partial items — we do not fake page yields from a finished
document.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from typing import Optional

import grpc

from docling_jobkit.datamodel.task_meta import TaskType

from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_stream_pb2,
    docling_serve_stream_pb2_grpc,
)
from docling_serve.grpc.mapping import (
    document_response_to_proto,
    requested_output_formats,
    to_convert_options,
    with_single_use_cleanup,
)
from docling_serve.grpc.server import DoclingServeGrpcService
from docling_serve.settings import docling_serve_settings

_log = logging.getLogger(__name__)


class DoclingStreamingGrpcService(
    docling_serve_stream_pb2_grpc.DoclingStreamingServiceServicer
):
    """Server-streaming convert feed owned by this fork."""

    def __init__(self, convert_service: DoclingServeGrpcService) -> None:
        self._convert = convert_service

    def _envelope(
        self,
        *,
        request_id: Optional[str],
        sequence: int,
        source_index: Optional[int] = None,
        status: Optional[docling_serve_stream_pb2.StreamStatus] = None,
        final_document=None,
        source_result: Optional[docling_serve_stream_pb2.StreamSourceResult] = None,
        error: Optional[docling_serve_stream_pb2.StreamError] = None,
    ) -> docling_serve_stream_pb2.StreamDocumentResponse:
        msg = docling_serve_stream_pb2.StreamDocumentResponse(
            sequence_number=sequence,
            timestamp_ms=int(time.time() * 1000),
        )
        if request_id:
            msg.request_id = request_id
        if source_index is not None:
            msg.source_index = source_index
        if status is not None:
            msg.status.CopyFrom(status)
        elif final_document is not None:
            msg.final_document.CopyFrom(final_document)
        elif source_result is not None:
            msg.source_result.CopyFrom(source_result)
        elif error is not None:
            msg.error.CopyFrom(error)
        return msg

    async def StreamDocument(
        self,
        request: docling_serve_stream_pb2.StreamDocumentRequest,
        context: grpc.aio.ServicerContext,
    ) -> AsyncIterator[docling_serve_stream_pb2.StreamDocumentResponse]:
        await self._convert._check_api_key(context)
        await self._convert._ensure_queue_started()

        request_id = request.request_id if request.HasField("request_id") else None
        seq = 0

        def next_seq() -> int:
            nonlocal seq
            seq += 1
            return seq

        yield self._envelope(
            request_id=request_id,
            sequence=next_seq(),
            status=docling_serve_stream_pb2.StreamStatus(
                phase=docling_serve_stream_pb2.StreamStatus.PHASE_QUEUED,
                message="queued",
            ),
        )

        convert_request = request.request
        requested_formats = requested_output_formats(
            convert_request.options if convert_request.HasField("options") else None
        )
        sources = await self._convert._parse_sources(convert_request.sources, context)
        if sources is None:
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                error=docling_serve_stream_pb2.StreamError(
                    code="INVALID_ARGUMENT",
                    message="Invalid or empty sources.",
                    terminal=True,
                ),
            )
            return

        options = to_convert_options(
            convert_request.options if convert_request.HasField("options") else None
        )
        self._convert._ensure_doc_format(options, requested_formats)
        target = self._convert._parse_target(convert_request)
        options = await self._convert._enforce_policy(
            context, sources, options, target
        )
        if options is None:
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                error=docling_serve_stream_pb2.StreamError(
                    code="INVALID_ARGUMENT",
                    message="Request rejected by server policy.",
                    terminal=True,
                ),
            )
            return

        yield self._envelope(
            request_id=request_id,
            sequence=next_seq(),
            status=docling_serve_stream_pb2.StreamStatus(
                phase=docling_serve_stream_pb2.StreamStatus.PHASE_STARTED,
                message="started",
                num_docs=len(sources),
            ),
        )

        task = await self._convert._orchestrator.enqueue(
            task_type=TaskType.CONVERT,
            sources=sources,
            convert_options=options,
            target=target,
        )

        # Phase 1: poll for status updates (same honesty as Watch*), then emit
        # final_document. DocumentNode parts wait for pipeline hooks.
        while not context.done():
            task_status = await self._convert._orchestrator.task_status(
                task_id=task.task_id
            )
            position = await self._convert._orchestrator.get_queue_position(
                task_id=task.task_id
            )
            meta = getattr(task_status, "task_status_meta", None) or getattr(
                task_status, "meta", None
            )
            status_kwargs: dict = {
                "phase": docling_serve_stream_pb2.StreamStatus.PHASE_PROCESSING,
                "message": str(getattr(task_status, "task_status", "processing")),
            }
            if position is not None:
                status_kwargs["queue_position"] = int(position)
            if meta is not None:
                for field, attr in (
                    ("num_docs", "num_docs"),
                    ("num_processed", "num_processed"),
                    ("num_succeeded", "num_succeeded"),
                    ("num_failed", "num_failed"),
                ):
                    value = getattr(meta, attr, None)
                    if value is not None:
                        status_kwargs[field] = int(value)
                total = status_kwargs.get("num_docs")
                processed = status_kwargs.get("num_processed")
                if total and processed is not None and total > 0:
                    status_kwargs["progress_percentage"] = float(processed) / float(
                        total
                    )

            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                status=docling_serve_stream_pb2.StreamStatus(**status_kwargs),
            )

            if task_status.is_completed():
                break
            await asyncio.sleep(docling_serve_settings.sync_poll_interval)
        else:
            return

        task_result = await self._convert._orchestrator.task_result(task_id=task.task_id)
        if task_result is None:
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                error=docling_serve_stream_pb2.StreamError(
                    code="NOT_FOUND",
                    message="Task result not found.",
                    terminal=True,
                ),
            )
            return

        if not hasattr(task_result.result, "content"):
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                error=docling_serve_stream_pb2.StreamError(
                    code="INVALID_ARGUMENT",
                    message="Conversion result is not an in-body document.",
                    terminal=True,
                ),
            )
            return

        doc_proto = document_response_to_proto(
            task_result.result.content, requested_formats
        )
        filename = doc_proto.filename or ""

        yield self._envelope(
            request_id=request_id,
            sequence=next_seq(),
            source_index=0,
            source_result=docling_serve_stream_pb2.StreamSourceResult(
                source_index=0,
                filename=filename,
                success=True,
                document_name=doc_proto.doc.name if doc_proto.HasField("doc") else "",
            ),
        )

        if doc_proto.HasField("doc"):
            yield self._envelope(
                request_id=request_id,
                sequence=next_seq(),
                source_index=0,
                final_document=doc_proto.doc,
            )

        yield self._envelope(
            request_id=request_id,
            sequence=next_seq(),
            status=docling_serve_stream_pb2.StreamStatus(
                phase=docling_serve_stream_pb2.StreamStatus.PHASE_COMPLETED,
                message="completed",
                progress_percentage=1.0,
                num_docs=len(sources),
                num_processed=len(sources),
                num_succeeded=1,
                num_failed=0,
            ),
        )

        with_single_use_cleanup(self._convert._orchestrator, task.task_id)
        _log.info(
            "StreamDocument finished request_id=%s sequences=%s",
            request_id,
            seq,
        )

from fastapi import BackgroundTasks, Response

from docling.datamodel.service.responses import (
    ChunkDocumentResponse,
    ChunkedDocumentResult,
    ConvertDocumentResponse,
    DoclingTaskResult,
    ExportDocumentResponse,
    ExportResult,
    PresignedArtifactResult,
    PresignedUrlConvertDocumentResponse,
    PresignedUrlConvertResponse,
    RemoteTargetResult,
    ZipArchiveResult,
)
from docling_core.types.doc.document import DocItem, DoclingDocument, RefItem
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
)

from docling_serve.datamodel.chunking import (
    ChunkDocumentResponseWithProvenance,
    ChunkedDocItem,
    ChunkedDocumentResultItemWithProvenance,
)
from docling_serve.settings import docling_serve_settings


class ChunkProvenanceResolutionError(ValueError):
    pass


async def prepare_response(
    task_id: str,
    task_result: DoclingTaskResult,
    orchestrator: BaseOrchestrator,
    background_tasks: BackgroundTasks,
    provenance_keep_converted_doc: bool | None = None,
):
    response: (
        Response
        | ConvertDocumentResponse
        | PresignedUrlConvertDocumentResponse
        | PresignedUrlConvertResponse
        | ChunkDocumentResponse
        | ChunkDocumentResponseWithProvenance
    )
    if isinstance(task_result.result, ExportResult):
        response = ConvertDocumentResponse(
            document=task_result.result.document,
            status=task_result.result.status,
            processing_time=task_result.processing_time,
            timings=task_result.result.timings,
            errors=task_result.result.errors,
            confidence=task_result.result.confidence,
        )
    elif isinstance(task_result.result, ZipArchiveResult):
        response = Response(
            content=task_result.result.content,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="converted_docs.zip"'
            },
        )
    elif isinstance(task_result.result, RemoteTargetResult):
        response = PresignedUrlConvertDocumentResponse(
            processing_time=task_result.processing_time,
            num_converted=task_result.num_converted,
            num_succeeded=task_result.num_succeeded,
            num_partially_succeeded=task_result.num_partially_succeeded,
            num_failed=task_result.num_failed,
        )
    elif isinstance(task_result.result, PresignedArtifactResult):
        response = PresignedUrlConvertResponse(
            documents=task_result.result.documents,
            processing_time=task_result.processing_time,
            num_converted=task_result.num_converted,
            num_succeeded=task_result.num_succeeded,
            num_partially_succeeded=task_result.num_partially_succeeded,
            num_failed=task_result.num_failed,
        )
    elif isinstance(task_result.result, ChunkedDocumentResult):
        chunk_response = ChunkDocumentResponse(
            chunks=task_result.result.chunks,
            documents=task_result.result.documents,
            processing_time=task_result.processing_time,
        )
        if provenance_keep_converted_doc is None:
            response = chunk_response
        else:
            response = resolve_chunk_provenance(
                chunk_response,
                keep_converted_doc=provenance_keep_converted_doc,
            )
    else:
        raise ValueError("Unknown result type")

    if docling_serve_settings.single_use_results:
        background_tasks.add_task(orchestrator.on_result_fetched, task_id)

    return response


def resolve_chunk_provenance(
    response: ChunkDocumentResponse,
    keep_converted_doc: bool,
) -> ChunkDocumentResponseWithProvenance:
    converted_docs: dict[str, DoclingDocument] = {}
    filenames: set[str] = set()
    for doc_result in response.documents:
        filename = doc_result.document.filename
        if filename in filenames:
            raise ChunkProvenanceResolutionError(
                f"Cannot resolve provenance for duplicate document filename {filename!r}."
            )
        filenames.add(filename)
        if doc_result.document.json_content is not None:
            converted_docs[filename] = doc_result.document.json_content

    chunks: list[ChunkedDocumentResultItemWithProvenance] = []
    for chunk in response.chunks:
        doc = converted_docs.get(chunk.filename)
        if doc is None:
            raise ChunkProvenanceResolutionError(
                f"Cannot resolve provenance without a converted document for {chunk.filename!r}."
            )

        resolved: list[ChunkedDocItem] = []
        for ref in chunk.doc_items:
            try:
                item = RefItem(cref=ref).resolve(doc)
            except (
                AttributeError,
                IndexError,
                KeyError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as exc:
                raise ChunkProvenanceResolutionError(
                    f"Cannot resolve document item {ref!r} for {chunk.filename!r}."
                ) from exc
            if not isinstance(item, DocItem):
                raise ChunkProvenanceResolutionError(
                    f"Document reference {ref!r} for {chunk.filename!r} is not a document item."
                )
            if item.self_ref != ref:
                raise ChunkProvenanceResolutionError(
                    f"Cannot resolve document item {ref!r} for {chunk.filename!r}."
                )
            resolved.append(
                ChunkedDocItem(
                    self_ref=ref,
                    label=item.label,
                    prov=item.prov,
                )
            )
        chunks.append(
            ChunkedDocumentResultItemWithProvenance(
                **chunk.model_dump(exclude={"doc_items"}),
                doc_items=resolved,
            )
        )

    documents = response.documents
    if not keep_converted_doc:
        documents = [
            doc_result.model_copy(
                update={
                    "document": ExportDocumentResponse(
                        filename=doc_result.document.filename
                    )
                }
            )
            for doc_result in response.documents
        ]

    return ChunkDocumentResponseWithProvenance(
        chunks=chunks,
        documents=documents,
        processing_time=response.processing_time,
    )

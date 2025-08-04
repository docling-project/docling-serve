import asyncio
import logging
import os
import shutil
import time
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Union

import httpx
from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from docling.datamodel.base_models import OutputFormat
from docling.datamodel.document import ConversionResult, ConversionStatus
from docling_core.types.doc import ImageRefMode
from docling_jobkit.datamodel.convert import ConvertDocumentsOptions
from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_targets import InBodyTarget, PutTarget, TaskTarget
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
)

from docling_serve.datamodel.convert import ChunkingOptions
from docling_serve.datamodel.responses import (
    ChunkedDocumentResponse,
    ChunkedDocumentResponseItem,
    ConvertDocumentResponse,
    DocumentResponse,
    PresignedUrlConvertDocumentResponse,
)
from docling_serve.settings import docling_serve_settings
from docling_serve.storage import get_scratch

_log = logging.getLogger(__name__)


@lru_cache(maxsize=8)  # Cache up to 8 different tokenizer models
def _get_cached_huggingface_tokenizer(tokenizer_model: str):
    """Cache the HuggingFace tokenizer loading."""
    try:
        from transformers import AutoTokenizer

        return AutoTokenizer.from_pretrained(tokenizer_model)
    except Exception as e:
        _log.warning(f"Failed to load tokenizer model {tokenizer_model}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to initialize tokenizer '{tokenizer_model}': {e}. Please check the model name and ensure it's available on HuggingFace Hub.",
        )


def _create_tokenizer(chunking_options: ChunkingOptions):
    """Create a HuggingFace tokenizer for chunking."""
    try:
        from docling_core.transforms.chunker.tokenizer.huggingface import (
            HuggingFaceTokenizer,
        )
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Chunking dependencies not available: {e}. Install with 'pip install docling[chunking]' or 'pip install docling-core[chunking]'",
        )

    # Use specified tokenizer model or default
    tokenizer_model = (
        chunking_options.tokenizer or "Qwen/Qwen3-Embedding-0.6B"
    )

    # Update the chunking_options
    if chunking_options.tokenizer is None:
        chunking_options.tokenizer = tokenizer_model

    # Get cached HuggingFace tokenizer
    hf_tokenizer = _get_cached_huggingface_tokenizer(tokenizer_model)

    # Create the wrapper with max_tokens
    return HuggingFaceTokenizer(
        tokenizer=hf_tokenizer,
        max_tokens=chunking_options.max_tokens,
    )


def _extract_page_numbers(chunk) -> list[int] | None:
    """Extract page numbers from chunk metadata."""
    page_numbers = set()
    if (
        hasattr(chunk, "meta")
        and chunk.meta
        and hasattr(chunk.meta, "doc_items")
        and getattr(chunk.meta, "doc_items", None)
    ):
        for doc_item in chunk.meta.doc_items:
            if hasattr(doc_item, "prov") and doc_item.prov:
                for prov in doc_item.prov:
                    if hasattr(prov, "page_no") and prov.page_no:
                        page_numbers.add(prov.page_no)
    return sorted(page_numbers) if page_numbers else None


def _chunk_document(
    conv_res: ConversionResult,
    chunking_options: ChunkingOptions,
) -> list[ChunkedDocumentResponseItem]:
    """Chunk a document using HybridChunker with optional markdown table serialization."""
    try:
        from docling_core.transforms.chunker.hierarchical_chunker import (
            ChunkingDocSerializer,
            ChunkingSerializerProvider,
        )
        from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
        from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
    except ImportError as e:
        raise HTTPException(
            status_code=500,
            detail=f"Chunking dependencies not available: {e}. Install with 'pip install docling[chunking]' or 'pip install docling-core[chunking]'",
        )

    # Configure tokenizer
    tokenizer = _create_tokenizer(chunking_options)

    # Configure serializer provider
    if chunking_options.use_markdown_tables:

        class MDTableSerializerProvider(ChunkingSerializerProvider):
            def get_serializer(self, doc):
                return ChunkingDocSerializer(
                    doc=doc,
                    table_serializer=MarkdownTableSerializer(),
                )

        serializer_provider: ChunkingSerializerProvider = MDTableSerializerProvider()
    else:
        serializer_provider = ChunkingSerializerProvider()

    # Initialize chunker
    chunker = HybridChunker(
        tokenizer=tokenizer,
        serializer_provider=serializer_provider,
        merge_peers=chunking_options.merge_peers,
    )

    # Generate chunks
    chunk_iter = chunker.chunk(dl_doc=conv_res.document)
    chunks = list(chunk_iter)

    # Convert to response items
    chunk_items = []
    for i, chunk in enumerate(chunks):
        # Extract metadata from chunk
        metadata = {}

        if hasattr(chunk, "meta") and chunk.meta:
            metadata = {
                "doc_items": getattr(chunk.meta, "doc_items", None),
            }

        # Extract page numbers
        page_numbers_list = _extract_page_numbers(chunk)

        # Extract headings from chunk metadata
        headings = None
        if (
            hasattr(chunk, "meta")
            and chunk.meta
            and hasattr(chunk.meta, "headings")
            and getattr(chunk.meta, "headings", None)
        ):
            headings = getattr(chunk.meta, "headings", None)

        # Get contextualized text
        contextualized_text = chunker.contextualize(chunk=chunk)

        chunk_item = ChunkedDocumentResponseItem(
            filename=conv_res.input.file.name,
            chunk_index=i,
            contextualized_text=contextualized_text,
            chunk_text=chunk.text if chunking_options.include_raw_text else None,
            headings=headings,
            page_numbers=page_numbers_list,
            metadata=metadata,
        )
        chunk_items.append(chunk_item)

    return chunk_items


def _export_document_as_content(
    conv_res: ConversionResult,
    export_json: bool,
    export_html: bool,
    export_md: bool,
    export_txt: bool,
    export_doctags: bool,
    image_mode: ImageRefMode,
    md_page_break_placeholder: str,
):
    document = DocumentResponse(filename=conv_res.input.file.name)

    if conv_res.status == ConversionStatus.SUCCESS:
        new_doc = conv_res.document._make_copy_with_refmode(
            Path(), image_mode, page_no=None
        )

        # Create the different formats
        if export_json:
            document.json_content = new_doc
        if export_html:
            document.html_content = new_doc.export_to_html(image_mode=image_mode)
        if export_txt:
            document.text_content = new_doc.export_to_markdown(
                strict_text=True,
                image_mode=image_mode,
            )
        if export_md:
            document.md_content = new_doc.export_to_markdown(
                image_mode=image_mode,
                page_break_placeholder=md_page_break_placeholder or None,
            )
        if export_doctags:
            document.doctags_content = new_doc.export_to_doctags()
    elif conv_res.status == ConversionStatus.SKIPPED:
        raise HTTPException(status_code=400, detail=conv_res.errors)
    else:
        raise HTTPException(status_code=500, detail=conv_res.errors)

    return document


def _export_documents_as_files(
    conv_results: Iterable[ConversionResult],
    output_dir: Path,
    export_json: bool,
    export_html: bool,
    export_md: bool,
    export_txt: bool,
    export_doctags: bool,
    image_export_mode: ImageRefMode,
    md_page_break_placeholder: str,
) -> ConversionStatus:
    success_count = 0
    failure_count = 0

    # Default failure in case results is empty
    conv_result = ConversionStatus.FAILURE

    artifacts_dir = Path("artifacts/")  # will be relative to the fname

    for conv_res in conv_results:
        conv_result = conv_res.status
        if conv_res.status == ConversionStatus.SUCCESS:
            success_count += 1
            doc_filename = conv_res.input.file.stem

            # Export JSON format:
            if export_json:
                fname = output_dir / f"{doc_filename}.json"
                _log.info(f"writing JSON output to {fname}")
                conv_res.document.save_as_json(
                    filename=fname,
                    image_mode=image_export_mode,
                    artifacts_dir=artifacts_dir,
                )

            # Export HTML format:
            if export_html:
                fname = output_dir / f"{doc_filename}.html"
                _log.info(f"writing HTML output to {fname}")
                conv_res.document.save_as_html(
                    filename=fname,
                    image_mode=image_export_mode,
                    artifacts_dir=artifacts_dir,
                )

            # Export Text format:
            if export_txt:
                fname = output_dir / f"{doc_filename}.txt"
                _log.info(f"writing TXT output to {fname}")
                conv_res.document.save_as_markdown(
                    filename=fname,
                    strict_text=True,
                    image_mode=ImageRefMode.PLACEHOLDER,
                )

            # Export Markdown format:
            if export_md:
                fname = output_dir / f"{doc_filename}.md"
                _log.info(f"writing Markdown output to {fname}")
                conv_res.document.save_as_markdown(
                    filename=fname,
                    artifacts_dir=artifacts_dir,
                    image_mode=image_export_mode,
                    page_break_placeholder=md_page_break_placeholder or None,
                )

            # Export Document Tags format:
            if export_doctags:
                fname = output_dir / f"{doc_filename}.doctags"
                _log.info(f"writing Doc Tags output to {fname}")
                conv_res.document.save_as_doctags(filename=fname)

        else:
            _log.warning(f"Document {conv_res.input.file} failed to convert.")
            failure_count += 1

    _log.info(
        f"Processed {success_count + failure_count} docs, "
        f"of which {failure_count} failed"
    )
    return conv_result


def process_results(
    conversion_options: ConvertDocumentsOptions,
    target: TaskTarget,
    conv_results: Iterable[ConversionResult],
    work_dir: Path,
) -> (
    ConvertDocumentResponse
    | ChunkedDocumentResponse
    | FileResponse
    | PresignedUrlConvertDocumentResponse
):
    # Let's start by processing the documents
    try:
        start_time = time.monotonic()

        # Convert the iterator to a list to count the number of results and get timings
        # As it's an iterator (lazy evaluation), it will also start the conversion
        conv_results = list(conv_results)

        processing_time = time.monotonic() - start_time

        _log.info(
            f"Processed {len(conv_results)} docs in {processing_time:.2f} seconds."
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if len(conv_results) == 0:
        raise HTTPException(
            status_code=500, detail="No documents were generated by Docling."
        )

    # We have some results, let's prepare the response
    response: Union[
        FileResponse,
        ConvertDocumentResponse,
        PresignedUrlConvertDocumentResponse,
        ChunkedDocumentResponse,
    ]

    # Check if chunking is enabled
    do_chunking = getattr(conversion_options, "do_chunking", False)
    chunking_options = getattr(conversion_options, "chunking_options", None)

    if do_chunking and chunking_options is None:
        chunking_options = ChunkingOptions()

    # If chunking is enabled, return chunked response
    if do_chunking:
        if len(conv_results) == 1:
            conv_res = conv_results[0]
            if conv_res.status == ConversionStatus.SUCCESS:
                assert chunking_options is not None
                chunks = _chunk_document(conv_res, chunking_options)
                response = ChunkedDocumentResponse(
                    chunks=chunks,
                    status=conv_res.status,
                    processing_time=processing_time,
                    timings=conv_res.timings,
                    chunking_info=chunking_options.model_dump()
                    if chunking_options
                    else {},
                )
            else:
                response = ChunkedDocumentResponse(
                    chunks=[],
                    status=conv_res.status,
                    errors=conv_res.errors,
                    processing_time=processing_time,
                    timings=conv_res.timings,
                    chunking_info=chunking_options.model_dump()
                    if chunking_options
                    else {},
                )
        else:
            # Multiple documents - chunk each one
            all_chunks = []
            assert chunking_options is not None
            for conv_res in conv_results:
                if conv_res.status == ConversionStatus.SUCCESS:
                    chunks = _chunk_document(conv_res, chunking_options)
                    all_chunks.extend(chunks)

            response = ChunkedDocumentResponse(
                chunks=all_chunks,
                status=ConversionStatus.SUCCESS
                if all_chunks
                else ConversionStatus.FAILURE,
                processing_time=processing_time,
                timings={},  # TODO: Aggregate timings from all results
                chunking_info=chunking_options.model_dump() if chunking_options else {},
            )
        return response

    # Booleans to know what to export
    export_json = OutputFormat.JSON in conversion_options.to_formats
    export_html = OutputFormat.HTML in conversion_options.to_formats
    export_md = OutputFormat.MARKDOWN in conversion_options.to_formats
    export_txt = OutputFormat.TEXT in conversion_options.to_formats
    export_doctags = OutputFormat.DOCTAGS in conversion_options.to_formats

    # Only 1 document was processed, and we are not returning it as a file
    if len(conv_results) == 1 and isinstance(target, InBodyTarget):
        conv_res = conv_results[0]
        document = _export_document_as_content(
            conv_res,
            export_json=export_json,
            export_html=export_html,
            export_md=export_md,
            export_txt=export_txt,
            export_doctags=export_doctags,
            image_mode=conversion_options.image_export_mode,
            md_page_break_placeholder=conversion_options.md_page_break_placeholder,
        )

        response = ConvertDocumentResponse(
            document=document,
            status=conv_res.status,
            processing_time=processing_time,
            timings=conv_res.timings,
        )

    # Multiple documents were processed, or we are forced returning as a file
    else:
        # Temporary directory to store the outputs
        output_dir = work_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Worker pid to use in archive identification as we may have multiple workers
        os.getpid()

        # Export the documents
        conv_result = _export_documents_as_files(
            conv_results=conv_results,
            output_dir=output_dir,
            export_json=export_json,
            export_html=export_html,
            export_md=export_md,
            export_txt=export_txt,
            export_doctags=export_doctags,
            image_export_mode=conversion_options.image_export_mode,
            md_page_break_placeholder=conversion_options.md_page_break_placeholder,
        )

        files = os.listdir(output_dir)
        if len(files) == 0:
            raise HTTPException(status_code=500, detail="No documents were exported.")

        file_path = work_dir / "converted_docs.zip"
        shutil.make_archive(
            base_name=str(file_path.with_suffix("")),
            format="zip",
            root_dir=output_dir,
        )

        # Other cleanups after the response is sent
        # Output directory
        # background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)

        if isinstance(target, PutTarget):
            try:
                with open(file_path, "rb") as file_data:
                    r = httpx.put(str(target.url), files={"file": file_data})
                    r.raise_for_status()
                response = PresignedUrlConvertDocumentResponse(
                    status=conv_result,
                    processing_time=processing_time,
                )
            except Exception as exc:
                _log.error("An error occour while uploading zip to s3", exc_info=exc)
                raise HTTPException(
                    status_code=500, detail="An error occour while uploading zip to s3."
                )
        else:
            response = FileResponse(
                file_path, filename=file_path.name, media_type="application/zip"
            )

    return response


async def prepare_response(
    task: Task, orchestrator: BaseOrchestrator, background_tasks: BackgroundTasks
):
    if task.results is None:
        raise HTTPException(
            status_code=404,
            detail="Task result not found. Please wait for a completion status.",
        )
    assert task.options is not None

    work_dir = get_scratch() / task.task_id
    response = process_results(
        conversion_options=task.options,
        target=task.target,
        conv_results=task.results,
        work_dir=work_dir,
    )

    if work_dir.exists():
        task.scratch_dir = work_dir
        if not isinstance(response, FileResponse):
            _log.warning(
                f"Task {task.task_id=} produced content in {work_dir=} but the response is not a file."
            )
            shutil.rmtree(work_dir, ignore_errors=True)

    if docling_serve_settings.single_use_results:
        if task.scratch_dir is not None:
            background_tasks.add_task(
                shutil.rmtree, task.scratch_dir, ignore_errors=True
            )

        async def _remove_task_impl():
            await asyncio.sleep(docling_serve_settings.result_removal_delay)
            await orchestrator.delete_task(task_id=task.task_id)

        async def _remove_task():
            asyncio.create_task(_remove_task_impl())  # noqa: RUF006

        background_tasks.add_task(_remove_task)

    return response

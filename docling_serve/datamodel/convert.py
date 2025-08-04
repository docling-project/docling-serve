# Define the input options for the API
from typing import Annotated, Optional

from pydantic import BaseModel, Field

from docling.datamodel.pipeline_options import (
    EasyOcrOptions,
)
from docling.models.factories import get_ocr_factory
from docling_jobkit.datamodel.convert import ConvertDocumentsOptions

from docling_serve.settings import docling_serve_settings

ocr_factory = get_ocr_factory(
    allow_external_plugins=docling_serve_settings.allow_external_plugins
)
ocr_engines_enum = ocr_factory.get_enum()


class ChunkingOptions(BaseModel):
    """Configuration options for document chunking using HybridChunker."""

    max_tokens: Annotated[
        int,
        Field(
            description="Maximum number of tokens per chunk.",
            gt=0,
            le=32768,  # Reasonable upper limit
        ),
    ] = 512

    overlap: Annotated[
        int,
        Field(
            description="Number of overlapping tokens between chunks.",
            ge=0,
        ),
    ] = 128

    tokenizer: Annotated[
        Optional[str],
        Field(
            description="HuggingFace model name for custom tokenization. If not specified, uses 'Qwen/Qwen3-Embedding-0.6B' as default.",
            examples=[
                "Qwen/Qwen3-Embedding-0.6B",
                "sentence-transformers/all-MiniLM-L6-v2",
                "microsoft/DialoGPT-medium",
            ],
        ),
    ] = None

    use_markdown_tables: Annotated[
        bool,
        Field(
            description="Use markdown table format instead of triplets for table serialization.",
        ),
    ] = False

    merge_peers: Annotated[
        bool,
        Field(
            description="Merge undersized successive chunks with same headings.",
        ),
    ] = True

    include_raw_text: Annotated[
        bool,
        Field(
            description="Include both chunk_text and contextualized_text in response. If False, only contextualized_text is included.",
        ),
    ] = True


class ConvertDocumentsRequestOptions(ConvertDocumentsOptions):
    ocr_engine: Annotated[  # type: ignore
        ocr_engines_enum,
        Field(
            description=(
                "The OCR engine to use. String. "
                f"Allowed values: {', '.join([v.value for v in ocr_engines_enum])}. "
                "Optional, defaults to easyocr."
            ),
            examples=[EasyOcrOptions.kind],
        ),
    ] = ocr_engines_enum(EasyOcrOptions.kind)  # type: ignore

    document_timeout: Annotated[
        float,
        Field(
            description="The timeout for processing each document, in seconds.",
            gt=0,
            le=docling_serve_settings.max_document_timeout,
        ),
    ] = docling_serve_settings.max_document_timeout

    do_chunking: Annotated[
        bool,
        Field(
            description="Whether to enable document chunking for RAG applications. When enabled, the response will contain chunks instead of the full document formats.",
            examples=[False],
        ),
    ] = False

    chunking_options: Annotated[
        ChunkingOptions,
        Field(
            description="Configuration options for document chunking. Supports parameters like max_tokens, overlap, tokenizer configuration, and markdown table serialization.",
        ),
    ] = ChunkingOptions()

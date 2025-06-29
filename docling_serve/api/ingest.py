# Ingestion API endpoint
# CUSTOM: This file is part of the new ingestion API

import asyncio
import tempfile
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, UploadFile, HTTPException, Form
from pydantic import HttpUrl

from docling_core.converter import DocumentConverter, ConverterConfig
from docling_core.document.docling_document import TextItem

from docling_serve.core.models import Chunk, ChunkMetadata, IngestionResponse

# Initialize router
# The prefix /v1 will be added when including this router in the main app
router = APIRouter(
    tags=["Ingestion"],
)

@router.post("/ingest", response_model=IngestionResponse)
async def ingest_document(
    file: Optional[UploadFile] = File(None, description="Document file to ingest."),
    source: Optional[HttpUrl] = Form(None, description="URL of the document to ingest.") # Using Form for HttpUrl to be part of form-data
):
    """
    Ingests a document from a file upload or URL, parses it,
    and returns extracted text chunks with basic metadata.
    """
    if not file and not source:
        raise HTTPException(
            status_code=400,
            detail="Either a file must be uploaded or a source URL must be provided.",
        )

    input_path_or_url = None
    temp_file_path = None
    doc_name = "untitled_document"

    try:
        if file:
            doc_name = Path(file.filename).stem if file.filename else "uploaded_file"
            # Save UploadFile to a temporary file
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix if file.filename else ".tmp") as tmp_file:
                tmp_file.write(await file.read())
                temp_file_path = tmp_file.name
            input_path_or_url = temp_file_path
        elif source:
            doc_name = Path(str(source)).stem
            input_path_or_url = str(source)

        if not input_path_or_url: # Should be caught by the initial check, but as a safeguard
            raise HTTPException(status_code=500, detail="Input source could not be determined.")

        # Initialize DocumentConverter
        # Using default OCR and layout backends as specified
        converter = DocumentConverter(
            config=ConverterConfig(ocr_backend="default", layout_backend="default")
        )

        # Perform conversion - run blocking I/O in a thread
        # print(f"DEBUG: Converting document from: {input_path_or_url}")
        result = await asyncio.to_thread(converter.convert, input_path_or_url)
        doc = result.document  # DoclingDocument

        extracted_chunks: list[Chunk] = []
        if doc and doc.texts:
            for text_item in doc.texts:
                if not isinstance(text_item, TextItem): # Ensure it's a TextItem
                    continue

                text_content = text_item.text
                if not text_content or text_content.isspace():
                    continue

                # Skip headers and footers as per requirements
                # Assuming standard labels from Docling. If custom, this might need adjustment.
                if text_item.label in ["PAGE_HEADER", "PAGE_FOOTER"]:
                    continue

                page_number: Optional[int] = None
                if text_item.prov and len(text_item.prov) > 0:
                    # Assuming prov[0] is the primary provenance for the item
                    page_number = text_item.prov[0].page_no

                metadata = ChunkMetadata(page=page_number)
                chunk = Chunk(text=text_content, metadata=metadata)
                extracted_chunks.append(chunk)

        # print(f"DEBUG: Extracted {len(extracted_chunks)} chunks for {doc_name}")
        return IngestionResponse(chunks=extracted_chunks, doc_name=doc_name)

    except HTTPException: # Re-raise HTTPExceptions
        raise
    except Exception as e:
        # print(f"DEBUG: Error during ingestion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing document: {str(e)}")
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            os.remove(temp_file_path)
        if file:
            await file.close()

@router.get("/ingest/health", status_code=200)
async def health_check():
    """Simple health check for the ingestion endpoint."""
    return {"status": "ok"}

# Pydantic models for ingestion API
# CUSTOM: This file is part of the new ingestion API support modules

from typing import List, Optional

from pydantic import BaseModel, HttpUrl

class ChunkMetadata(BaseModel):
    """
    Metadata for a single text chunk.
    """
    page: Optional[int] = None
    # Further metadata fields can be added here in subsequent tasks

class Chunk(BaseModel):
    """
    A single text chunk extracted from a document.
    """
    text: str
    metadata: ChunkMetadata

class IngestionRequest(BaseModel): # Added for completeness, though not strictly required by plan for response
    """
    Model for the ingestion request if we want to support JSON body for URL.
    Not directly used if only form-data for file and query/path for URL.
    However, the task mentioned "JSON with a file URL", this could model that.
    """
    source: HttpUrl

class IngestionResponse(BaseModel):
    """
    Response model for the document ingestion endpoint.
    """
    chunks: List[Chunk]
    doc_name: str
    # doc_id: Optional[str] = None # To be added in Task 3

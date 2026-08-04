from pydantic import BaseModel, Field, create_model

from docling.datamodel.service.chunking import (
    HierarchicalChunkerOptions,
    HybridChunkerOptions,
)
from docling.datamodel.service.responses import (
    ChunkDocumentResponse,
    ChunkedDocumentResultItem,
)
from docling_core.types.doc.document import ProvenanceItem

_INCLUDE_PROVENANCE_DESCRIPTION = (
    "Return each doc_items entry as an object with self_ref, label and the "
    "resolved prov array (page_no, bbox, charspan) instead of a bare reference. "
    "Requires an in-body target and a non-referenced image export mode."
)


class HybridChunkerOptionsWithProvenance(HybridChunkerOptions):
    include_provenance: bool = Field(
        default=False,
        description=_INCLUDE_PROVENANCE_DESCRIPTION,
    )


class HierarchicalChunkerOptionsWithProvenance(HierarchicalChunkerOptions):
    include_provenance: bool = Field(
        default=False,
        description=_INCLUDE_PROVENANCE_DESCRIPTION,
    )


ProvenanceChunkerOptions = (
    HybridChunkerOptionsWithProvenance | HierarchicalChunkerOptionsWithProvenance
)


class ChunkedDocItem(BaseModel):
    self_ref: str = Field(description="Reference of the item in the document.")
    label: str = Field(description="Label of the document item.")
    prov: list[ProvenanceItem] = Field(
        default_factory=list,
        description="Provenance of the item, including page number and bounding box.",
    )


ChunkedDocumentResultItemWithProvenance = create_model(
    "ChunkedDocumentResultItemWithProvenance",
    __base__=ChunkedDocumentResultItem,
    doc_items=(
        list[ChunkedDocItem],
        Field(description="Document items with resolved provenance"),
    ),
)

ChunkDocumentResponseWithProvenance = create_model(
    "ChunkDocumentResponseWithProvenance",
    __base__=ChunkDocumentResponse,
    chunks=(list[ChunkedDocumentResultItemWithProvenance], ...),
)


ChunkDocumentResponseModel = ChunkDocumentResponse | ChunkDocumentResponseWithProvenance

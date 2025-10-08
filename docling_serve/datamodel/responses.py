import enum
from typing import Optional, List, Tuple

from pydantic import BaseModel, Field

from docling.datamodel.document import ConversionStatus, ErrorItem
from docling.utils.profiling import ProfilingItem
from docling_jobkit.datamodel.result import (
    ChunkedDocumentResultItem,
    ExportDocumentResponse,
    ExportResult,
)
from docling_jobkit.datamodel.task_meta import TaskProcessingMeta, TaskType


# Status
class HealthCheckResponse(BaseModel):
    status: str = "ok"


class ClearResponse(BaseModel):
    status: str = "ok"


class ConvertDocumentResponse(BaseModel):
    document: ExportDocumentResponse
    status: ConversionStatus
    errors: list[ErrorItem] = []
    processing_time: float
    timings: dict[str, ProfilingItem] = {}


class PresignedUrlConvertDocumentResponse(BaseModel):
    processing_time: float
    num_converted: int
    num_succeeded: int
    num_failed: int


class ConvertDocumentErrorResponse(BaseModel):
    status: ConversionStatus


class ChunkDocumentResponse(BaseModel):
    chunks: list[ChunkedDocumentResultItem]
    documents: list[ExportResult]
    processing_time: float


class TaskStatusResponse(BaseModel):
    task_id: str
    task_type: TaskType
    task_status: str
    task_position: Optional[int] = None
    task_meta: Optional[TaskProcessingMeta] = None
    queue_size: Optional[int] = None


class MessageKind(str, enum.Enum):
    CONNECTION = "connection"
    UPDATE = "update"
    ERROR = "error"


class WebsocketMessage(BaseModel):
    message: MessageKind
    task: Optional[TaskStatusResponse] = None
    error: Optional[str] = None


class Provenance(BaseModel):
    page_num: int = Field(-1, description="Page number")
    l: float = Field(-1, description="Left border of bounding box")
    t: float = Field(-1, description="Top border of bounding box")
    r: float = Field(-1, description="Right border of bounding box")
    b: float = Field(-1, description="Bottom border of bounding box")
    charspan: Tuple[int, int] = Field([0,0], description="Character span of text within this doc item")


class DocItem(BaseModel):
    self_ref: str = Field("", description="Element of page")
    prov: List[Provenance] = Field([], description="Provenance of chunk")
    

class ChunkResponse(BaseModel):
    """
    Collection of embedding responses.
    """
    chunk: str = Field("", description="Text of chunk")
    doc_items: List[DocItem] = Field([], description="Doc items within chunk")
    


class ChunkResponses(BaseModel):
    """
    Collection of embedding responses.
    """
    chunks: List[ChunkResponse] = Field([], description="Chunks in doc")
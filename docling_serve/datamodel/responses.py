import enum
from typing import Optional

from pydantic import BaseModel

from docling.datamodel.document import ConversionStatus, ErrorItem
from docling.utils.profiling import ProfilingItem
from docling_core.types.doc import DoclingDocument
from docling_jobkit.datamodel.task_meta import TaskProcessingMeta


# Status
class HealthCheckResponse(BaseModel):
    status: str = "ok"


class ClearResponse(BaseModel):
    status: str = "ok"


class DocumentResponse(BaseModel):
    filename: str
    md_content: Optional[str] = None
    json_content: Optional[DoclingDocument] = None
    html_content: Optional[str] = None
    text_content: Optional[str] = None
    doctags_content: Optional[str] = None


class ConvertDocumentResponse(BaseModel):
    document: DocumentResponse
    status: ConversionStatus
    errors: list[ErrorItem] = []
    processing_time: float
    timings: dict[str, ProfilingItem] = {}


class ConvertDocumentErrorResponse(BaseModel):
    status: ConversionStatus


class TaskStatusResponse(BaseModel):
    task_id: str
    task_status: str
    task_position: Optional[int] = None
    task_meta: Optional[TaskProcessingMeta] = None


class MessageKind(str, enum.Enum):
    CONNECTION = "connection"
    UPDATE = "update"
    ERROR = "error"


class WebsocketMessage(BaseModel):
    message: MessageKind
    task: Optional[TaskStatusResponse] = None
    error: Optional[str] = None

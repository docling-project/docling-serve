import enum
from typing import Optional

from pydantic import BaseModel

from docling_serve.datamodel.requests import ConvertDocumentsRequest
from docling_serve.datamodel.responses import ConvertDocumentResponse


class TaskStatus(str, enum.Enum):
    SUCCESS = "success"
    PENDING = "pending"
    STARTED = "started"
    FAILURE = "failure"


class AsyncEngine(str, enum.Enum):
    LOCAL = "local"
    KFP = "kfp"


class TaskProcessingMeta(BaseModel):
    num_docs: int
    num_processed: int = 0
    num_success: int = 0
    num_failed: int = 0


class Task(BaseModel):
    task_id: str
    task_status: TaskStatus = TaskStatus.PENDING
    request: Optional[ConvertDocumentsRequest]
    result: Optional[ConvertDocumentResponse] = None
    processing_meta: Optional[TaskProcessingMeta] = None

    def is_completed(self) -> bool:
        if self.task_status in [TaskStatus.SUCCESS, TaskStatus.FAILURE]:
            return True
        return False

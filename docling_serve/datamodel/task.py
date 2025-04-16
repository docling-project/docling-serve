from typing import Optional

from pydantic import BaseModel

from docling_serve.datamodel.engines import TaskStatus
from docling_serve.datamodel.requests import ConvertDocumentsRequest
from docling_serve.datamodel.responses import ConvertDocumentResponse
from docling_serve.datamodel.task_meta import TaskProcessingMeta


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

from typing import Optional, Union

from pydantic import BaseModel

from docling.datamodel.base_models import DocumentStream

from docling_serve.datamodel.convert import ConvertDocumentsOptions
from docling_serve.datamodel.engines import TaskStatus
from docling_serve.datamodel.requests import FileSource, HttpSource
from docling_serve.datamodel.responses import ConvertDocumentResponse
from docling_serve.datamodel.task_meta import TaskProcessingMeta

TaskSource = Union[HttpSource, FileSource, DocumentStream]


class Task(BaseModel):
    task_id: str
    task_status: TaskStatus = TaskStatus.PENDING
    sources: list[TaskSource] = []
    options: Optional[ConvertDocumentsOptions]
    result: Optional[ConvertDocumentResponse] = None
    processing_meta: Optional[TaskProcessingMeta] = None

    def is_completed(self) -> bool:
        if self.task_status in [TaskStatus.SUCCESS, TaskStatus.FAILURE]:
            return True
        return False

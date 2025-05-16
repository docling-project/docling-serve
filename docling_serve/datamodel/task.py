import datetime
from functools import partial
from pathlib import Path
from typing import Optional, Union

from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from docling.datamodel.base_models import DocumentStream

from docling_serve.datamodel.convert import ConvertDocumentsOptions
from docling_serve.datamodel.engines import TaskStatus
from docling_serve.datamodel.requests import FileSource, HttpSource
from docling_serve.datamodel.responses import ConvertDocumentResponse
from docling_serve.datamodel.task_meta import TaskProcessingMeta

TaskSource = Union[HttpSource, FileSource, DocumentStream]


class Task(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    task_id: str
    task_status: TaskStatus = TaskStatus.PENDING
    sources: list[TaskSource] = []
    options: Optional[ConvertDocumentsOptions]
    result: Optional[Union[ConvertDocumentResponse, FileResponse]] = None
    scratch_dir: Optional[Path] = None
    processing_meta: Optional[TaskProcessingMeta] = None
    created_at: datetime.datetime = Field(
        default_factory=partial(datetime.datetime.now, datetime.timezone.utc)
    )
    started_at: Optional[datetime.datetime] = None
    finished_at: Optional[datetime.datetime] = None
    last_update_at: datetime.datetime = Field(
        default_factory=partial(datetime.datetime.now, datetime.timezone.utc)
    )

    def set_status(self, status: TaskStatus):
        now = datetime.datetime.now(datetime.timezone.utc)
        if status == TaskStatus.STARTED and self.started_at is None:
            self.started_at = now
        if (
            status in [TaskStatus.SUCCESS, TaskStatus.FAILURE]
            and self.finished_at is None
        ):
            self.finished_at = now

        self.last_update_at = now
        self.task_status = status

    def is_completed(self) -> bool:
        if self.task_status in [TaskStatus.SUCCESS, TaskStatus.FAILURE]:
            return True
        return False

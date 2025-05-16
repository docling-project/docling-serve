from abc import ABC, abstractmethod
from typing import Optional, Union

from fastapi import BackgroundTasks
from fastapi.responses import FileResponse

from docling_serve.datamodel.convert import ConvertDocumentsOptions
from docling_serve.datamodel.responses import ConvertDocumentResponse
from docling_serve.datamodel.task import Task, TaskSource


class OrchestratorError(Exception):
    pass


class TaskNotFoundError(OrchestratorError):
    pass


class BaseOrchestrator(ABC):
    @abstractmethod
    async def enqueue(
        self, sources: list[TaskSource], options: ConvertDocumentsOptions
    ) -> Task:
        pass

    @abstractmethod
    async def queue_size(self) -> int:
        pass

    @abstractmethod
    async def get_queue_position(self, task_id: str) -> Optional[int]:
        pass

    @abstractmethod
    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
        pass

    @abstractmethod
    async def task_result(
        self, task_id: str, background_tasks: BackgroundTasks
    ) -> Union[ConvertDocumentResponse, FileResponse, None]:
        pass

    @abstractmethod
    async def clear_results(self, older_than: float = 0.0):
        pass

    @abstractmethod
    async def process_queue(self):
        pass

    @abstractmethod
    async def warm_up_caches(self):
        pass

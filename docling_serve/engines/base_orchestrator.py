from abc import ABC, abstractmethod
from typing import Optional

from docling_serve.datamodel.engines import Task
from docling_serve.datamodel.requests import ConvertDocumentsRequest


class OrchestratorError(Exception):
    pass


class TaskNotFoundError(OrchestratorError):
    pass


class BaseOrchestrator(ABC):
    @abstractmethod
    async def enqueue(self, request: ConvertDocumentsRequest) -> Task:
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
    async def task_result(self, task_id: str):
        pass

    @abstractmethod
    async def process_queue(self):
        pass


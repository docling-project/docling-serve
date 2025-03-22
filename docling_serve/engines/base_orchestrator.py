from abc import ABC, abstractmethod

from docling_serve.datamodel.task import Task


class BaseOrchestrator(ABC):
    @abstractmethod
    async def enqueue(self, task) -> Task:
        pass

    @abstractmethod
    async def queue_size(self) -> int:
        pass

    @abstractmethod
    async def task_status(self, task_id: str) -> Task:
        pass

    @abstractmethod
    async def task_result(self, task_id: str):
        pass

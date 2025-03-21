import logging
import uuid
from typing import Optional

from docling_serve.datamodel.engines import Task
from docling_serve.datamodel.requests import ConvertDocumentsRequest
from docling_serve.engines.async_orchestrator import BaseAsyncOrchestrator
from docling_serve.settings import docling_serve_settings

_log = logging.getLogger(__name__)


class AsyncKfpOrchestrator(BaseAsyncOrchestrator):
    def __init__(self):
        super().__init__()
        # TODO: add kfp client

    async def enqueue(self, request: ConvertDocumentsRequest) -> Task:
        task_id = str(uuid.uuid4())
        task = Task(task_id=task_id, request=request)
        await self.init_task_tracking(task)
        return task

    async def queue_size(self) -> int:
        return 1

    async def get_queue_position(self, task_id: str) -> Optional[int]:
        return None

    async def process_queue(self):
        return


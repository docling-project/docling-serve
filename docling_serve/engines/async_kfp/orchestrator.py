import logging
import uuid
from typing import Optional

from docling_serve.datamodel.callback import (
    ProgressCallbackRequest,
    ProgressSetNumDocs,
    ProgressUpdateProcessed,
)
from docling_serve.datamodel.engines import Task, TaskProcessingMeta
from docling_serve.datamodel.requests import ConvertDocumentsRequest
from docling_serve.engines.async_orchestrator import (
    BaseAsyncOrchestrator,
    ProgressInvalid,
)

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

    async def receive_task_progress(self, task_id: str, progress: ProgressCallbackRequest):
        task = await self.get_raw_task(task_id=task_id)

        if isinstance(progress, ProgressSetNumDocs):
            task.processing_meta = TaskProcessingMeta(num_docs=progress.num_docs)

        elif isinstance(progress, ProgressUpdateProcessed):
            if task.processing_meta is None:
                raise ProgressInvalid("UpdateProcessed was called before setting the expected number of documents.")
            task.processing_meta.num_processed += progress.num_processed
            task.processing_meta.num_success += progress.num_success
            task.processing_meta.num_failed += progress.num_failed

        # TODO: could be moved to BackgroundTask
        await self.notify_task_subscribers(task_id=task_id)

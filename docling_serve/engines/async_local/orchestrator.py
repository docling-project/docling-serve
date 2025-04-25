import asyncio
import logging
import uuid
from typing import Optional

from docling_serve.datamodel.convert import ConvertDocumentsOptions
from docling_serve.datamodel.task import Task, TaskSource
from docling_serve.docling_conversion import get_converter, get_pdf_pipeline_opts
from docling_serve.engines.async_local.worker import AsyncLocalWorker
from docling_serve.engines.async_orchestrator import BaseAsyncOrchestrator
from docling_serve.settings import docling_serve_settings

_log = logging.getLogger(__name__)


class AsyncLocalOrchestrator(BaseAsyncOrchestrator):
    def __init__(self):
        super().__init__()
        self.task_queue = asyncio.Queue()
        self.queue_list: list[str] = []

    async def enqueue(
        self, sources: list[TaskSource], options: ConvertDocumentsOptions
    ) -> Task:
        task_id = str(uuid.uuid4())
        task = Task(task_id=task_id, sources=sources, options=options)
        await self.init_task_tracking(task)

        self.queue_list.append(task_id)
        await self.task_queue.put(task_id)
        return task

    async def queue_size(self) -> int:
        return self.task_queue.qsize()

    async def get_queue_position(self, task_id: str) -> Optional[int]:
        return (
            self.queue_list.index(task_id) + 1 if task_id in self.queue_list else None
        )

    async def process_queue(self):
        # Create a pool of workers
        workers = []
        for i in range(docling_serve_settings.eng_loc_num_workers):
            _log.debug(f"Starting worker {i}")
            w = AsyncLocalWorker(i, self)
            worker_task = asyncio.create_task(w.loop())
            workers.append(worker_task)

        # Wait for all workers to complete (they won't, as they run indefinitely)
        await asyncio.gather(*workers)
        _log.debug("All workers completed.")

    async def warm_up_caches(self):
        # Converter with default options
        pdf_format_option = get_pdf_pipeline_opts(ConvertDocumentsOptions())
        get_converter(pdf_format_option)

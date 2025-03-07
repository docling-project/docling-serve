import asyncio
import logging
import uuid
from typing import Optional

from fastapi import WebSocket

from docling_serve.datamodel.engines import Task, TaskStatus
from docling_serve.datamodel.requests import ConvertDocumentsRequest
from docling_serve.datamodel.responses import (
    MessageKind,
    TaskStatusResponse,
    WebsocketMessage,
)
from docling_serve.engines.async_local.worker import AsyncLocalWorker
from docling_serve.engines.base_orchestrator import BaseOrchestrator
from docling_serve.settings import docling_serve_settings

_log = logging.getLogger(__name__)


class OrchestratorError(Exception):
    pass


class TaskNotFoundError(OrchestratorError):
    pass


class AsyncLocalOrchestrator(BaseOrchestrator):
    def __init__(self):
        self.task_queue = asyncio.Queue()
        self.tasks: dict[str, Task] = {}
        self.queue_list: list[str] = []
        self.task_subscribers: dict[str, set[WebSocket]] = {}

    async def enqueue(self, request: ConvertDocumentsRequest) -> Task:
        task_id = str(uuid.uuid4())
        task = Task(task_id=task_id, request=request)
        self.tasks[task_id] = task
        self.queue_list.append(task_id)
        self.task_subscribers[task_id] = set()
        await self.task_queue.put(task_id)
        return task

    async def queue_size(self) -> int:
        return self.task_queue.qsize()

    async def get_queue_position(self, task_id: str) -> Optional[int]:
        return (
            self.queue_list.index(task_id) + 1 if task_id in self.queue_list else None
        )

    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
        if task_id not in self.tasks:
            raise TaskNotFoundError()
        return self.tasks[task_id]

    async def task_result(self, task_id: str):
        if task_id not in self.tasks:
            raise TaskNotFoundError()
        return self.tasks[task_id].result

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

    async def notify_task_subscribers(self, task_id: str):
        if task_id not in self.task_subscribers:
            raise RuntimeError(f"Task {task_id} does not have a subscribers list.")

        task = self.tasks[task_id]
        task_queue_position = await self.get_queue_position(task_id)
        msg = TaskStatusResponse(
            task_id=task.task_id,
            task_status=task.task_status,
            task_position=task_queue_position,
        )
        for websocket in self.task_subscribers[task_id]:
            await websocket.send_text(
                WebsocketMessage(message=MessageKind.UPDATE, task=msg).model_dump_json()
            )
            if task.is_completed():
                await websocket.close()

    async def notify_queue_positions(self):
        for task_id in self.task_subscribers.keys():
            # notify only pending tasks
            if self.tasks[task_id].task_status != TaskStatus.PENDING:
                continue

            await self.notify_task_subscribers(task_id)

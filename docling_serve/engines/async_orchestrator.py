import asyncio
import datetime
import logging
import shutil
from typing import Union

from fastapi import BackgroundTasks, WebSocket
from fastapi.responses import FileResponse

from docling_serve.datamodel.callback import ProgressCallbackRequest
from docling_serve.datamodel.engines import TaskStatus
from docling_serve.datamodel.responses import (
    ConvertDocumentResponse,
    MessageKind,
    TaskStatusResponse,
    WebsocketMessage,
)
from docling_serve.datamodel.task import Task
from docling_serve.engines.base_orchestrator import (
    BaseOrchestrator,
    OrchestratorError,
    TaskNotFoundError,
)
from docling_serve.settings import docling_serve_settings

_log = logging.getLogger(__name__)


class ProgressInvalid(OrchestratorError):
    pass


class BaseAsyncOrchestrator(BaseOrchestrator):
    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.task_subscribers: dict[str, set[WebSocket]] = {}

    async def init_task_tracking(self, task: Task):
        task_id = task.task_id
        self.tasks[task.task_id] = task
        self.task_subscribers[task_id] = set()

    async def get_raw_task(self, task_id: str) -> Task:
        if task_id not in self.tasks:
            raise TaskNotFoundError()
        return self.tasks[task_id]

    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
        return await self.get_raw_task(task_id=task_id)

    async def task_result(
        self, task_id: str, background_tasks: BackgroundTasks
    ) -> Union[ConvertDocumentResponse, FileResponse, None]:
        try:
            task = await self.get_raw_task(task_id=task_id)
            if task.is_completed() and docling_serve_settings.single_use_results:
                if task.scratch_dir is not None:
                    background_tasks.add_task(
                        shutil.rmtree, task.scratch_dir, ignore_errors=True
                    )

                async def _remove_task_impl():
                    await asyncio.sleep(docling_serve_settings.result_removal_delay)
                    await self.delete_task(task_id=task.task_id)

                async def _remove_task():
                    asyncio.create_task(_remove_task_impl())  # noqa: RUF006

                background_tasks.add_task(_remove_task)

            return task.result
        except TaskNotFoundError:
            return None

    async def delete_task(self, task_id: str):
        _log.info(f"Deleting {task_id=}")
        if task_id in self.task_subscribers:
            for websocket in self.task_subscribers[task_id]:
                await websocket.close()

            del self.task_subscribers[task_id]

        if task_id in self.tasks:
            del self.tasks[task_id]

    async def clear_results(self, older_than: float = 0.0):
        cutoff_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            seconds=older_than
        )

        tasks_to_delete = [
            task_id
            for task_id, task in self.tasks.items()
            if task.finished_at is not None and task.finished_at < cutoff_time
        ]
        for task_id in tasks_to_delete:
            await self.delete_task(task_id=task_id)

    async def notify_task_subscribers(self, task_id: str):
        if task_id not in self.task_subscribers:
            raise RuntimeError(f"Task {task_id} does not have a subscribers list.")

        task = await self.get_raw_task(task_id=task_id)
        task_queue_position = await self.get_queue_position(task_id)
        msg = TaskStatusResponse(
            task_id=task.task_id,
            task_status=task.task_status,
            task_position=task_queue_position,
            task_meta=task.processing_meta,
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

    async def receive_task_progress(self, request: ProgressCallbackRequest):
        raise NotImplementedError()

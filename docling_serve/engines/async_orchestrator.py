from fastapi import WebSocket

from docling_serve.datamodel.callback import ProgressCallbackRequest
from docling_serve.datamodel.engines import TaskStatus
from docling_serve.datamodel.responses import (
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

    async def task_result(self, task_id: str):
        task = await self.get_raw_task(task_id=task_id)
        return task.result

    async def notify_task_subscribers(self, task_id: str):
        if task_id not in self.task_subscribers:
            raise RuntimeError(f"Task {task_id} does not have a subscribers list.")

        task = await self.get_raw_task(task_id=task_id)
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

    async def receive_task_progress(self, request: ProgressCallbackRequest):
        raise NotImplementedError()

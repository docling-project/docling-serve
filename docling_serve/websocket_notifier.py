from fastapi import WebSocket

from docling_jobkit.datamodel.task_meta import TaskStatus
from docling_jobkit.orchestrators.base_notifier import BaseNotifier
from docling_jobkit.orchestrators.base_orchestrator import BaseOrchestrator

from docling_serve.datamodel.responses import (
    MessageKind,
    TaskStatusResponse,
    WebsocketMessage,
)


class WebsocketNotifier(BaseNotifier):
    def __init__(self, orchestrator: BaseOrchestrator):
        super().__init__(orchestrator)
        self.task_subscribers: dict[str, set[WebSocket]] = {}

    async def add_task(self, task_id: str):
        self.task_subscribers[task_id] = set()

    async def remove_task(self, task_id: str):
        if task_id in self.task_subscribers:
            for websocket in self.task_subscribers[task_id]:
                await websocket.close()

            del self.task_subscribers[task_id]

    async def notify_task_subscribers(self, task_id: str):
        if task_id not in self.task_subscribers:
            raise RuntimeError(f"Task {task_id} does not have a subscribers list.")

        try:
            # Get task status from Redis or RQ directly instead of in-memory registry
            task = await self.orchestrator.task_status(task_id=task_id)
            task_queue_position = await self.orchestrator.get_queue_position(task_id)
            msg = TaskStatusResponse(
                task_id=task.task_id,
                task_type=task.task_type,
                task_status=task.task_status,
                task_position=task_queue_position,
                task_meta=task.processing_meta,
            )
            for websocket in self.task_subscribers[task_id]:
                await websocket.send_text(
                    WebsocketMessage(
                        message=MessageKind.UPDATE, task=msg
                    ).model_dump_json()
                )
                if task.is_completed():
                    await websocket.close()
        except Exception as e:
            # Log the error but don't crash the notifier
            import logging

            _log = logging.getLogger(__name__)
            _log.error(f"Error notifying subscribers for task {task_id}: {e}")

    async def notify_queue_positions(self):
        """Notify all subscribers of pending tasks about queue position updates."""
        for task_id in self.task_subscribers.keys():
            try:
                # Check task status directly from Redis or RQ
                task = await self.orchestrator.task_status(task_id)

                # Notify only pending tasks
                if task.task_status == TaskStatus.PENDING:
                    await self.notify_task_subscribers(task_id)
            except Exception as e:
                # Log the error but don't crash the notifier
                import logging

                _log = logging.getLogger(__name__)
                _log.error(
                    f"Error checking task {task_id} status for queue position notification: {e}"
                )

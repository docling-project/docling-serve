import logging

from fastapi import WebSocket

from docling.datamodel.service.responses import (
    MessageKind,
    TaskStatusResponse,
    WebsocketMessage,
)
from docling_jobkit.datamodel.task_meta import TaskStatus
from docling_jobkit.orchestrators.base_notifier import BaseNotifier
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
    TaskNotFoundError,
)

_log = logging.getLogger(__name__)


class WebsocketNotifier(BaseNotifier):
    def __init__(self, orchestrator: BaseOrchestrator):
        super().__init__(orchestrator)
        self.task_subscribers: dict[str, set[WebSocket]] = {}

    async def add_task(self, task_id: str):
        self.task_subscribers[task_id] = set()

    async def remove_task(self, task_id: str):
        subscribers = self.task_subscribers.pop(task_id, None)
        if subscribers:
            for websocket in list(subscribers):
                await websocket.close()

    async def _drop_untracked_task(self, task_id: str):
        """Forget a task the orchestrator no longer knows about.

        The orchestrator only calls ``remove_task`` from ``delete_task``. A task
        can vanish without that call: its RQ job and metadata expire before the
        result is fetched, the zombie reaper drops it from tracking, or the
        result is fetched through another API replica. Keeping the key would
        make every later ``notify_queue_positions`` round query and log an
        error for it until the process restarts.
        """
        _log.debug(f"Task {task_id} is no longer tracked, dropping its subscribers.")
        await self.remove_task(task_id)

    async def notify_task_subscribers(self, task_id: str):
        if task_id not in self.task_subscribers:
            _log.debug(
                f"Task {task_id} has no websocket subscribers, skipping notification."
            )
            return

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
                error_message=task.error_message,
                failure=task.failure,
            )
        except TaskNotFoundError:
            await self._drop_untracked_task(task_id)
            return
        except Exception as e:
            _log.error(f"Error fetching status for task {task_id}: {e}")
            return

        payload = WebsocketMessage(
            message=MessageKind.UPDATE, task=msg
        ).model_dump_json()
        for websocket in list(self.task_subscribers.get(task_id, set())):
            try:
                await websocket.send_text(payload)
                if task.is_completed():
                    await websocket.close()
            except Exception as e:
                _log.warning(
                    f"Failed to notify subscriber for task {task_id}, discarding: {e}"
                )
                subs = self.task_subscribers.get(task_id)
                if subs:
                    subs.discard(websocket)

    async def notify_queue_positions(self):
        """Notify all subscribers of pending tasks about queue position updates."""
        for task_id in list(self.task_subscribers.keys()):
            try:
                # Check task status directly from Redis or RQ
                task = await self.orchestrator.task_status(task_id)

                # Notify only pending tasks
                if task.task_status == TaskStatus.PENDING:
                    await self.notify_task_subscribers(task_id)
            except TaskNotFoundError:
                await self._drop_untracked_task(task_id)
            except Exception as e:
                _log.error(
                    f"Error checking task {task_id} status for queue position notification: {e}"
                )

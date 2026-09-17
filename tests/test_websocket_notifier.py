"""Unit tests for WebsocketNotifier.

The notifier tracks every enqueued task. When the orchestrator no longer knows a
task (result expired unfetched, reaped, or deleted through another replica), the
notifier must drop it instead of logging an error on every later round.
"""

import logging

import pytest

from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus
from docling_jobkit.orchestrators.base_orchestrator import TaskNotFoundError

from docling_serve.websocket_notifier import WebsocketNotifier

_LOGGER = "docling_serve.websocket_notifier"


class _FakeOrchestrator:
    """Stands in for BaseOrchestrator with the two calls the notifier makes."""

    def __init__(self):
        self.tasks: dict[str, Task] = {}
        self.status_calls: list[str] = []
        self.error: Exception | None = None

    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
        self.status_calls.append(task_id)
        if self.error is not None:
            raise self.error
        if task_id not in self.tasks:
            raise TaskNotFoundError(task_id)
        return self.tasks[task_id]

    async def get_queue_position(self, task_id: str):
        return 0


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[str] = []
        self.closed = False

    async def send_text(self, payload: str):
        self.sent.append(payload)

    async def close(self):
        self.closed = True


@pytest.fixture
def orchestrator():
    return _FakeOrchestrator()


@pytest.fixture
def notifier(orchestrator):
    return WebsocketNotifier(orchestrator)  # type: ignore[arg-type]


async def test_queue_positions_drop_task_unknown_to_orchestrator(
    notifier, orchestrator, caplog
):
    await notifier.add_task("gone")

    with caplog.at_level(logging.DEBUG, logger=_LOGGER):
        await notifier.notify_queue_positions()

    assert "gone" not in notifier.task_subscribers
    assert orchestrator.status_calls == ["gone"]
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]

    # The next round must not query the orchestrator for it again.
    await notifier.notify_queue_positions()
    assert orchestrator.status_calls == ["gone"]


async def test_queue_positions_keep_tasks_known_to_orchestrator(notifier, orchestrator):
    orchestrator.tasks["pending"] = Task(task_id="pending")
    orchestrator.tasks["done"] = Task(task_id="done", task_status=TaskStatus.SUCCESS)
    for task_id in ("pending", "done", "gone"):
        await notifier.add_task(task_id)

    await notifier.notify_queue_positions()

    assert set(notifier.task_subscribers) == {"pending", "done"}


async def test_queue_positions_keep_task_on_other_errors(
    notifier, orchestrator, caplog
):
    await notifier.add_task("flaky")
    orchestrator.error = ConnectionError("redis down")

    with caplog.at_level(logging.ERROR, logger=_LOGGER):
        await notifier.notify_queue_positions()

    assert "flaky" in notifier.task_subscribers
    assert any(
        "flaky" in r.getMessage() for r in caplog.records if r.levelno == logging.ERROR
    )


async def test_subscribers_of_vanished_task_are_closed(notifier, orchestrator):
    await notifier.add_task("gone")
    websocket = _FakeWebSocket()
    notifier.task_subscribers["gone"].add(websocket)  # type: ignore[arg-type]

    await notifier.notify_task_subscribers("gone")

    assert websocket.closed
    assert "gone" not in notifier.task_subscribers


async def test_pending_task_subscribers_still_get_updates(notifier, orchestrator):
    orchestrator.tasks["pending"] = Task(task_id="pending")
    await notifier.add_task("pending")
    websocket = _FakeWebSocket()
    notifier.task_subscribers["pending"].add(websocket)  # type: ignore[arg-type]

    await notifier.notify_queue_positions()

    assert len(websocket.sent) == 1
    assert not websocket.closed
    assert "pending" in notifier.task_subscribers

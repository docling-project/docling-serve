# SPDX-License-Identifier: MIT

"""Queued-cancellation HTTP and WebSocket contracts.

Use a fake orchestrator without models, Redis or workers. Backend start/cancel
arbitration is covered by Jobkit.
"""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus
from docling_jobkit.orchestrators.base_orchestrator import (
    CancellationConflictReason,
    TaskCancellationConflictError,
    TaskNotFoundError,
)

from docling_serve.websocket_notifier import WebsocketNotifier


def _task(
    task_id: str,
    status: TaskStatus = TaskStatus.PENDING,
    tenant: str = "default",
) -> Task:
    return Task(task_id=task_id, task_status=status, metadata={"tenant_id": tenant})


class _FakeOrchestrator:
    """Cancellation test double."""

    cancel_on_enqueue = False

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.notifier = WebsocketNotifier(self)  # type: ignore[arg-type]

    async def enqueue(self, **kwargs) -> Task:  # type: ignore[no-untyped-def]
        metadata = kwargs.get("metadata") or {}
        task = _task(
            str(uuid.uuid4()), TaskStatus.PENDING, metadata.get("tenant_id", "default")
        )
        if self.cancel_on_enqueue:
            task.set_status(TaskStatus.CANCELLED)
        self.tasks[task.task_id] = task
        return task

    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
        del wait
        if task_id not in self.tasks:
            raise TaskNotFoundError(task_id)
        return self.tasks[task_id]

    async def task_outcome(self, task_id: str):  # type: ignore[no-untyped-def]
        return await self.task_result(task_id)

    async def task_result(self, task_id: str):  # type: ignore[no-untyped-def]
        # Cancelled work never writes a result; success paths are covered by
        # the existing endpoint suite, so this double stays result-free.
        del task_id
        return None

    async def get_queue_position(self, task_id: str):  # type: ignore[no-untyped-def]
        task = self.tasks.get(task_id)
        if task is None or task.task_status == TaskStatus.CANCELLED:
            return None
        return 1

    async def cancel_queued_task(self, task_id: str) -> Task:
        if task_id not in self.tasks:
            raise TaskNotFoundError(task_id)
        task = self.tasks[task_id]
        if task.task_status == TaskStatus.CANCELLED:
            return task
        if task.task_status == TaskStatus.STARTED:
            raise TaskCancellationConflictError(
                CancellationConflictReason.ALREADY_STARTED, task.task_status
            )
        if task.task_status in (TaskStatus.SUCCESS, TaskStatus.FAILURE):
            raise TaskCancellationConflictError(
                CancellationConflictReason.ALREADY_FINISHED, task.task_status
            )
        task.set_status(TaskStatus.CANCELLED)
        return task


@pytest.fixture
def orchestrator() -> _FakeOrchestrator:
    fake = _FakeOrchestrator()
    fake.tasks["pending"] = _task("pending", TaskStatus.PENDING)
    fake.tasks["started"] = _task("started", TaskStatus.STARTED)
    fake.tasks["success"] = _task("success", TaskStatus.SUCCESS)
    fake.tasks["failure"] = _task("failure", TaskStatus.FAILURE)
    fake.tasks["cancelled"] = _task("cancelled", TaskStatus.CANCELLED)
    fake.tasks["other"] = _task("other", TaskStatus.PENDING, tenant="other")
    return fake


@pytest.fixture
def client(orchestrator, monkeypatch) -> TestClient:
    from docling_serve import app as app_module

    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: orchestrator)
    with patch.object(app_module, "setup_otel_instrumentation"):
        return TestClient(app_module.create_app())


def _sync_payload() -> dict:
    return {
        "sources": [{"kind": "http", "url": "https://example.com/a.pdf"}],
        "target": {"kind": "inbody"},
    }


def test_cancel_pending_returns_200_cancelled(client: TestClient):
    response = client.post("/v1/tasks/pending/cancel")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["task_id"] == "pending"
    assert body["task_status"] == "cancelled"


def test_cancel_repeated_is_idempotent_200(client: TestClient):
    first = client.post("/v1/tasks/pending/cancel")
    second = client.post("/v1/tasks/pending/cancel")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["task_status"] == "cancelled"


def test_cancel_started_conflicts_409_started(client: TestClient):
    response = client.post("/v1/tasks/started/cancel")

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "TASK_ALREADY_STARTED"


@pytest.mark.parametrize("task_id", ["success", "failure"])
def test_cancel_finished_conflicts_409_finished(client: TestClient, task_id: str):
    response = client.post(f"/v1/tasks/{task_id}/cancel")

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "TASK_ALREADY_FINISHED"


def test_cancel_unknown_returns_404(client: TestClient):
    response = client.post("/v1/tasks/does-not-exist/cancel")

    assert response.status_code == 404, response.text


def test_cancel_tenant_mismatch_returns_404_without_leakage(client: TestClient):
    mismatch = client.post("/v1/tasks/other/cancel")
    unknown = client.post("/v1/tasks/does-not-exist/cancel")

    assert mismatch.status_code == 404, mismatch.text
    assert mismatch.json() == unknown.json()

    owned = client.post("/v1/tasks/other/cancel", headers={"X-Tenant-Id": "other"})
    assert owned.status_code == 200, owned.text
    assert owned.json()["task_status"] == "cancelled"


def test_cancel_requires_auth(orchestrator, monkeypatch):
    from docling_serve import app as app_module

    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: orchestrator)
    monkeypatch.setattr(app_module.docling_serve_settings, "api_key", "secret")
    with patch.object(app_module, "setup_otel_instrumentation"):
        authed = TestClient(app_module.create_app())

    assert authed.post("/v1/tasks/pending/cancel").status_code == 401
    ok = authed.post("/v1/tasks/pending/cancel", headers={"X-Api-Key": "secret"})
    assert ok.status_code == 200, ok.text


def test_openapi_exposes_cancelled_status(client: TestClient):
    schema = client.get("/openapi.json")

    assert schema.status_code == 200, schema.text
    doc = schema.json()
    for route in ("/v1/tasks/{task_id}/cancel", "/v1/status/poll/{task_id}"):
        ref = doc["paths"][route]["post" if "cancel" in route else "get"]["responses"][
            "200"
        ]["content"]["application/json"]["schema"]["$ref"]
        assert ref == "#/components/schemas/TaskStatusResponse", ref
    status_schema = doc["components"]["schemas"]["TaskStatusResponse"]["properties"][
        "task_status"
    ]
    assert status_schema == {"$ref": "#/components/schemas/TaskStatus"}
    assert set(doc["components"]["schemas"]["TaskStatus"]["enum"]) == {
        "pending",
        "started",
        "success",
        "failure",
        "cancelled",
    }


def test_cancel_unsupported_engine_returns_501(
    client: TestClient, orchestrator, monkeypatch
):
    async def _unsupported(task_id: str) -> Task:
        raise NotImplementedError(f"no queued cancellation for {task_id}")

    monkeypatch.setattr(orchestrator, "cancel_queued_task", _unsupported)

    response = client.post("/v1/tasks/pending/cancel")

    assert response.status_code == 501, response.text
    assert response.json()["detail"] == (
        "Queued task cancellation is not supported by this orchestrator."
    )


def test_poll_recognizes_terminal_cancelled(client: TestClient):
    response = client.get("/v1/status/poll/cancelled")

    assert response.status_code == 200, response.text
    assert response.json()["task_status"] == "cancelled"


def test_result_returns_409_cancelled_not_404(client: TestClient):
    response = client.get("/v1/result/cancelled")

    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "code": "TASK_CANCELLED",
        "message": "Task was cancelled while queued.",
    }


def test_sync_externally_cancelled_terminates_409(monkeypatch):
    from docling_serve import app as app_module

    fake = _FakeOrchestrator()
    fake.cancel_on_enqueue = True
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: fake)
    with patch.object(app_module, "setup_otel_instrumentation"):
        sync_client = TestClient(app_module.create_app())

    response = sync_client.post("/v1/convert/source", json=_sync_payload())

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "TASK_CANCELLED"


def test_websocket_cancelled_is_terminal_and_closes(client: TestClient):
    import json
    import threading

    from fastapi import WebSocketDisconnect

    with client.websocket_connect("/v1/status/ws/cancelled") as websocket:
        first = json.loads(websocket.receive_text())
        second = json.loads(websocket.receive_text())
        assert second["task"]["task_status"] == "cancelled"
        assert first["task"]["task_id"] == "cancelled"
        # The socket must be closed after the terminal update: an adversary
        # that stays open must fail within the bound, not hang the suite.
        # The third receive runs on an owned daemon worker; the main thread
        # interrupts/closes before joining it, so a permanently blocked
        # receive cannot stall executor teardown and no non-daemon thread
        # lingers.
        outcome: dict[str, object] = {}

        def _blocked_receive() -> None:
            try:
                outcome["value"] = websocket.receive_text()
            except Exception as exc:
                outcome["error"] = exc

        worker = threading.Thread(target=_blocked_receive, daemon=True)
        worker.start()
        worker.join(timeout=5)
        if worker.is_alive():
            try:
                websocket.close()
            except Exception:
                pass
            worker.join(timeout=5)
            if worker.is_alive():
                pytest.fail(
                    "websocket third receive did not terminate after close; "
                    "bound exceeded"
                )
            pytest.fail(
                "websocket stayed open after terminal cancelled "
                "(third receive blocked past 5s bound)"
            )
        if "error" in outcome:
            exc = outcome["error"]
            assert isinstance(exc, WebSocketDisconnect | RuntimeError), (
                f"terminal socket raised unexpected {exc!r}"
            )
            return
        pytest.fail("websocket stayed open after terminal cancelled")


def test_cancel_error_mapping_is_exact_and_guarded_calls_never_delegate(
    client: TestClient, orchestrator: _FakeOrchestrator, monkeypatch
) -> None:
    from unittest.mock import AsyncMock

    started = client.post("/v1/tasks/started/cancel")
    assert started.status_code == 409, started.text
    assert started.json()["detail"] == {
        "code": "TASK_ALREADY_STARTED",
        "message": "Task already started and can no longer be cancelled.",
    }
    finished = client.post("/v1/tasks/success/cancel")
    assert finished.status_code == 409, finished.text
    assert finished.json()["detail"] == {
        "code": "TASK_ALREADY_FINISHED",
        "message": "Task already reached a terminal outcome.",
    }
    unknown = client.post("/v1/tasks/does-not-exist/cancel")
    assert unknown.status_code == 404, unknown.text

    spy = AsyncMock(wraps=orchestrator.cancel_queued_task)
    monkeypatch.setattr(orchestrator, "cancel_queued_task", spy)
    mismatch = client.post("/v1/tasks/other/cancel")
    assert mismatch.status_code == 404, mismatch.text
    assert spy.await_count == 0

    from docling_serve import app as app_module

    monkeypatch.setattr(app_module.docling_serve_settings, "api_key", "secret")
    with patch.object(app_module, "setup_otel_instrumentation"):
        guarded = TestClient(app_module.create_app())
    denied = guarded.post("/v1/tasks/pending/cancel")
    assert denied.status_code == 401, denied.text
    assert spy.await_count == 0


def test_deferred_external_cancel_during_sync_wait_returns_409(
    monkeypatch,
) -> None:
    from docling_serve import app as app_module

    class _DeferredCancelOrchestrator(_FakeOrchestrator):
        def __init__(self) -> None:
            super().__init__()
            self.polls = 0

        async def enqueue(self, **kwargs):  # type: ignore[no-untyped-def]
            task = await super().enqueue(**kwargs)
            self.polls = 0
            return task

        async def task_status(self, task_id: str, wait: float = 0.0):  # type: ignore[no-untyped-def]
            del wait
            task = self.tasks[task_id]
            self.polls += 1
            if self.polls >= 2 and task.task_status == TaskStatus.PENDING:
                task.set_status(TaskStatus.CANCELLED)
            return task

    fake = _DeferredCancelOrchestrator()
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: fake)
    with patch.object(app_module, "setup_otel_instrumentation"):
        sync_client = TestClient(app_module.create_app())

    response = sync_client.post("/v1/convert/source", json=_sync_payload())

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "TASK_CANCELLED"

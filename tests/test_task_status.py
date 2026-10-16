# SPDX-License-Identifier: MIT

"""P2a shared wire schema: cancelled-capable response and WS envelope."""

import json

from docling.datamodel.base_models import ConversionStatus
from docling.datamodel.service.responses import MessageKind
from docling.datamodel.service.tasks import TaskType
from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus as JobkitStatus
from docling_jobkit.orchestrators.base_orchestrator import TaskNotFoundError

from docling_serve.datamodel.task_status import (
    ServeTaskStatusResponse,
    ServeWebsocketMessage,
    to_serve_task_status,
)
from docling_serve.websocket_notifier import WebsocketNotifier


class _FakeOrchestrator:
    def __init__(self):
        self.tasks: dict[str, Task] = {}

    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
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


def test_all_prior_sdk_statuses_still_accepted():
    for status in list(ConversionStatus):
        response = ServeTaskStatusResponse(
            task_id="t", task_type=TaskType.CONVERT, task_status=status
        )
        assert response.task_status == status
        assert f'"{status.value}"' in response.model_dump_json()


def test_cancelled_string_and_jobkit_enum_accepted():
    from_string = ServeTaskStatusResponse(
        task_id="t", task_type=TaskType.CONVERT, task_status="cancelled"
    )
    assert from_string.model_dump()["task_status"] == "cancelled"

    from_jobkit = ServeTaskStatusResponse(
        task_id="t",
        task_type=TaskType.CONVERT,
        task_status=JobkitStatus.CANCELLED,  # type: ignore[arg-type]
    )
    assert from_jobkit.model_dump()["task_status"] == "cancelled"


def test_jobkit_prior_statuses_coerce_to_sdk_enum():
    for jobkit_status, sdk_status in (
        (JobkitStatus.PENDING, ConversionStatus.PENDING),
        (JobkitStatus.STARTED, ConversionStatus.STARTED),
        (JobkitStatus.SUCCESS, ConversionStatus.SUCCESS),
        (JobkitStatus.FAILURE, ConversionStatus.FAILURE),
    ):
        response = ServeTaskStatusResponse(
            task_id="t",
            task_type=TaskType.CONVERT,
            task_status=jobkit_status,  # type: ignore[arg-type]
        )
        assert response.task_status == sdk_status


def test_sdk_fields_and_defaults_preserved():
    response = ServeTaskStatusResponse(
        task_id="t", task_type=TaskType.CONVERT, task_status="cancelled"
    )
    assert response.task_id == "t"
    assert response.task_position is None
    assert response.task_meta is None
    assert response.error_message is None
    assert response.failure is None

    full = ServeTaskStatusResponse(
        task_id="t",
        task_type=TaskType.CONVERT,
        task_status=ConversionStatus.STARTED,
        task_position=3,
        error_message="boom",
    )
    assert full.task_position == 3
    assert full.error_message == "boom"


def test_openapi_schema_is_compatible_and_includes_cancelled():
    schema = ServeTaskStatusResponse.model_json_schema()
    status_schema = schema["properties"]["task_status"]
    assert status_schema == {
        "anyOf": [
            {"$ref": "#/$defs/ConversionStatus"},
            {"const": "cancelled", "type": "string"},
        ],
        "title": "Task Status",
    }
    assert schema["$defs"]["ConversionStatus"]["enum"] == [
        "pending",
        "started",
        "failure",
        "success",
        "partial_success",
        "skipped",
    ]

    payload = json.loads(
        ServeTaskStatusResponse(
            task_id="t", task_type=TaskType.CONVERT, task_status="cancelled"
        ).model_dump_json()
    )
    assert payload["task_status"] == "cancelled"


def test_websocket_envelope_nests_cancelled():
    inner = ServeTaskStatusResponse(
        task_id="t", task_type=TaskType.CONVERT, task_status="cancelled"
    )
    envelope = ServeWebsocketMessage(message=MessageKind.UPDATE, task=inner)
    assert envelope.task is not None
    assert envelope.task.task_status == "cancelled"
    assert envelope.message == MessageKind.UPDATE
    assert envelope.error is None

    payload = json.loads(envelope.model_dump_json())
    assert payload["message"] == "update"
    assert payload["task"]["task_status"] == "cancelled"

    default_envelope = ServeWebsocketMessage(message=MessageKind.ERROR, error="nope")
    assert default_envelope.task is None


def test_helper_maps_cancelled_and_passes_through():
    assert to_serve_task_status(JobkitStatus.CANCELLED) == "cancelled"
    assert to_serve_task_status("cancelled") == "cancelled"
    assert to_serve_task_status(ConversionStatus.PENDING) == ConversionStatus.PENDING


async def test_notifier_sends_cancelled_terminal_and_closes():
    orchestrator = _FakeOrchestrator()
    orchestrator.tasks["cancelled"] = Task(
        task_id="cancelled", task_status=JobkitStatus.CANCELLED
    )
    notifier = WebsocketNotifier(orchestrator)  # type: ignore[arg-type]
    await notifier.add_task("cancelled")
    websocket = _FakeWebSocket()
    notifier.task_subscribers["cancelled"].add(websocket)  # type: ignore[arg-type]

    await notifier.notify_task_subscribers("cancelled")

    assert len(websocket.sent) == 1
    payload = json.loads(websocket.sent[0])
    assert payload["task"]["task_status"] == "cancelled"
    assert websocket.closed


async def test_notifier_still_sends_prior_status_without_closing_pending():
    orchestrator = _FakeOrchestrator()
    orchestrator.tasks["pending"] = Task(task_id="pending")
    notifier = WebsocketNotifier(orchestrator)  # type: ignore[arg-type]
    await notifier.add_task("pending")
    websocket = _FakeWebSocket()
    notifier.task_subscribers["pending"].add(websocket)  # type: ignore[arg-type]

    await notifier.notify_task_subscribers("pending")

    assert len(websocket.sent) == 1
    assert json.loads(websocket.sent[0])["task"]["task_status"] == "pending"
    assert not websocket.closed

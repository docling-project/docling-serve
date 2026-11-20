"""A failed task must be reported as a failure on the synchronous endpoints.

``Task.is_completed()`` is true for FAILURE as well as SUCCESS, so the sync
handlers used to ask for a result that a failed task never has, and answered
404 "Task result not found" for a task that had in fact failed.
"""

from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from docling.datamodel.service.responses import (
    FailureCategory,
    FailurePhase,
    PublicFailureInfo,
)
from docling.datamodel.service.tasks import TaskType
from docling_jobkit.datamodel.stored_outcome import (
    StoredFailureOutcome,
    StoredSuccessOutcome,
)
from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus

FAILURE = PublicFailureInfo(
    category=FailureCategory.INTERNAL,
    message="The worker died while converting the document.",
    retryable=False,
    phase=FailurePhase.EXECUTION,
)

SYNC_ENDPOINTS = ["/v1/convert/source", "/v1/chunk/hybrid/source"]


class _FakeOrchestrator:
    """Stands in for an orchestrator whose only task reached ``status``."""

    def __init__(self, status, outcome=None, failure=None) -> None:
        self.status = status
        self.outcome = outcome
        self.failure = failure

    async def enqueue(self, **kwargs):
        return Task.model_construct(
            task_id="task-1",
            task_type=kwargs["task_type"],
            sources=kwargs["sources"],
        )

    async def get_queue_position(self, task_id: str):
        del task_id
        return 0

    async def task_status(self, task_id: str):
        del task_id
        return Task(
            task_id="task-1",
            task_type=TaskType.CONVERT,
            task_status=self.status,
            sources=[],
            metadata={"tenant_id": "default"},
            failure=self.failure,
        )

    async def task_outcome(self, task_id: str):
        del task_id
        return self.outcome

    async def task_result(self, task_id: str):
        """Mirrors the Ray orchestrator: a stored failure has no result."""
        del task_id
        if isinstance(self.outcome, StoredSuccessOutcome):
            return self.outcome.result
        if isinstance(self.outcome, StoredFailureOutcome):
            return None
        return self.outcome

    async def on_result_fetched(self, task_id: str):
        del task_id


@pytest.fixture
def make_client(monkeypatch):
    from docling_serve import app as app_module

    def _make(orchestrator):
        monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: orchestrator)
        with patch.object(app_module, "setup_otel_instrumentation"):
            app = app_module.create_app()
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://app.io")

    return _make


def _payload(endpoint: str) -> dict:
    payload: dict = {"sources": [{"kind": "http", "url": "https://example.com/a.pdf"}]}
    if "chunk" in endpoint:
        payload["chunking_options"] = {}
    return payload


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", SYNC_ENDPOINTS)
async def test_failed_task_without_stored_outcome_reports_the_failure(
    make_client, endpoint
):
    """An orchestrator that keeps no outcome leaves the failure on the task."""
    client = make_client(_FakeOrchestrator(TaskStatus.FAILURE, failure=FAILURE))

    async with client:
        response = await client.post(endpoint, json=_payload(endpoint))

    assert response.status_code == 500
    assert response.json()["detail"] == FAILURE.message


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", SYNC_ENDPOINTS)
async def test_failed_task_with_stored_outcome_reports_the_failure(
    make_client, endpoint
):
    """An orchestrator that stores outcomes answers with a StoredFailureOutcome."""
    client = make_client(
        _FakeOrchestrator(
            TaskStatus.FAILURE, outcome=StoredFailureOutcome(failure=FAILURE)
        )
    )

    async with client:
        response = await client.post(endpoint, json=_payload(endpoint))

    assert response.status_code == 500
    assert response.json()["detail"] == FAILURE.message


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", SYNC_ENDPOINTS)
async def test_failed_task_with_no_recorded_detail_still_reports_a_failure(
    make_client, endpoint
):
    client = make_client(_FakeOrchestrator(TaskStatus.FAILURE))

    async with client:
        response = await client.post(endpoint, json=_payload(endpoint))

    assert response.status_code == 500
    assert response.json()["detail"] == "The conversion task failed."


@pytest.mark.asyncio
@pytest.mark.parametrize("endpoint", SYNC_ENDPOINTS)
async def test_succeeded_task_with_no_result_is_still_a_404(make_client, endpoint):
    """A result that was cleared or expired is genuinely missing, so 404 stays."""
    client = make_client(_FakeOrchestrator(TaskStatus.SUCCESS))

    async with client:
        response = await client.post(endpoint, json=_payload(endpoint))

    assert response.status_code == 404
    assert "Task result not found" in response.json()["detail"]

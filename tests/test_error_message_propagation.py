"""Tests for error_message propagation through the docling-serve API layer."""

import json

from docling_serve.datamodel.responses import (
    FailureCategory,
    FailurePhase,
    PublicFailureInfo,
    TaskStatusResponse,
)


class TestTaskStatusResponseErrorMessage:
    def test_error_message_field_exists(self):
        resp = TaskStatusResponse(
            task_id="t1",
            task_type="convert",
            task_status="failure",
            error_message="conversion failed",
        )
        assert resp.error_message == "conversion failed"

    def test_error_message_defaults_to_none(self):
        resp = TaskStatusResponse(
            task_id="t1",
            task_type="convert",
            task_status="success",
        )
        assert resp.error_message is None

    def test_error_message_in_json_output(self):
        resp = TaskStatusResponse(
            task_id="t1",
            task_type="convert",
            task_status="failure",
            error_message="OOM killed",
        )
        data = json.loads(resp.model_dump_json())
        assert data["error_message"] == "OOM killed"

    def test_error_message_none_in_json_output(self):
        resp = TaskStatusResponse(
            task_id="t1",
            task_type="convert",
            task_status="success",
        )
        data = json.loads(resp.model_dump_json())
        assert data["error_message"] is None

    def test_backward_compatible_deserialization(self):
        old_json = '{"task_id": "t1", "task_type": "convert", "task_status": "failure"}'
        resp = TaskStatusResponse.model_validate_json(old_json)
        assert resp.error_message is None

    def test_failure_field_in_json_output(self):
        resp = TaskStatusResponse(
            task_id="t1",
            task_type="convert",
            task_status="failure",
            failure=PublicFailureInfo(
                code="internal_error",
                category=FailureCategory.INTERNAL,
                message="Internal processing error.",
                retryable=False,
                phase=FailurePhase.ORCHESTRATION,
                correlation_id="t1",
            ),
        )
        data = json.loads(resp.model_dump_json())
        assert data["failure"]["code"] == "internal_error"

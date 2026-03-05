"""Tests for error_message propagation through the docling-serve API layer."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus
from docling_jobkit.datamodel.task_targets import InBodyTarget

from docling_serve.datamodel.responses import TaskStatusResponse


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


class TestRedisErrorMessageStorage:
    @pytest.mark.asyncio
    async def test_store_and_retrieve_error_message(self):
        from docling_serve.orchestrator_factory import RedisTaskStatusMixin

        storage: dict[str, str] = {}

        async def mock_set(key: str, value: str, ex: int = 0) -> None:
            storage[key] = value

        async def mock_get(key: str) -> bytes | None:
            val = storage.get(key)
            return val.encode() if val else None

        mock_redis = AsyncMock()
        mock_redis.set = mock_set
        mock_redis.get = mock_get
        mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.__aexit__ = AsyncMock(return_value=False)

        class FakeMixin(RedisTaskStatusMixin):
            def __init__(self):
                self.redis_prefix = "docling:tasks:"
                self._redis_pool = MagicMock()
                self.tasks: dict[str, Task] = {}
                self._task_result_keys: dict[str, str] = {}
                self.config = MagicMock()
                self.config.redis_url = "redis://localhost:6379/"

        mixin = FakeMixin()

        task = Task(
            task_id="fail-task-1",
            sources=[],
            target=InBodyTarget(),
            task_status=TaskStatus.FAILURE,
            error_message="corrupt PDF: invalid xref table",
        )

        with patch(
            "docling_serve.orchestrator_factory.redis.Redis", return_value=mock_redis
        ):
            await mixin._store_task_in_redis(task)

        raw = storage.get("docling:tasks:fail-task-1:metadata")
        assert raw is not None
        data = json.loads(raw)
        assert data["error_message"] == "corrupt PDF: invalid xref table"

        with patch(
            "docling_serve.orchestrator_factory.redis.Redis", return_value=mock_redis
        ):
            restored = await mixin._get_task_from_redis("fail-task-1")

        assert restored is not None
        assert restored.error_message == "corrupt PDF: invalid xref table"
        assert restored.task_status == TaskStatus.FAILURE

    @pytest.mark.asyncio
    async def test_retrieve_without_error_message_backward_compat(self):
        from docling_serve.orchestrator_factory import RedisTaskStatusMixin

        old_data = json.dumps(
            {
                "task_id": "old-task-1",
                "task_type": "convert",
                "task_status": "success",
                "processing_meta": {
                    "num_docs": 1,
                    "num_processed": 1,
                    "num_succeeded": 1,
                    "num_failed": 0,
                },
            }
        )

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=old_data.encode())
        mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.__aexit__ = AsyncMock(return_value=False)

        class FakeMixin(RedisTaskStatusMixin):
            def __init__(self):
                self.redis_prefix = "docling:tasks:"
                self._redis_pool = MagicMock()
                self.tasks: dict[str, Task] = {}
                self._task_result_keys: dict[str, str] = {}
                self.config = MagicMock()
                self.config.redis_url = "redis://localhost:6379/"

        mixin = FakeMixin()

        with patch(
            "docling_serve.orchestrator_factory.redis.Redis", return_value=mock_redis
        ):
            restored = await mixin._get_task_from_redis("old-task-1")

        assert restored is not None
        assert restored.error_message is None
        assert restored.task_status == TaskStatus.SUCCESS

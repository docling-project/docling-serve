"""Tests for zombie task cleanup in RedisTaskStatusMixin.

Tests cover:
- Layer A: _RQJobGone sentinel from _get_task_from_rq_direct when NoSuchJobError
- Layer B: task_status() reconciliation for zombie scenarios
- Layer C: Background zombie reaper
- Layer E: TTL alignment (metadata TTL uses results_ttl)
"""

import asyncio
import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rq.exceptions import NoSuchJobError

from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus
from docling_jobkit.orchestrators.base_orchestrator import TaskNotFoundError

from docling_serve.orchestrator_factory import (
    _RQ_JOB_GONE,
    RedisTaskStatusMixin,
    _RQJobGone,
)


def _make_task(
    task_id: str = "test-task-1",
    status: TaskStatus = TaskStatus.SUCCESS,
    error_message: str | None = None,
    finished_at: datetime.datetime | None = None,
) -> Task:
    task = Task(
        task_id=task_id,
        task_type="convert",
        task_status=status,
        processing_meta={
            "num_docs": 0,
            "num_processed": 0,
            "num_succeeded": 0,
            "num_failed": 0,
        },
    )
    if error_message:
        task.error_message = error_message
    if finished_at:
        task.finished_at = finished_at
    return task


class FakeParentOrchestrator:
    """Minimal fake parent to satisfy MRO without real RQ/Redis."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.tasks: dict[str, Task] = {}
        self._task_result_keys: dict[str, str] = {}

    async def _update_task_from_rq(self, task_id: str) -> None:
        raise NoSuchJobError(f"No such job: {task_id}")

    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
        if task_id in self.tasks:
            return self.tasks[task_id]
        raise TaskNotFoundError(task_id)


class FakeMixin(RedisTaskStatusMixin, FakeParentOrchestrator):
    """Concrete class combining RedisTaskStatusMixin with a fake parent."""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self._task_result_keys: dict[str, str] = {}
        self.redis_prefix = "docling:tasks:"
        self._redis_pool = MagicMock()


# ---------------------------------------------------------------------------
# Layer A: Sentinel tests
# ---------------------------------------------------------------------------


class TestRQJobGoneSentinel:
    @pytest.mark.asyncio
    async def test_returns_sentinel_on_no_such_job_error(self):
        mixin = FakeMixin()
        result = await mixin._get_task_from_rq_direct("missing-job")
        assert isinstance(result, _RQJobGone)

    @pytest.mark.asyncio
    async def test_returns_none_on_generic_exception(self):
        mixin = FakeMixin()

        async def raise_generic(self_inner, task_id: str) -> None:
            raise RuntimeError("Redis connection lost")

        with patch.object(
            FakeParentOrchestrator, "_update_task_from_rq", raise_generic
        ):
            result = await mixin._get_task_from_rq_direct("some-task")
            assert result is None

    @pytest.mark.asyncio
    async def test_returns_task_when_rq_has_job(self):
        mixin = FakeMixin()
        expected_task = _make_task("rq-task", TaskStatus.SUCCESS)

        async def update_with_success(self_inner, task_id: str) -> None:
            mixin.tasks[task_id] = expected_task

        mock_redis = AsyncMock()
        mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.__aexit__ = AsyncMock(return_value=False)

        with (
            patch.object(
                FakeParentOrchestrator, "_update_task_from_rq", update_with_success
            ),
            patch(
                "docling_serve.orchestrator_factory.redis.Redis",
                return_value=mock_redis,
            ),
        ):
            result = await mixin._get_task_from_rq_direct("rq-task")
            assert isinstance(result, Task)
            assert result.task_status == TaskStatus.SUCCESS


# ---------------------------------------------------------------------------
# Layer B: task_status() reconciliation
# ---------------------------------------------------------------------------


class TestTaskStatusReconciliation:
    @pytest.mark.asyncio
    async def test_rq_gone_redis_success_cleans_up(self):
        """RQ job gone + Redis has SUCCESS -> return task, clean up tracking."""
        mixin = FakeMixin()
        cached_task = _make_task("t1", TaskStatus.SUCCESS)
        mixin.tasks["t1"] = cached_task
        mixin._task_result_keys["t1"] = "some-key"

        with (
            patch.object(mixin, "_get_task_from_rq_direct", return_value=_RQ_JOB_GONE),
            patch.object(mixin, "_get_task_from_redis", return_value=cached_task),
        ):
            result = await mixin.task_status("t1")

        assert result.task_status == TaskStatus.SUCCESS
        assert "t1" not in mixin.tasks
        assert "t1" not in mixin._task_result_keys

    @pytest.mark.asyncio
    async def test_rq_gone_redis_failure_cleans_up(self):
        """RQ job gone + Redis has FAILURE -> return task, clean up tracking."""
        mixin = FakeMixin()
        cached_task = _make_task("t1", TaskStatus.FAILURE)
        mixin.tasks["t1"] = cached_task

        with (
            patch.object(mixin, "_get_task_from_rq_direct", return_value=_RQ_JOB_GONE),
            patch.object(mixin, "_get_task_from_redis", return_value=cached_task),
        ):
            result = await mixin.task_status("t1")

        assert result.task_status == TaskStatus.FAILURE
        assert "t1" not in mixin.tasks

    @pytest.mark.asyncio
    async def test_rq_gone_redis_pending_marks_failure(self):
        """RQ job gone + Redis has PENDING -> mark as FAILURE with error_message."""
        mixin = FakeMixin()
        cached_task = _make_task("t2", TaskStatus.PENDING)
        mixin.tasks["t2"] = cached_task

        with (
            patch.object(mixin, "_get_task_from_rq_direct", return_value=_RQ_JOB_GONE),
            patch.object(mixin, "_get_task_from_redis", return_value=cached_task),
            patch.object(
                mixin, "_store_task_in_redis", new_callable=AsyncMock
            ) as mock_store,
        ):
            result = await mixin.task_status("t2")

        assert result.task_status == TaskStatus.FAILURE
        assert "orphaned" in result.error_message.lower()
        assert "t2" not in mixin.tasks
        mock_store.assert_called_once()

    @pytest.mark.asyncio
    async def test_rq_gone_redis_started_marks_failure(self):
        """RQ job gone + Redis has STARTED -> mark as FAILURE with error_message."""
        mixin = FakeMixin()
        cached_task = _make_task("t3", TaskStatus.STARTED)

        with (
            patch.object(mixin, "_get_task_from_rq_direct", return_value=_RQ_JOB_GONE),
            patch.object(mixin, "_get_task_from_redis", return_value=cached_task),
            patch.object(mixin, "_store_task_in_redis", new_callable=AsyncMock),
        ):
            result = await mixin.task_status("t3")

        assert result.task_status == TaskStatus.FAILURE
        assert "orphaned" in result.error_message.lower()

    @pytest.mark.asyncio
    async def test_rq_gone_no_redis_raises_not_found(self):
        """RQ job gone + not in Redis -> TaskNotFoundError."""
        mixin = FakeMixin()

        with (
            patch.object(mixin, "_get_task_from_rq_direct", return_value=_RQ_JOB_GONE),
            patch.object(mixin, "_get_task_from_redis", return_value=None),
        ):
            with pytest.raises(TaskNotFoundError):
                await mixin.task_status("ghost-task")

    @pytest.mark.asyncio
    async def test_rq_transient_error_falls_through_to_redis(self):
        """RQ returns None (transient) + Redis has SUCCESS -> return Redis task."""
        mixin = FakeMixin()
        cached_task = _make_task("t4", TaskStatus.SUCCESS)

        with (
            patch.object(mixin, "_get_task_from_rq_direct", return_value=None),
            patch.object(mixin, "_get_task_from_redis", return_value=cached_task),
        ):
            result = await mixin.task_status("t4")

        assert result.task_status == TaskStatus.SUCCESS

    @pytest.mark.asyncio
    async def test_rq_has_task_returns_directly(self):
        """When RQ has the task, return it directly."""
        mixin = FakeMixin()
        rq_task = _make_task("t5", TaskStatus.SUCCESS)

        with (
            patch.object(mixin, "_get_task_from_rq_direct", return_value=rq_task),
            patch.object(mixin, "_store_task_in_redis", new_callable=AsyncMock),
        ):
            result = await mixin.task_status("t5")

        assert result is rq_task
        assert mixin.tasks["t5"] is rq_task


# ---------------------------------------------------------------------------
# Layer C: Background zombie reaper
# ---------------------------------------------------------------------------


class TestZombieReaper:
    @pytest.mark.asyncio
    async def test_reaps_old_completed_tasks(self):
        mixin = FakeMixin()
        old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            hours=2
        )
        old_task = _make_task("old-1", TaskStatus.SUCCESS, finished_at=old_time)
        mixin.tasks["old-1"] = old_task
        mixin._task_result_keys["old-1"] = "key-1"

        reaper = asyncio.create_task(
            mixin._reap_zombie_tasks(interval=0.01, max_age=3600.0)
        )
        await asyncio.sleep(0.05)
        reaper.cancel()
        try:
            await reaper
        except asyncio.CancelledError:
            pass

        assert "old-1" not in mixin.tasks
        assert "old-1" not in mixin._task_result_keys

    @pytest.mark.asyncio
    async def test_keeps_recent_completed_tasks(self):
        mixin = FakeMixin()
        recent_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            minutes=5
        )
        recent_task = _make_task(
            "recent-1", TaskStatus.SUCCESS, finished_at=recent_time
        )
        mixin.tasks["recent-1"] = recent_task

        reaper = asyncio.create_task(
            mixin._reap_zombie_tasks(interval=0.01, max_age=3600.0)
        )
        await asyncio.sleep(0.05)
        reaper.cancel()
        try:
            await reaper
        except asyncio.CancelledError:
            pass

        assert "recent-1" in mixin.tasks

    @pytest.mark.asyncio
    async def test_keeps_in_progress_tasks(self):
        mixin = FakeMixin()
        old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            hours=2
        )
        started_task = _make_task("started-1", TaskStatus.STARTED)
        started_task.started_at = old_time
        mixin.tasks["started-1"] = started_task

        pending_task = _make_task("pending-1", TaskStatus.PENDING)
        mixin.tasks["pending-1"] = pending_task

        reaper = asyncio.create_task(
            mixin._reap_zombie_tasks(interval=0.01, max_age=3600.0)
        )
        await asyncio.sleep(0.05)
        reaper.cancel()
        try:
            await reaper
        except asyncio.CancelledError:
            pass

        assert "started-1" in mixin.tasks
        assert "pending-1" in mixin.tasks

    @pytest.mark.asyncio
    async def test_reaps_failed_tasks_with_finished_at(self):
        mixin = FakeMixin()
        old_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
            hours=2
        )
        failed_task = _make_task("failed-1", TaskStatus.FAILURE, finished_at=old_time)
        mixin.tasks["failed-1"] = failed_task

        reaper = asyncio.create_task(
            mixin._reap_zombie_tasks(interval=0.01, max_age=3600.0)
        )
        await asyncio.sleep(0.05)
        reaper.cancel()
        try:
            await reaper
        except asyncio.CancelledError:
            pass

        assert "failed-1" not in mixin.tasks


# ---------------------------------------------------------------------------
# Layer E: TTL alignment
# ---------------------------------------------------------------------------


class TestTTLAlignment:
    @pytest.mark.asyncio
    async def test_store_task_uses_results_ttl(self):
        """Metadata TTL should match eng_rq_results_ttl, not 86400."""
        mixin = FakeMixin()
        task = _make_task("ttl-task", TaskStatus.SUCCESS)

        mock_redis = AsyncMock()
        mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "docling_serve.orchestrator_factory.redis.Redis",
                return_value=mock_redis,
            ),
            patch(
                "docling_serve.orchestrator_factory.docling_serve_settings"
            ) as mock_settings,
        ):
            mock_settings.eng_rq_results_ttl = 14400
            await mixin._store_task_in_redis(task)

        mock_redis.set.assert_called_once()
        call_kwargs = mock_redis.set.call_args
        assert (
            call_kwargs.kwargs.get("ex") == 14400 or call_kwargs[1].get("ex") == 14400
        )


# ---------------------------------------------------------------------------
# Error message propagation through Redis
# ---------------------------------------------------------------------------


class TestErrorMessagePropagation:
    @pytest.mark.asyncio
    async def test_store_and_retrieve_error_message(self):
        """error_message should round-trip through Redis store/get."""
        mixin = FakeMixin()
        task = _make_task("err-task", TaskStatus.FAILURE, error_message="Out of memory")

        stored_data = {}

        async def fake_set(key: str, value: Any, ex: int = 0) -> None:
            stored_data[key] = value

        async def fake_get(key: str) -> bytes | None:
            val = stored_data.get(key)
            if val is None:
                return None
            return val.encode() if isinstance(val, str) else val

        mock_redis = AsyncMock()
        mock_redis.__aenter__ = AsyncMock(return_value=mock_redis)
        mock_redis.__aexit__ = AsyncMock(return_value=False)
        mock_redis.set = fake_set
        mock_redis.get = fake_get

        with (
            patch(
                "docling_serve.orchestrator_factory.redis.Redis",
                return_value=mock_redis,
            ),
            patch(
                "docling_serve.orchestrator_factory.docling_serve_settings"
            ) as mock_settings,
        ):
            mock_settings.eng_rq_results_ttl = 14400
            await mixin._store_task_in_redis(task)
            retrieved = await mixin._get_task_from_redis("err-task")

        assert retrieved is not None
        assert retrieved.error_message == "Out of memory"
        assert retrieved.task_status == TaskStatus.FAILURE

import asyncio
import datetime
import json
import logging
from functools import lru_cache
from typing import Any, Union

import redis.asyncio as redis
from rq.exceptions import NoSuchJobError

from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
    TaskNotFoundError,
)

from docling_serve.settings import AsyncEngine, docling_serve_settings
from docling_serve.storage import get_scratch

_log = logging.getLogger(__name__)


class _RQJobGone:
    """Sentinel: the RQ job has been deleted / TTL-expired."""


_RQ_JOB_GONE = _RQJobGone()


class RedisTaskStatusMixin:
    tasks: dict[str, Task]
    _task_result_keys: dict[str, str]
    config: Any

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.redis_prefix = "docling:tasks:"

        self._redis_pool = redis.ConnectionPool.from_url(
            self.config.redis_url,
            max_connections=docling_serve_settings.eng_rq_redis_max_connections,
            socket_timeout=docling_serve_settings.eng_rq_redis_socket_timeout,
            socket_connect_timeout=docling_serve_settings.eng_rq_redis_socket_connect_timeout,
            decode_responses=False,
        )
        _log.info(
            f"Redis connection pool initialized with max_connections="
            f"{docling_serve_settings.eng_rq_redis_max_connections}, "
            f"socket_timeout={docling_serve_settings.eng_rq_redis_socket_timeout}, "
            f"socket_connect_timeout={docling_serve_settings.eng_rq_redis_socket_connect_timeout}"
        )

    async def close_redis_pool(self) -> None:
        """Close the Redis connection pool and release all connections."""
        try:
            await self._redis_pool.aclose()
            _log.info("Redis connection pool closed successfully")
        except Exception as e:
            _log.error(f"Error closing Redis connection pool: {e}")

    def get_redis_pool_stats(self) -> dict[str, Any]:
        """Get current Redis connection pool statistics for monitoring."""
        try:
            # Access internal pool state for monitoring
            pool = self._redis_pool
            return {
                "max_connections": docling_serve_settings.eng_rq_redis_max_connections,
                "pool_class": pool.__class__.__name__,
            }
        except Exception as e:
            _log.warning(f"Could not retrieve Redis pool stats: {e}")
            return {}

    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
        """
        Get task status with zombie task reconciliation.

        Checks RQ first (authoritative), then Redis cache, then in-memory.
        When the RQ job is definitively gone (NoSuchJobError), reconciles:
        - Terminal status in Redis -> return it, clean up tracking
        - Non-terminal status in Redis -> mark FAILURE (orphaned task)
        - Not in Redis at all -> raise TaskNotFoundError
        """
        _log.info(f"Task {task_id} status check")

        rq_result = await self._get_task_from_rq_direct(task_id)

        if isinstance(rq_result, Task):
            _log.info(f"Task {task_id} in RQ: {rq_result.task_status}")
            self.tasks[task_id] = rq_result
            await self._store_task_in_redis(rq_result)
            return rq_result

        job_is_gone = isinstance(rq_result, _RQJobGone)

        task = await self._get_task_from_redis(task_id)
        if task:
            _log.info(f"Task {task_id} in Redis: {task.task_status}")

            if job_is_gone:
                if task.is_completed():
                    _log.info(
                        f"Task {task_id} completed ({task.task_status}) "
                        f"and RQ job expired — cleaning up tracking"
                    )
                    self.tasks.pop(task_id, None)
                    self._task_result_keys.pop(task_id, None)
                    return task
                else:
                    _log.warning(
                        f"Task {task_id} was {task.task_status} but RQ job is gone "
                        f"— marking as FAILURE (orphaned)"
                    )
                    task.set_status(TaskStatus.FAILURE)
                    if hasattr(task, "error_message"):
                        task.error_message = (
                            f"Task orphaned: RQ job expired while status was "
                            f"{task.task_status}. Likely caused by worker restart or "
                            f"Redis eviction."
                        )
                    self.tasks.pop(task_id, None)
                    self._task_result_keys.pop(task_id, None)
                    await self._store_task_in_redis(task)
                    return task

            if task.task_status in [TaskStatus.PENDING, TaskStatus.STARTED]:
                _log.debug(f"Task {task_id} verifying stale status")
                fresh_rq_task = await self._get_task_from_rq_direct(task_id)
                if (
                    isinstance(fresh_rq_task, Task)
                    and fresh_rq_task.task_status != task.task_status
                ):
                    _log.info(
                        f"Task {task_id} status updated: {fresh_rq_task.task_status}"
                    )
                    self.tasks[task_id] = fresh_rq_task
                    await self._store_task_in_redis(fresh_rq_task)
                    return fresh_rq_task
                else:
                    _log.debug(f"Task {task_id} status consistent")

            return task

        if job_is_gone:
            _log.warning(f"Task {task_id} not in RQ or Redis — truly gone")
            self.tasks.pop(task_id, None)
            raise TaskNotFoundError(task_id)

        try:
            parent_task = await super().task_status(task_id, wait)  # type: ignore[misc]
            _log.debug(f"Task {task_id} from parent: {parent_task.task_status}")
            await self._store_task_in_redis(parent_task)
            return parent_task
        except TaskNotFoundError:
            _log.warning(f"Task {task_id} not found")
            raise

    async def _get_task_from_redis(self, task_id: str) -> Task | None:
        try:
            async with redis.Redis(connection_pool=self._redis_pool) as r:
                task_data = await r.get(f"{self.redis_prefix}{task_id}:metadata")
                if not task_data:
                    return None

                data: dict[str, Any] = json.loads(task_data)
                meta = data.get("processing_meta") or {}
                meta.setdefault("num_docs", 0)
                meta.setdefault("num_processed", 0)
                meta.setdefault("num_succeeded", 0)
                meta.setdefault("num_failed", 0)

                task_kwargs: dict[str, Any] = {
                    "task_id": data["task_id"],
                    "task_type": data["task_type"],
                    "task_status": TaskStatus(data["task_status"]),
                    "processing_meta": meta,
                }
                if data.get("error_message") and "error_message" in Task.model_fields:
                    task_kwargs["error_message"] = data["error_message"]
                task = Task(**task_kwargs)
                return task
        except Exception as e:
            _log.error(f"Redis get task {task_id}: {e}")
            return None

    async def _get_task_from_rq_direct(
        self, task_id: str
    ) -> Union[Task, _RQJobGone, None]:
        try:
            _log.debug(f"Checking RQ for task {task_id}")

            # Do not consult RQ for tasks already in a terminal state. The temp-task
            # swap below would replace self.tasks[task_id] with a PENDING task, making
            # the base class's is_completed() guard ineffective and allowing a stale
            # RQ STARTED status to overwrite a watchdog-published FAILURE.
            original_task = self.tasks.get(task_id)
            if original_task is not None and original_task.is_completed():
                _log.debug(
                    f"Task {task_id} already terminal ({original_task.task_status}), "
                    f"skipping RQ direct check"
                )
                return original_task

            temp_task = Task(
                task_id=task_id,
                task_type="convert",
                task_status=TaskStatus.PENDING,
                processing_meta={
                    "num_docs": 0,
                    "num_processed": 0,
                    "num_succeeded": 0,
                    "num_failed": 0,
                },
            )

            original_task = self.tasks.get(task_id)
            self.tasks[task_id] = temp_task

            try:
                await super()._update_task_from_rq(task_id)  # type: ignore[misc]

                updated_task = self.tasks.get(task_id)
                if updated_task and updated_task.task_status != TaskStatus.PENDING:
                    _log.debug(f"RQ task {task_id}: {updated_task.task_status}")

                    result_ttl = docling_serve_settings.eng_rq_results_ttl
                    if task_id in self._task_result_keys:
                        try:
                            async with redis.Redis(
                                connection_pool=self._redis_pool
                            ) as r:
                                await r.set(
                                    f"{self.redis_prefix}{task_id}:result_key",
                                    self._task_result_keys[task_id],
                                    ex=result_ttl,
                                )
                                _log.debug(f"Stored result key for {task_id}")
                        except Exception as e:
                            _log.error(f"Store result key {task_id}: {e}")

                    return updated_task
                return None

            finally:
                if original_task:
                    self.tasks[task_id] = original_task
                elif task_id in self.tasks and self.tasks[task_id] == temp_task:
                    del self.tasks[task_id]

        except NoSuchJobError:
            _log.info(f"RQ job {task_id} no longer exists (TTL expired or deleted)")
            return _RQ_JOB_GONE
        except Exception as e:
            _log.error(f"RQ check {task_id}: {e}")
            return None

    async def get_raw_task(self, task_id: str) -> Task:
        if task_id in self.tasks:
            return self.tasks[task_id]

        task = await self._get_task_from_redis(task_id)
        if task:
            self.tasks[task_id] = task
            return task

        try:
            parent_task = await super().get_raw_task(task_id)  # type: ignore[misc]
            await self._store_task_in_redis(parent_task)
            return parent_task
        except TaskNotFoundError:
            raise

    async def _store_task_in_redis(self, task: Task) -> None:
        try:
            meta: Any = task.processing_meta
            if hasattr(meta, "model_dump"):
                meta = meta.model_dump()
            elif not isinstance(meta, dict):
                meta = {
                    "num_docs": 0,
                    "num_processed": 0,
                    "num_succeeded": 0,
                    "num_failed": 0,
                }

            data: dict[str, Any] = {
                "task_id": task.task_id,
                "task_type": (
                    task.task_type.value
                    if hasattr(task.task_type, "value")
                    else str(task.task_type)
                ),
                "task_status": task.task_status.value,
                "processing_meta": meta,
                "error_message": getattr(task, "error_message", None),
            }

            metadata_ttl = docling_serve_settings.eng_rq_results_ttl
            async with redis.Redis(connection_pool=self._redis_pool) as r:
                await r.set(
                    f"{self.redis_prefix}{task.task_id}:metadata",
                    json.dumps(data),
                    ex=metadata_ttl,
                )
        except Exception as e:
            _log.error(f"Store task {task.task_id}: {e}")

    async def enqueue(self, **kwargs):  # type: ignore[override]
        task = await super().enqueue(**kwargs)  # type: ignore[misc]
        await self._store_task_in_redis(task)
        return task

    async def task_result(self, task_id: str):  # type: ignore[override]
        result = await super().task_result(task_id)  # type: ignore[misc]
        if result is not None:
            return result

        try:
            async with redis.Redis(connection_pool=self._redis_pool) as r:
                result_key = await r.get(f"{self.redis_prefix}{task_id}:result_key")
                if result_key:
                    self._task_result_keys[task_id] = result_key.decode("utf-8")
                    return await super().task_result(task_id)  # type: ignore[misc]
        except Exception as e:
            _log.error(f"Redis result key {task_id}: {e}")

        return None

    async def _update_task_from_rq(self, task_id: str) -> None:
        original_status = (
            self.tasks[task_id].task_status if task_id in self.tasks else None
        )

        await super()._update_task_from_rq(task_id)  # type: ignore[misc]

        if task_id in self.tasks:
            new_status = self.tasks[task_id].task_status
            if original_status != new_status:
                _log.debug(f"Task {task_id} status: {original_status} -> {new_status}")
                await self._store_task_in_redis(self.tasks[task_id])

        if task_id in self._task_result_keys:
            result_ttl = docling_serve_settings.eng_rq_results_ttl
            try:
                async with redis.Redis(connection_pool=self._redis_pool) as r:
                    await r.set(
                        f"{self.redis_prefix}{task_id}:result_key",
                        self._task_result_keys[task_id],
                        ex=result_ttl,
                    )
            except Exception as e:
                _log.error(f"Store result key {task_id}: {e}")

    async def _reap_zombie_tasks(
        self, interval: float = 300.0, max_age: float = 3600.0
    ) -> None:
        """
        Periodically remove completed tasks from in-memory tracking.

        Args:
            interval: Seconds between sweeps (default 5 min)
            max_age: Remove completed tasks older than this (default 1h)
        """
        while True:
            await asyncio.sleep(interval)
            try:
                now = datetime.datetime.now(datetime.timezone.utc)
                cutoff = now - datetime.timedelta(seconds=max_age)
                to_remove: list[str] = []

                for task_id, task in list(self.tasks.items()):
                    if (
                        task.is_completed()
                        and task.finished_at
                        and task.finished_at < cutoff
                    ):
                        to_remove.append(task_id)

                for task_id in to_remove:
                    self.tasks.pop(task_id, None)
                    self._task_result_keys.pop(task_id, None)
                    _log.debug(f"Reaped zombie task {task_id}")

                if to_remove:
                    _log.info(f"Reaped {len(to_remove)} zombie tasks from tracking")

            except Exception as e:
                _log.error(f"Zombie reaper error: {e}")


@lru_cache
def get_async_orchestrator() -> BaseOrchestrator:
    if docling_serve_settings.eng_kind == AsyncEngine.LOCAL:
        from docling_jobkit.convert.manager import (
            DoclingConverterManager,
            DoclingConverterManagerConfig,
        )
        from docling_jobkit.orchestrators.local.orchestrator import (
            LocalOrchestrator,
            LocalOrchestratorConfig,
        )

        local_config = LocalOrchestratorConfig(
            num_workers=docling_serve_settings.eng_loc_num_workers,
            shared_models=docling_serve_settings.eng_loc_share_models,
            scratch_dir=get_scratch(),
        )

        cm_config = DoclingConverterManagerConfig(
            artifacts_path=docling_serve_settings.artifacts_path,
            options_cache_size=docling_serve_settings.options_cache_size,
            enable_remote_services=docling_serve_settings.enable_remote_services,
            allow_external_plugins=docling_serve_settings.allow_external_plugins,
            allow_custom_vlm_config=docling_serve_settings.allow_custom_vlm_config,
            allow_custom_picture_description_config=docling_serve_settings.allow_custom_picture_description_config,
            allow_custom_code_formula_config=docling_serve_settings.allow_custom_code_formula_config,
            max_num_pages=docling_serve_settings.max_num_pages,
            max_file_size=docling_serve_settings.max_file_size,
            queue_max_size=docling_serve_settings.queue_max_size,
            ocr_batch_size=docling_serve_settings.ocr_batch_size,
            layout_batch_size=docling_serve_settings.layout_batch_size,
            table_batch_size=docling_serve_settings.table_batch_size,
            batch_polling_interval_seconds=docling_serve_settings.batch_polling_interval_seconds,
        )
        cm = DoclingConverterManager(config=cm_config)

        return LocalOrchestrator(config=local_config, converter_manager=cm)

    elif docling_serve_settings.eng_kind == AsyncEngine.RQ:
        from docling_jobkit.orchestrators.rq.orchestrator import (
            RQOrchestrator,
            RQOrchestratorConfig,
        )

        from docling_serve.rq_instrumentation import wrap_rq_queue_for_tracing

        class RedisAwareRQOrchestrator(RedisTaskStatusMixin, RQOrchestrator):  # type: ignore[misc]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                super().__init__(*args, **kwargs)
                # Wrap RQ queue to inject trace context into jobs
                if docling_serve_settings.otel_enable_traces:
                    wrap_rq_queue_for_tracing(self._rq_queue)

            async def enqueue(self, **kwargs: Any) -> Task:  # type: ignore[override]
                """Override enqueue to use instrumented job function when tracing is enabled."""
                import base64
                import uuid
                import warnings

                from docling.datamodel.base_models import DocumentStream
                from docling_jobkit.datamodel.chunking import ChunkingExportOptions
                from docling_jobkit.datamodel.http_inputs import FileSource, HttpSource
                from docling_jobkit.datamodel.task import Task, TaskSource, TaskTarget
                from docling_jobkit.datamodel.task_meta import TaskType

                # Extract parameters
                sources: list[TaskSource] = kwargs.get("sources", [])
                target: TaskTarget = kwargs["target"]
                task_type: TaskType = kwargs.get("task_type", TaskType.CONVERT)
                options = kwargs.get("options")
                convert_options = kwargs.get("convert_options")
                chunking_options = kwargs.get("chunking_options")
                chunking_export_options = kwargs.get("chunking_export_options")

                if options is not None and convert_options is None:
                    convert_options = options
                    warnings.warn(
                        "'options' is deprecated and will be removed in a future version. "
                        "Use 'conversion_options' instead.",
                        DeprecationWarning,
                        stacklevel=2,
                    )

                task_id = str(uuid.uuid4())
                rq_sources: list[HttpSource | FileSource] = []
                for source in sources:
                    if isinstance(source, DocumentStream):
                        encoded_doc = base64.b64encode(source.stream.read()).decode()
                        rq_sources.append(
                            FileSource(filename=source.name, base64_string=encoded_doc)
                        )
                    elif isinstance(source, (HttpSource | FileSource)):
                        rq_sources.append(source)

                chunking_export_options = (
                    chunking_export_options or ChunkingExportOptions()
                )

                task = Task(
                    task_id=task_id,
                    task_type=task_type,
                    sources=rq_sources,
                    convert_options=convert_options,
                    chunking_options=chunking_options,
                    chunking_export_options=chunking_export_options,
                    target=target,
                )

                self.tasks.update({task.task_id: task})
                task_data = task.model_dump(mode="json", serialize_as_any=True)

                # Use instrumented job function if tracing is enabled
                if docling_serve_settings.otel_enable_traces:
                    job_func = "docling_serve.rq_job_wrapper.instrumented_docling_task"
                else:
                    job_func = "docling_jobkit.orchestrators.rq.worker.docling_task"

                self._rq_queue.enqueue(
                    job_func,
                    kwargs={"task_data": task_data},
                    job_id=task_id,
                    timeout=14400,
                    failure_ttl=docling_serve_settings.eng_rq_failure_ttl,
                )

                await self.init_task_tracking(task)

                # Store in Redis
                await self._store_task_in_redis(task)

                return task

        rq_config = RQOrchestratorConfig(
            redis_url=docling_serve_settings.eng_rq_redis_url,
            results_prefix=docling_serve_settings.eng_rq_results_prefix,
            sub_channel=docling_serve_settings.eng_rq_sub_channel,
            scratch_dir=get_scratch(),
            results_ttl=docling_serve_settings.eng_rq_results_ttl,
            failure_ttl=docling_serve_settings.eng_rq_failure_ttl,
            redis_max_connections=docling_serve_settings.eng_rq_redis_max_connections,
            redis_socket_timeout=docling_serve_settings.eng_rq_redis_socket_timeout,
            redis_socket_connect_timeout=docling_serve_settings.eng_rq_redis_socket_connect_timeout,
        )

        return RedisAwareRQOrchestrator(config=rq_config)

    elif docling_serve_settings.eng_kind == AsyncEngine.KFP:
        from docling_jobkit.orchestrators.kfp.orchestrator import (
            KfpOrchestrator,
            KfpOrchestratorConfig,
        )

        kfp_config = KfpOrchestratorConfig(
            endpoint=docling_serve_settings.eng_kfp_endpoint,
            token=docling_serve_settings.eng_kfp_token,
            ca_cert_path=docling_serve_settings.eng_kfp_ca_cert_path,
            self_callback_endpoint=docling_serve_settings.eng_kfp_self_callback_endpoint,
            self_callback_token_path=docling_serve_settings.eng_kfp_self_callback_token_path,
            self_callback_ca_cert_path=docling_serve_settings.eng_kfp_self_callback_ca_cert_path,
        )

        return KfpOrchestrator(config=kfp_config)

    raise RuntimeError(f"Engine {docling_serve_settings.eng_kind} not recognized.")

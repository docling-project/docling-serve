import json
import logging
from functools import lru_cache
from typing import Any

import redis.asyncio as redis

from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskStatus
from docling_jobkit.orchestrators.base_orchestrator import (
    BaseOrchestrator,
    TaskNotFoundError,
)

from docling_serve.settings import AsyncEngine, docling_serve_settings
from docling_serve.storage import get_scratch

_log = logging.getLogger(__name__)


class RedisTaskStatusMixin:
    tasks: dict[str, Task]
    _task_result_keys: dict[str, str]
    config: Any

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.redis_prefix = "docling:tasks:"
        self._redis_pool = redis.ConnectionPool.from_url(
            self.config.redis_url,
            max_connections=10,
            socket_timeout=2.0,
        )

    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
        """
        Get task status by checking Redis first, then falling back to RQ verification.

        When Redis shows 'pending' but RQ shows 'success', we update Redis
        and return the RQ status for cross-instance consistency.
        """
        _log.info(f"Task {task_id} status check")

        # Always check RQ directly first - this is the most reliable source
        rq_task = await self._get_task_from_rq_direct(task_id)
        if rq_task:
            _log.info(f"Task {task_id} in RQ: {rq_task.task_status}")

            # Update memory registry
            self.tasks[task_id] = rq_task

            # Store/update in Redis for other instances
            await self._store_task_in_redis(rq_task)
            return rq_task

        # If not in RQ, check Redis (maybe it's cached from another instance)
        task = await self._get_task_from_redis(task_id)
        if task:
            _log.info(f"Task {task_id} in Redis: {task.task_status}")

            # CRITICAL FIX: Check if Redis status might be stale
            # STARTED tasks might have completed since they were cached
            if task.task_status in [TaskStatus.PENDING, TaskStatus.STARTED]:
                _log.debug(f"Task {task_id} verifying stale status")

                # Try to get fresh status from RQ
                fresh_rq_task = await self._get_task_from_rq_direct(task_id)
                if fresh_rq_task and fresh_rq_task.task_status != task.task_status:
                    _log.info(
                        f"Task {task_id} status updated: {fresh_rq_task.task_status}"
                    )

                    # Update memory and Redis with fresh status
                    self.tasks[task_id] = fresh_rq_task
                    await self._store_task_in_redis(fresh_rq_task)
                    return fresh_rq_task
                else:
                    _log.debug(f"Task {task_id} status consistent")

            return task

        # Fall back to parent implementation
        try:
            parent_task = await super().task_status(task_id, wait)  # type: ignore[misc]
            _log.debug(f"Task {task_id} from parent: {parent_task.task_status}")

            # Store in Redis for other instances to find
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

                return Task(
                    task_id=data["task_id"],
                    task_type=data["task_type"],
                    task_status=TaskStatus(data["task_status"]),
                    processing_meta=meta,
                    error_message=data.get("error_message"),
                )
        except Exception as e:
            _log.error(f"Redis get task {task_id}: {e}")
            return None

    async def _get_task_from_rq_direct(self, task_id: str) -> Task | None:
        try:
            _log.debug(f"Checking RQ for task {task_id}")

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

                    # Store result key if available
                    if task_id in self._task_result_keys:
                        try:
                            async with redis.Redis(
                                connection_pool=self._redis_pool
                            ) as r:
                                await r.set(
                                    f"{self.redis_prefix}{task_id}:result_key",
                                    self._task_result_keys[task_id],
                                    ex=86400,
                                )
                                _log.debug(f"Stored result key for {task_id}")
                        except Exception as e:
                            _log.error(f"Store result key {task_id}: {e}")

                    return updated_task
                return None

            finally:
                # Restore original task state
                if original_task:
                    self.tasks[task_id] = original_task
                elif task_id in self.tasks and self.tasks[task_id] == temp_task:
                    # Only remove if it's still our temp task
                    del self.tasks[task_id]

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
                "error_message": task.error_message,
            }
            async with redis.Redis(connection_pool=self._redis_pool) as r:
                await r.set(
                    f"{self.redis_prefix}{task.task_id}:metadata",
                    json.dumps(data),
                    ex=86400,
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
            try:
                async with redis.Redis(connection_pool=self._redis_pool) as r:
                    await r.set(
                        f"{self.redis_prefix}{task_id}:result_key",
                        self._task_result_keys[task_id],
                        ex=86400,
                    )
            except Exception as e:
                _log.error(f"Store result key {task_id}: {e}")


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

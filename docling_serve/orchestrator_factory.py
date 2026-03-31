import asyncio
import datetime
import json
import logging
from functools import lru_cache
from typing import Any, Union

import redis.asyncio as redis
from rq.exceptions import NoSuchJobError
from rq.job import Job

from docling_jobkit.datamodel.task import Task
from docling_jobkit.datamodel.task_meta import TaskProcessingMeta, TaskStatus
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
    _redis_conn: Any

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

        Resolution order:
        1. Redis (terminal-state gate): if Redis already holds a completed state,
           return it immediately without consulting RQ. Prevents stale STARTED
           in RQ from overwriting a watchdog-published FAILURE.
        2. RQ: authoritative source for non-terminal states. Returns a Task only
           when the job is non-PENDING; returns None for PENDING, _RQJobGone on
           NoSuchJobError.
        3. Redis (fallback): reached only when RQ had no useful answer (PENDING
           or job expired). Handles job-gone reconciliation and stale-status
           cross-checks. Same Redis key as step 1, different role.
        When the RQ job is definitively gone (NoSuchJobError), reconciles:
        - Terminal status in Redis -> return it, clean up tracking
        - Non-terminal status in Redis -> mark FAILURE (orphaned task)
        - Not in Redis at all -> raise TaskNotFoundError
        """
        _log.info(f"Task {task_id} status check")

        # Before consulting RQ (which can report stale STARTED for up to 4 hours
        # after a worker kill), check Redis for a terminal state written by
        # _on_task_status_changed() or a previous poll. A terminal state in Redis
        # is authoritative: written either by the watchdog (after heartbeat expiry
        # + grace period) or by the normal success/failure path, neither of which
        # can be a false positive for a still-running job.
        task_from_redis = await self._get_task_from_redis(task_id)
        if task_from_redis is not None and task_from_redis.is_completed():
            _log.info(
                f"Task {task_id} terminal in Redis ({task_from_redis.task_status}), "
                f"skipping RQ check"
            )
            try:
                job_exists = await asyncio.to_thread(
                    Job.exists, task_id, self._redis_conn
                )
            except Exception as e:
                _log.warning(
                    f"Task {task_id} terminal in Redis, but RQ existence check "
                    f"failed: {e}"
                )
                job_exists = True
            if job_exists:
                self.tasks[task_id] = task_from_redis
            else:
                _log.info(
                    f"Task {task_id} terminal in Redis and RQ job is gone — "
                    f"cleaning up tracking"
                )
                self.tasks.pop(task_id, None)
                self._task_result_keys.pop(task_id, None)
            return task_from_redis

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
                meta = data["processing_meta"]
                meta.setdefault("num_docs", 0)
                meta.setdefault("num_processed", 0)
                meta.setdefault("num_succeeded", 0)
                meta.setdefault("num_failed", 0)

                task_kwargs: dict[str, Any] = {
                    "task_id": data["task_id"],
                    "task_type": data["task_type"],
                    "task_status": TaskStatus(data["task_status"]),
                    "processing_meta": meta,
                    "error_message": data["error_message"],
                    "created_at": data["created_at"],
                    "started_at": data["started_at"],
                    "finished_at": data["finished_at"],
                    "last_update_at": data["last_update_at"],
                }
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
            if isinstance(meta, TaskProcessingMeta):
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
                "task_type": task.task_type.value,
                "task_status": task.task_status.value,
                "processing_meta": meta,
                "error_message": task.error_message,
                "created_at": task.created_at.isoformat(),
                "started_at": (
                    task.started_at.isoformat() if task.started_at is not None else None
                ),
                "finished_at": (
                    task.finished_at.isoformat()
                    if task.finished_at is not None
                    else None
                ),
                "last_update_at": task.last_update_at.isoformat(),
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

    async def _on_task_status_changed(self, task: Task) -> None:
        await self._store_task_in_redis(task)

    async def enqueue(self, **kwargs):  # type: ignore[override]
        task = await super().enqueue(**kwargs)  # type: ignore[misc]
        await self._store_task_in_redis(task)
        return task

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
            result_removal_delay=docling_serve_settings.result_removal_delay,
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
            # VLM Pipeline Control
            default_vlm_preset=docling_serve_settings.default_vlm_preset,
            allowed_vlm_presets=docling_serve_settings.allowed_vlm_presets,
            custom_vlm_presets=docling_serve_settings.custom_vlm_presets,
            allowed_vlm_engines=docling_serve_settings.allowed_vlm_engines,
            allow_custom_vlm_config=docling_serve_settings.allow_custom_vlm_config,
            # Picture Description Control
            default_picture_description_preset=docling_serve_settings.default_picture_description_preset,
            allowed_picture_description_presets=docling_serve_settings.allowed_picture_description_presets,
            custom_picture_description_presets=docling_serve_settings.custom_picture_description_presets,
            allowed_picture_description_engines=docling_serve_settings.allowed_picture_description_engines,
            allow_custom_picture_description_config=docling_serve_settings.allow_custom_picture_description_config,
            # Code/Formula Control
            default_code_formula_preset=docling_serve_settings.default_code_formula_preset,
            allowed_code_formula_presets=docling_serve_settings.allowed_code_formula_presets,
            custom_code_formula_presets=docling_serve_settings.custom_code_formula_presets,
            allowed_code_formula_engines=docling_serve_settings.allowed_code_formula_engines,
            allow_custom_code_formula_config=docling_serve_settings.allow_custom_code_formula_config,
            # Table Structure Control
            default_table_structure_kind=docling_serve_settings.default_table_structure_kind,
            allowed_table_structure_kinds=docling_serve_settings.allowed_table_structure_kinds,
            # Layout Control
            default_layout_kind=docling_serve_settings.default_layout_kind,
            allowed_layout_kinds=docling_serve_settings.allowed_layout_kinds,
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
                callbacks = kwargs.get("callbacks", [])

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
                    callbacks=callbacks,
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
            result_removal_delay=docling_serve_settings.result_removal_delay,
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

    elif docling_serve_settings.eng_kind == AsyncEngine.RAY:
        from docling_jobkit.convert.manager import (
            DoclingConverterManager,
            DoclingConverterManagerConfig,
        )
        from docling_jobkit.orchestrators.ray.config import (
            RayOrchestratorConfig,
        )
        from docling_jobkit.orchestrators.ray.orchestrator import (
            RayOrchestrator,
        )

        # Create converter manager config
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

        # Create Fair Ray orchestrator config
        ray_config = RayOrchestratorConfig(
            # Redis Configuration
            redis_url=docling_serve_settings.eng_ray_redis_url,
            redis_max_connections=docling_serve_settings.eng_ray_redis_max_connections,
            redis_socket_timeout=docling_serve_settings.eng_ray_redis_socket_timeout,
            redis_socket_connect_timeout=docling_serve_settings.eng_ray_redis_socket_connect_timeout,
            # Result Storage
            results_ttl=docling_serve_settings.eng_ray_results_ttl,
            results_prefix=docling_serve_settings.eng_ray_results_prefix,
            result_removal_delay=docling_serve_settings.result_removal_delay,
            # Pub/Sub
            sub_channel=docling_serve_settings.eng_ray_sub_channel,
            # Fair Dispatcher
            dispatcher_interval=docling_serve_settings.eng_ray_dispatcher_interval,
            # Per-User Limits
            max_concurrent_tasks=docling_serve_settings.eng_ray_max_concurrent_tasks,
            max_queued_tasks=docling_serve_settings.eng_ray_max_queued_tasks,
            enable_queue_limit_rejection=docling_serve_settings.eng_ray_enable_queue_limit_rejection,
            max_documents=docling_serve_settings.eng_ray_max_documents,
            enable_document_limits=docling_serve_settings.eng_ray_enable_document_limits,
            # Ray Configuration
            ray_address=(
                None
                if docling_serve_settings.eng_ray_address in ["auto", "local"]
                else docling_serve_settings.eng_ray_address
            ),
            ray_namespace=docling_serve_settings.eng_ray_namespace,
            ray_runtime_env=docling_serve_settings.eng_ray_runtime_env,
            # Ray mTLS Configuration
            enable_mtls=docling_serve_settings.eng_ray_enable_mtls,
            ray_cluster_name=docling_serve_settings.eng_ray_cluster_name,
            # Ray Serve Autoscaling
            min_actors=docling_serve_settings.eng_ray_min_actors,
            max_actors=docling_serve_settings.eng_ray_max_actors,
            target_requests_per_replica=docling_serve_settings.eng_ray_target_requests_per_replica,
            upscale_delay_s=docling_serve_settings.eng_ray_upscale_delay_s,
            downscale_delay_s=docling_serve_settings.eng_ray_downscale_delay_s,
            ray_num_cpus_per_actor=docling_serve_settings.eng_ray_num_cpus_per_actor,
            # Fault Tolerance & Retry
            max_task_retries=docling_serve_settings.eng_ray_max_task_retries,
            retry_delay=docling_serve_settings.eng_ray_retry_delay,
            max_document_retries=docling_serve_settings.eng_ray_max_document_retries,
            # Ray Actor Configuration
            dispatcher_max_restarts=docling_serve_settings.eng_ray_dispatcher_max_restarts,
            dispatcher_max_task_retries=docling_serve_settings.eng_ray_dispatcher_max_task_retries,
            # Timeouts
            task_timeout=docling_serve_settings.eng_ray_task_timeout,
            document_timeout=docling_serve_settings.eng_ray_document_timeout,
            redis_operation_timeout=docling_serve_settings.eng_ray_redis_operation_timeout,
            # Health Checks
            enable_heartbeat=docling_serve_settings.eng_ray_enable_heartbeat,
            # Resource Management & Memory Monitoring
            ray_memory_limit_per_actor=docling_serve_settings.eng_ray_memory_limit_per_actor,
            ray_object_store_memory=docling_serve_settings.eng_ray_object_store_memory,
            enable_oom_protection=docling_serve_settings.eng_ray_enable_oom_protection,
            memory_warning_threshold=docling_serve_settings.eng_ray_memory_warning_threshold,
            # Scratch Directory
            scratch_dir=docling_serve_settings.eng_ray_scratch_dir or get_scratch(),
            # Logging
            log_level=docling_serve_settings.eng_ray_log_level,
        )

        return RayOrchestrator(config=ray_config, converter_manager=cm)

    raise RuntimeError(f"Engine {docling_serve_settings.eng_kind} not recognized.")

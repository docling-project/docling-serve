import datetime
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from kfp_server_api.models import V2beta1RuntimeState
from pydantic import BaseModel, TypeAdapter
from pydantic_settings import SettingsConfigDict

from docling_serve.datamodel.callback import (
    ProgressCallbackRequest,
    ProgressSetNumDocs,
    ProgressUpdateProcessed,
)
from docling_serve.datamodel.convert import ConvertDocumentsOptions
from docling_serve.datamodel.engines import TaskStatus
from docling_serve.datamodel.kfp import CallbackSpec
from docling_serve.datamodel.requests import HttpSource
from docling_serve.datamodel.task import Task, TaskSource
from docling_serve.datamodel.task_meta import TaskProcessingMeta
from docling_serve.engines.async_kfp.kfp_pipeline import process
from docling_serve.engines.async_orchestrator import (
    BaseAsyncOrchestrator,
    ProgressInvalid,
)
from docling_serve.settings import docling_serve_settings

_log = logging.getLogger(__name__)


class _RunItem(BaseModel):
    model_config = SettingsConfigDict(arbitrary_types_allowed=True)

    run_id: str
    state: str
    created_at: datetime.datetime
    scheduled_at: datetime.datetime
    finished_at: datetime.datetime


class AsyncKfpOrchestrator(BaseAsyncOrchestrator):
    def __init__(self):
        super().__init__()
        import kfp

        kfp_endpoint = docling_serve_settings.eng_kfp_endpoint
        if kfp_endpoint is None:
            raise ValueError("KFP endpoint is required when using the KFP engine.")

        kube_sa_token_path = Path("/run/secrets/kubernetes.io/serviceaccount/token")
        kube_sa_ca_cert_path = Path(
            "/run/secrets/kubernetes.io/serviceaccount/service-ca.crt"
        )

        ssl_ca_cert = docling_serve_settings.eng_kfp_ca_cert_path
        token = docling_serve_settings.eng_kfp_token
        if (
            ssl_ca_cert is None
            and ".svc" in kfp_endpoint.host
            and kube_sa_ca_cert_path.exists()
        ):
            ssl_ca_cert = str(kube_sa_ca_cert_path)
        if token is None and kube_sa_token_path.exists():
            token = kube_sa_token_path.read_text()

        self._client = kfp.Client(
            host=str(kfp_endpoint),
            existing_token=token,
            ssl_ca_cert=ssl_ca_cert,
            # verify_ssl=False,
        )

    async def enqueue(
        self, sources: list[TaskSource], options: ConvertDocumentsOptions
    ) -> Task:
        callbacks = []
        if docling_serve_settings.eng_kfp_self_callback_endpoint is not None:
            headers = {}
            if docling_serve_settings.eng_kfp_self_callback_token_path is not None:
                token = (
                    docling_serve_settings.eng_kfp_self_callback_token_path.read_text()
                )
                headers["Authorization"] = f"Bearer {token}"
            ca_cert = ""
            if docling_serve_settings.eng_kfp_self_callback_ca_cert_path is not None:
                ca_cert = docling_serve_settings.eng_kfp_self_callback_ca_cert_path.read_text()
            callbacks.append(
                CallbackSpec(
                    url=docling_serve_settings.eng_kfp_self_callback_endpoint,
                    headers=headers,
                    ca_cert=ca_cert,
                )
            )

        CallbacksType = TypeAdapter(list[CallbackSpec])
        SourcesListType = TypeAdapter(list[HttpSource])
        http_sources = [s for s in sources if isinstance(s, HttpSource)]
        # hack: since the current kfp backend is not resolving the job_id placeholder,
        # we set the run_name and pass it as argument to the job itself.
        run_name = f"docling-job-{uuid.uuid4()}"
        kfp_run = self._client.create_run_from_pipeline_func(
            process,
            arguments={
                "batch_size": 10,
                "sources": SourcesListType.dump_python(http_sources, mode="json"),
                "options": options.model_dump(mode="json"),
                "callbacks": CallbacksType.dump_python(callbacks, mode="json"),
                "run_name": run_name,
            },
            run_name=run_name,
        )
        task_id = kfp_run.run_id

        task = Task(task_id=task_id, sources=sources, options=options)
        await self.init_task_tracking(task)
        return task

    async def _update_task_from_run(self, task_id: str, wait: float = 0.0):
        run_info = self._client.get_run(run_id=task_id)
        task = await self.get_raw_task(task_id=task_id)
        # RUNTIME_STATE_UNSPECIFIED = "RUNTIME_STATE_UNSPECIFIED"
        # PENDING = "PENDING"
        # RUNNING = "RUNNING"
        # SUCCEEDED = "SUCCEEDED"
        # SKIPPED = "SKIPPED"
        # FAILED = "FAILED"
        # CANCELING = "CANCELING"
        # CANCELED = "CANCELED"
        # PAUSED = "PAUSED"
        if run_info.state == V2beta1RuntimeState.SUCCEEDED:
            task.set_status(TaskStatus.SUCCESS)
        elif run_info.state == V2beta1RuntimeState.PENDING:
            task.set_status(TaskStatus.PENDING)
        elif run_info.state == V2beta1RuntimeState.RUNNING:
            task.set_status(TaskStatus.STARTED)
        else:
            task.set_status(TaskStatus.FAILURE)

    async def task_status(self, task_id: str, wait: float = 0.0) -> Task:
        await self._update_task_from_run(task_id=task_id, wait=wait)
        return await self.get_raw_task(task_id=task_id)

    async def _get_pending(self) -> list[_RunItem]:
        runs: list[_RunItem] = []
        next_page: Optional[str] = None
        while True:
            res = self._client.list_runs(
                page_token=next_page,
                page_size=20,
                filter=json.dumps(
                    {
                        "predicates": [
                            {
                                "operation": "EQUALS",
                                "key": "state",
                                "stringValue": "PENDING",
                            }
                        ]
                    }
                ),
            )
            if res.runs is not None:
                for run in res.runs:
                    runs.append(
                        _RunItem(
                            run_id=run.run_id,
                            state=run.state,
                            created_at=run.created_at,
                            scheduled_at=run.scheduled_at,
                            finished_at=run.finished_at,
                        )
                    )
            if res.next_page_token is None:
                break
            next_page = res.next_page_token
        return runs

    async def queue_size(self) -> int:
        runs = await self._get_pending()
        return len(runs)

    async def get_queue_position(self, task_id: str) -> Optional[int]:
        runs = await self._get_pending()
        for pos, run in enumerate(runs, start=1):
            if run.run_id == task_id:
                return pos
        return None

    async def process_queue(self):
        return

    async def warm_up_caches(self):
        return

    async def _get_run_id(self, run_name: str) -> str:
        res = self._client.list_runs(
            filter=json.dumps(
                {
                    "predicates": [
                        {
                            "operation": "EQUALS",
                            "key": "name",
                            "stringValue": run_name,
                        }
                    ]
                }
            ),
        )
        if res.runs is not None and len(res.runs) > 0:
            return res.runs[0].run_id
        raise RuntimeError(f"Run with {run_name=} not found.")

    async def receive_task_progress(self, request: ProgressCallbackRequest):
        task_id = await self._get_run_id(run_name=request.task_id)
        progress = request.progress
        task = await self.get_raw_task(task_id=task_id)

        if isinstance(progress, ProgressSetNumDocs):
            task.processing_meta = TaskProcessingMeta(num_docs=progress.num_docs)
            task.task_status = TaskStatus.STARTED

        elif isinstance(progress, ProgressUpdateProcessed):
            if task.processing_meta is None:
                raise ProgressInvalid(
                    "UpdateProcessed was called before setting the expected number of documents."
                )
            task.processing_meta.num_processed += progress.num_processed
            task.processing_meta.num_succeeded += progress.num_succeeded
            task.processing_meta.num_failed += progress.num_failed
            task.task_status = TaskStatus.STARTED

        # TODO: could be moved to BackgroundTask
        await self.notify_task_subscribers(task_id=task_id)

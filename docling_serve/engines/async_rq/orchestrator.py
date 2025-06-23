import logging
import uuid
from subprocess import PIPE, Popen
from typing import Optional

from redis import Redis
from rq import Queue, Worker
from rq.job import Job, JobStatus

from docling_serve.datamodel.convert import ConvertDocumentsOptions
from docling_serve.datamodel.engines import TaskStatus
from docling_serve.datamodel.task import Task, TaskSource
from docling_serve.docling_conversion import get_converter, get_pdf_pipeline_opts
from docling_serve.engines.async_orchestrator import BaseAsyncOrchestrator
from docling_serve.engines.async_rq.job import conversion_task
from docling_serve.settings import docling_serve_settings

_log = logging.getLogger(__name__)


class AsyncRQOrchestrator(BaseAsyncOrchestrator):
    def __init__(self, dev_mode=False):
        super().__init__()
        self.dev_mode = dev_mode
        self.worker_processes: list[Popen] = []
        self.redis_conn = Redis(
            host=docling_serve_settings.eng_rq_host,
            port=docling_serve_settings.eng_rq_port,
        )
        self.task_queue = Queue(
            "conversion_queue", connection=self.redis_conn, default_timeout=7200
        )

    async def notify_end_job(self, task_id):
        # TODO: check if this is necessary
        pass

    async def enqueue(
        self, sources: list[TaskSource], options: ConvertDocumentsOptions
    ) -> Task:
        task_id = str(uuid.uuid4())
        task = Task(task_id=task_id, sources=sources, options=options)
        self.tasks.update({task.task_id: task})
        task_data = task.model_dump(mode="json")
        self.task_queue.enqueue(
            conversion_task,
            kwargs={"task_data": task_data},
            job_id=task_id,
            timeout=7200,
        )
        await self.init_task_tracking(task)

        return task

    async def queue_size(self) -> int:
        return self.task_queue.count

    async def get_queue_position(self, task_id: str) -> Optional[int]:
        try:
            # On fetching Job to get queue position, we also get the status
            # in order to keep the status updated in the tasks list
            job = Job.fetch(task_id, connection=self.redis_conn)
            status = job.get_status()
            queue_pos = job.get_position()
            if status == JobStatus.FINISHED:
                task = self.tasks[task_id]
                task.task_status = TaskStatus.SUCCESS
                task.result = job.return_value()
                self.tasks.update({task.task_id: task})
            elif status == JobStatus.QUEUED or status == JobStatus.SCHEDULED:
                task = self.tasks[task_id]
                task.task_status = TaskStatus.PENDING
                self.tasks.update({task.task_id: task})
            elif status == JobStatus.STARTED:
                task = self.tasks[task_id]
                task.task_status = TaskStatus.STARTED
                self.tasks.update({task.task_id: task})
            else:
                task = self.tasks[task_id]
                task.task_status = TaskStatus.FAILURE
                self.tasks.update({task.task_id: task})
            return queue_pos + 1 if queue_pos is not None else 0
        except Exception as e:
            _log.error("An error occour getting queue position.", exc_info=e)
            return None

    def run_local_worker(self):
        # Command to run the RQ worker
        command = ["rq", "worker", "conversion_queue"]

        # Start the RQ worker as a subprocess
        process = Popen(command, stdout=PIPE, stderr=PIPE)
        return process

    async def process_queue(self):
        if self.dev_mode:
            for i in range(docling_serve_settings.eng_loc_num_workers):
                _log.debug(f"Starting worker {i}")
                self.worker_processes.append(self.run_local_worker())

    async def warm_up_caches(self):
        # if not local, warm up caches will run in worker container
        if self.dev_mode:
            # Converter with default options
            _log.debug("warming caches")
            pdf_format_option = get_pdf_pipeline_opts(ConvertDocumentsOptions())
            get_converter(pdf_format_option)

    async def check_connection(self):
        # Check redis connection is up
        try:
            self.redis_conn.ping()
        except Exception:
            raise RuntimeError("No connection to Redis")

        if not self.dev_mode:
            # Count the number of workers in redis connection
            workers = Worker.count(connection=self.redis_conn)
            if workers == 0:
                raise RuntimeError("No workers connected to Redis")

    async def kill_workers(self):
        for i, process in enumerate(self.worker_processes):
            process.terminate()
            _log.debug(f"Killed worker {i}")

import asyncio
import logging
import shutil
import time
from typing import TYPE_CHECKING, Any, Optional, Union

from fastapi.responses import FileResponse

from docling.datamodel.base_models import DocumentStream

from docling_serve.datamodel.engines import TaskStatus
from docling_serve.datamodel.requests import FileSource, HttpSource
from docling_serve.docling_conversion import convert_documents
from docling_serve.response_preparation import process_results
from docling_serve.storage import get_scratch

if TYPE_CHECKING:
    from docling_serve.engines.async_local.orchestrator import AsyncLocalOrchestrator

_log = logging.getLogger(__name__)


class AsyncLocalWorker:
    def __init__(self, worker_id: int, orchestrator: "AsyncLocalOrchestrator"):
        self.worker_id = worker_id
        self.orchestrator = orchestrator

    async def loop(self):
        _log.debug(f"Starting loop for worker {self.worker_id}")
        while True:
            task_id: str = await self.orchestrator.task_queue.get()
            self.orchestrator.queue_list.remove(task_id)

            if task_id not in self.orchestrator.tasks:
                raise RuntimeError(f"Task {task_id} not found.")
            task = self.orchestrator.tasks[task_id]

            try:
                task.set_status(TaskStatus.STARTED)
                _log.info(f"Worker {self.worker_id} processing task {task_id}")

                # Notify clients about task updates
                await self.orchestrator.notify_task_subscribers(task_id)

                # Notify clients about queue updates
                await self.orchestrator.notify_queue_positions()

                # Define a callback function to send progress updates to the client.
                # TODO: send partial updates, e.g. when a document in the batch is done
                def run_conversion():
                    convert_sources: list[Union[str, DocumentStream]] = []
                    headers: Optional[dict[str, Any]] = None
                    for source in task.sources:
                        if isinstance(source, DocumentStream):
                            convert_sources.append(source)
                        elif isinstance(source, FileSource):
                            convert_sources.append(source.to_document_stream())
                        elif isinstance(source, HttpSource):
                            convert_sources.append(str(source.url))
                            if headers is None and source.headers:
                                headers = source.headers

                    # Note: results are only an iterator->lazy evaluation
                    results = convert_documents(
                        sources=convert_sources,
                        options=task.options,
                        headers=headers,
                    )

                    # The real processing will happen here
                    work_dir = get_scratch() / task_id
                    response = process_results(
                        conversion_options=task.options,
                        conv_results=results,
                        work_dir=work_dir,
                    )

                    if work_dir.exists():
                        task.scratch_dir = work_dir
                        if not isinstance(response, FileResponse):
                            _log.warning(
                                f"Task {task_id=} produced content in {work_dir=} but the response is not a file."
                            )
                            shutil.rmtree(work_dir, ignore_errors=True)

                    return response

                start_time = time.monotonic()

                # Run the prediction in a thread to avoid blocking the event loop.
                # Get the current event loop
                # loop = asyncio.get_event_loop()
                # future = asyncio.run_coroutine_threadsafe(
                #     run_conversion(),
                #     loop=loop
                # )
                # response = future.result()

                # Run in a thread
                response = await asyncio.to_thread(
                    run_conversion,
                )
                processing_time = time.monotonic() - start_time

                task.result = response
                task.sources = []
                task.options = None

                task.set_status(TaskStatus.SUCCESS)
                _log.info(
                    f"Worker {self.worker_id} completed job {task_id} "
                    f"in {processing_time:.2f} seconds"
                )

            except Exception as e:
                _log.error(
                    f"Worker {self.worker_id} failed to process job {task_id}: {e}"
                )
                task.set_status(TaskStatus.FAILURE)

            finally:
                await self.orchestrator.notify_task_subscribers(task_id)
                self.orchestrator.task_queue.task_done()
                _log.debug(f"Worker {self.worker_id} completely done with {task_id}")

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, Optional, Union

from fastapi import BackgroundTasks

from docling.datamodel.base_models import DocumentStream

from docling_serve.datamodel.engines import TaskStatus
from docling_serve.datamodel.requests import FileSource, HttpSource
from docling_serve.datamodel.responses import ConvertDocumentResponse
from docling_serve.docling_conversion import convert_documents
from docling_serve.response_preparation import process_results

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
                task.task_status = TaskStatus.STARTED
                _log.info(f"Worker {self.worker_id} processing task {task_id}")

                # Notify clients about task updates
                await self.orchestrator.notify_task_subscribers(task_id)

                # Notify clients about queue updates
                await self.orchestrator.notify_queue_positions()

                # Get the current event loop
                asyncio.get_event_loop()

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
                    response = process_results(
                        background_tasks=BackgroundTasks(),
                        conversion_options=task.options,
                        conv_results=results,
                    )

                    return response

                # Run the prediction in a thread to avoid blocking the event loop.
                start_time = time.monotonic()
                # future = asyncio.run_coroutine_threadsafe(
                #     run_conversion(),
                #     loop=loop
                # )
                # response = future.result()

                response = await asyncio.to_thread(
                    run_conversion,
                )
                processing_time = time.monotonic() - start_time

                if not isinstance(response, ConvertDocumentResponse):
                    _log.error(
                        f"Worker {self.worker_id} got un-processable "
                        "result for {task_id}: {type(response)}"
                    )
                task.result = response
                task.sources = []
                task.options = None

                task.task_status = TaskStatus.SUCCESS
                _log.info(
                    f"Worker {self.worker_id} completed job {task_id} "
                    f"in {processing_time:.2f} seconds"
                )

            except Exception as e:
                _log.error(
                    f"Worker {self.worker_id} failed to process job {task_id}: {e}"
                )
                task.task_status = TaskStatus.FAILURE

            finally:
                await self.orchestrator.notify_task_subscribers(task_id)
                self.orchestrator.task_queue.task_done()
                _log.debug(f"Worker {self.worker_id} completely done with {task_id}")

import asyncio
import logging
import threading
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from fastapi import BackgroundTasks

from docling.datamodel.base_models import DocumentStream

from docling_serve.datamodel.engines import TaskStatus
from docling_serve.datamodel.requests import ConvertDocumentFileSourcesRequest
from docling_serve.datamodel.responses import ConvertDocumentResponse
from docling_serve.docling_conversion import convert_documents
from docling_serve.response_preparation import process_results

if TYPE_CHECKING:
    from docling_serve.engines.async_local.orchestrator import AsyncLocalOrchestrator

_log = logging.getLogger(__name__)


class AsyncLocalWorker:
    _lock = threading.Lock()

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
                    sources: List[Union[str, DocumentStream]] = []
                    headers: Optional[Dict[str, Any]] = None
                    if isinstance(task.request, ConvertDocumentFileSourcesRequest):
                        for file_source in task.request.file_sources:
                            sources.append(file_source.to_document_stream())
                    else:
                        for http_source in task.request.http_sources:
                            sources.append(http_source.url)
                            if headers is None and http_source.headers:
                                headers = http_source.headers

                    # TODO: When Docling will puts locks around Pypdfium2
                    # we could run in parallel without the lock
                    with AsyncLocalWorker._lock:
                        # Note: results are only an iterator->lazy evaluation
                        results = convert_documents(
                            sources=sources,
                            options=task.request.options,
                            headers=headers,
                        )

                        # The real processing will happen here
                        response = process_results(
                            background_tasks=BackgroundTasks(),
                            conversion_options=task.request.options,
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
                task.request = None

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

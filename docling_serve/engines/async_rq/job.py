import logging
import shutil
from typing import Any, Optional, Union

from fastapi.responses import FileResponse

from docling.datamodel.base_models import DocumentStream

from docling_serve.datamodel.convert import ConvertDocumentsOptions
from docling_serve.datamodel.requests import FileSource, HttpSource
from docling_serve.datamodel.task import Task
from docling_serve.docling_conversion import (
    convert_documents,
)
from docling_serve.response_preparation import process_results
from docling_serve.storage import get_scratch

_log = logging.getLogger(__name__)


def conversion_task(task_data: dict):
    _log.debug("started task")
    task = Task.model_validate(task_data)
    task_id = task.task_id

    _log.debug(f"task_id inside task is: {task_id}")
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

    if not task.options:
        options = ConvertDocumentsOptions()
    else:
        options = task.options
    # Note: results are only an iterator->lazy evaluation
    results = convert_documents(
        sources=convert_sources,
        options=options,
        headers=headers,
    )

    # The real processing will happen here
    work_dir = get_scratch() / task_id
    response = process_results(
        conversion_options=options,
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

    _log.debug("ended task")
    return response

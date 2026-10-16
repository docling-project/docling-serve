import json
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from docling.datamodel.base_models import ConversionStatus
from docling.datamodel.service.responses import (
    ConvertDocumentResponse,
    DoclingTaskResult,
    ExportDocumentResponse,
    ExportResult,
)
from docling_core.types.doc.document import DoclingDocument
from docling_core.types.doc.labels import DocItemLabel

from docling_serve.response_preparation import prepare_response


def _stored_result() -> DoclingTaskResult:
    doc = DoclingDocument(name="sample")
    doc.add_text(label=DocItemLabel.TEXT, text="hello")
    result = DoclingTaskResult(
        result=ExportResult(
            document=ExportDocumentResponse(filename="a.pdf", json_content=doc),
            status=ConversionStatus.SUCCESS,
        ),
        processing_time=0.1,
        num_converted=1,
        num_succeeded=1,
        num_failed=0,
    )
    # Mimic the RQ/Ray Redis round-trip, which re-validates the document.
    return DoclingTaskResult.model_validate(result.model_dump())


async def _prepare(target_document_version: str | None):
    return await prepare_response(
        task_id="t",
        task_result=_stored_result(),
        orchestrator=SimpleNamespace(on_result_fetched=None),  # type: ignore[arg-type]
        background_tasks=BackgroundTasks(),
        target_document_version=target_document_version,
    )


@pytest.mark.asyncio
async def test_in_body_json_is_projected_after_redis_round_trip():
    response = await _prepare("1.5.0")

    assert isinstance(response, JSONResponse)
    json_content = json.loads(response.body)["document"]["json_content"]
    assert json_content["version"] == "1.5.0"
    assert "meta" not in json.dumps(json_content)
    assert json_content["texts"][0]["text"] == "hello"


@pytest.mark.asyncio
async def test_in_body_json_untouched_without_target():
    response = await _prepare(None)

    assert isinstance(response, ConvertDocumentResponse)

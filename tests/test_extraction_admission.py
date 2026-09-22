"""Offline extraction admission and durable HTTP response contracts."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from docling.datamodel.extraction_options import ExtractionVlmOptions
from docling.datamodel.service.responses import (
    DoclingTaskResult,
    PublicFailureInfo,
)
from docling.datamodel.service.tasks import TaskType
from docling_jobkit.datamodel.stored_outcome import (
    StoredFailureOutcome,
    StoredSuccessOutcome,
)
from docling_jobkit.datamodel.task import Task

from docling_serve.app import create_app
from docling_serve.orchestrator_factory import get_async_orchestrator
from docling_serve.policy import build_service_policy
from docling_serve.settings import (
    AsyncEngine,
    DoclingServeSettings,
    docling_serve_settings,
)

SCHEMA = {
    "type": "object",
    "properties": {"total": {"type": "number"}},
    "required": ["total"],
    "additionalProperties": False,
}
NATIVE = {"template": {"format": "nuextract", "value": {"total": "number"}}}
EXAMPLE = {"template": {"format": "example_json", "value": {"total": 5}}}


@pytest.fixture
def extraction_app(monkeypatch):
    monkeypatch.setattr(docling_serve_settings, "eng_kind", AsyncEngine.LOCAL)
    monkeypatch.setattr(docling_serve_settings, "api_key", "stage10-key")
    orchestrator = SimpleNamespace(
        enqueue=AsyncMock(
            return_value=Task(task_id="extract", task_type=TaskType.EXTRACT)
        ),
        get_queue_position=AsyncMock(return_value=0),
    )
    app = create_app()
    app.dependency_overrides[get_async_orchestrator] = lambda: orchestrator
    monkeypatch.setattr(docling_serve_settings, "eng_kind", AsyncEngine.RAY)
    return app, orchestrator


@pytest.mark.parametrize(
    "preset", ["nuextract_2b", "nuextract_3", "granite_vision_4_1", "lift"]
)
def test_startup_validates_stable_default_without_target_or_extractor(preset):
    policy = build_service_policy(
        DoclingServeSettings(default_extraction_preset=preset)
    )
    assert policy.extraction_manager._get_extractor.cache_info().currsize == 0


def test_startup_resolves_operator_defined_default():
    custom = ExtractionVlmOptions.from_preset("nuextract_2b").model_copy(
        update={"scale": 1.25}
    )
    policy = build_service_policy(
        DoclingServeSettings(
            default_extraction_preset="server_model",
            allowed_extraction_presets=["server_model"],
            custom_extraction_presets={"server_model": custom.model_dump(mode="json")},
        )
    )

    assert policy.extraction_manager.resolve_extraction_model().scale == 1.25


@pytest.mark.parametrize(
    "settings, message",
    [
        ({"default_extraction_preset": "unknown"}, "not found"),
        ({"allowed_extraction_presets": []}, "not allowed"),
        ({"allowed_extraction_engines": []}, "not allowed"),
    ],
)
def test_startup_rejects_invalid_operator_default(settings, message):
    with pytest.raises(ValueError, match=message):
        build_service_policy(DoclingServeSettings(**settings))


def test_openapi_advertises_tagged_guidance_mode_and_canonical_items():
    schema = create_app().openapi()
    models = schema["components"]["schemas"]
    options = models["ExtractDocumentsOptions"]
    assert "target" in options["required"]
    assert "template" not in options["properties"]
    assert options["properties"]["output_mode"]["enum"] == [
        "prompt_only",
        "schema_constrained",
    ]
    assert models["ExtractionTemplate"]["required"] == ["format", "value"]
    assert set(models["ExtractionTemplate"]["properties"]["format"]["enum"]) == {
        "nuextract",
        "example_json",
    }
    result = models["ExtractionDocumentResult"]
    assert set(result["required"]) == {
        "source_index",
        "source_uri",
        "filename",
        "status",
    }
    assert "items" in result["properties"] and "pages" not in result["properties"]
    item = models["ExtractionItem"]["properties"]
    assert item["scope"]["discriminator"]["propertyName"] == "kind"
    assert set(item["validation_status"]["enum"]) == {
        "not_requested",
        "not_run",
        "passed",
        "failed",
    }
    refs = schema["paths"]["/v1/result/{task_id}"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["anyOf"]
    assert {"$ref": "#/components/schemas/ExtractDocumentResponse"} in refs


@pytest.mark.parametrize(
    "options, message",
    [
        ({"template": {}}, "target"),
        ({"target": {}}, "requires output_schema or template"),
        ({"target": {**NATIVE, "unknown": True}}, "Extra inputs"),
        ({"target": {"template": {"total": "number"}}}, "format"),
        ({"target": {"template": {"format": "other", "value": {}}}}, "Input should be"),
        ({"target": NATIVE, "grouping": "document"}, "Extra inputs"),
        ({"target": NATIVE, "output_mode": "automatic"}, "Input should be"),
        ({"target": EXAMPLE}, "NuExtract requires"),
        (
            {"target": NATIVE, "extraction_preset": "granite_vision_4_1"},
            "native dialect",
        ),
        ({"target": EXAMPLE, "extraction_preset": "lift"}, "requires an output schema"),
        ({"target": {"output_schema": {"type": "broken"}}}, "invalid JSON Schema"),
        ({"target": {"output_schema": {"type": "array"}}}, "object"),
        (
            {
                "target": {
                    "output_schema": {
                        "type": "object",
                        "properties": {"total": {"$ref": "https://example.com/schema"}},
                    }
                }
            },
            "only local",
        ),
        (
            {
                "target": {
                    "output_schema": {
                        "type": "object",
                        "patternProperties": {".*": {"type": "string"}},
                    }
                }
            },
            "unsupported",
        ),
        (
            {"target": {"output_schema": SCHEMA}, "output_mode": "schema_constrained"},
            "vLLM API engine",
        ),
        ({"target": NATIVE, "extraction_preset": "unknown"}, "not found"),
        (
            {
                "target": EXAMPLE,
                "extraction_preset": "granite_vision_4_1",
                "input_channels": "text",
            },
            "does not accept a text",
        ),
        (
            {
                "target": EXAMPLE,
                "extraction_preset": "granite_vision_4_1",
                "input_channels": "image_and_text",
            },
            "does not accept a text",
        ),
        (
            {"target": NATIVE, "extraction_custom_config": {}},
            "Custom extraction configuration",
        ),
    ],
)
async def test_incompatible_requests_fail_before_queue(
    extraction_app, options, message
):
    app, orchestrator = extraction_app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/extract/source/async",
            headers={"X-Api-Key": "stage10-key"},
            json={
                "options": options,
                "sources": [{"kind": "http", "url": "https://example.com/test.pdf"}],
            },
        )
    assert response.status_code == 422, response.text
    assert message in response.text
    orchestrator.enqueue.assert_not_awaited()


@pytest.mark.parametrize(
    "preset, target, channels",
    [
        ("nuextract_2b", NATIVE, "text"),
        ("nuextract_3", {"output_schema": SCHEMA}, "image_and_text"),
        ("granite_vision_4_1", EXAMPLE, "image"),
        ("granite_vision_4_1", {"output_schema": SCHEMA}, "image"),
        ("lift", {"output_schema": SCHEMA, **EXAMPLE}, "text"),
    ],
)
async def test_valid_targets_forward_unchanged_and_isolated(
    extraction_app, preset, target, channels
):
    app, orchestrator = extraction_app
    payload = {
        "options": {
            "target": deepcopy(target),
            "extraction_preset": preset,
            "input_channels": channels,
            "page_range": [2, 5],
        },
        "sources": [{"kind": "http", "url": "https://example.com/test.pdf"}],
        "target": {"kind": "inbody"},
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for instructions in ("First request.", "Second request."):
            payload["options"]["target"]["instructions"] = instructions
            response = await client.post(
                "/v1/extract/source/async",
                headers={
                    "X-Api-Key": "stage10-key",
                    docling_serve_settings.eng_ray_tenant_id_header: "tenant-a",
                },
                json=payload,
            )
            assert response.status_code == 200, response.text
            forwarded = orchestrator.enqueue.await_args.kwargs
            assert (
                forwarded["extract_options"].target.model_dump(
                    mode="json", exclude_none=True
                )
                == payload["options"]["target"]
            )
            assert forwarded["extract_options"].page_range == (2, 5)
            assert forwarded["metadata"] == {"tenant_id": "tenant-a"}
            assert forwarded["targets"][0].kind == "inbody"
            assert str(forwarded["sources"][0].url) == "https://example.com/test.pdf"
            assert forwarded["callbacks"] == []
    first, second = [
        call.kwargs["extract_options"] for call in orchestrator.enqueue.await_args_list
    ]
    assert first.target.instructions == "First request."
    assert second.target.instructions == "Second request."


@pytest.mark.parametrize(
    "engine, mode, schema, message",
    [
        ("api", "schema_constrained", SCHEMA, None),
        ("api", "schema_constrained", None, "requires an output schema"),
        (
            "api",
            "schema_constrained",
            {
                "type": "object",
                "properties": {"total": {"type": "number"}},
                "dependentRequired": {"total": ["other"]},
            },
            "unsupported vLLM",
        ),
        ("api_ollama", "schema_constrained", SCHEMA, "vLLM API engine"),
    ],
)
async def test_custom_decoder_mode_preflight(
    monkeypatch, engine, mode, schema, message
):
    from docling.datamodel.extraction_options import ExtractionVlmOptions

    monkeypatch.setattr(docling_serve_settings, "eng_kind", AsyncEngine.LOCAL)
    monkeypatch.setattr(docling_serve_settings, "enable_remote_services", True)
    monkeypatch.setattr(docling_serve_settings, "allow_custom_extraction_config", True)
    custom = ExtractionVlmOptions.from_preset("nuextract_2b").model_dump(mode="json")
    custom["engine_options"] = {
        "engine_type": engine,
        "url": "http://offline.test/v1/chat/completions",
    }
    orchestrator = SimpleNamespace(
        enqueue=AsyncMock(
            return_value=Task(task_id="extract", task_type=TaskType.EXTRACT)
        ),
        get_queue_position=AsyncMock(return_value=0),
    )
    app = create_app()
    app.dependency_overrides[get_async_orchestrator] = lambda: orchestrator
    monkeypatch.setattr(docling_serve_settings, "eng_kind", AsyncEngine.RAY)
    target = {**NATIVE, **({"output_schema": schema} if schema is not None else {})}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/extract/source/async",
            json={
                "options": {
                    "target": target,
                    "extraction_custom_config": custom,
                    "output_mode": mode,
                },
                "sources": [{"kind": "http", "url": "https://example.com/test.pdf"}],
            },
        )
    if message is not None:
        assert response.status_code == 422, response.text
        assert message in response.text
        orchestrator.enqueue.assert_not_awaited()
    else:
        assert response.status_code == 200, response.text
        assert (
            orchestrator.enqueue.await_args.kwargs["extract_options"].output_mode
            == mode
        )


async def test_extraction_requires_authentication_before_queue(extraction_app):
    app, orchestrator = extraction_app
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/extract/source/async",
            json={
                "options": {"target": NATIVE},
                "sources": [{"kind": "http", "url": "https://example.com/test.pdf"}],
            },
        )
    assert response.status_code == 401
    orchestrator.enqueue.assert_not_awaited()


@pytest.mark.parametrize(
    "result_kind",
    ["ExtractionResult", "PresignedArtifactResult", "RemoteTargetResult", "failure"],
)
async def test_extraction_result_unions_preserve_tenant_and_durable_shape(
    monkeypatch, result_kind
):
    monkeypatch.setattr(docling_serve_settings, "single_use_results", False)
    task = Task(
        task_id="extract",
        task_type=TaskType.EXTRACT,
        task_status="failure" if result_kind == "failure" else "success",
        metadata={"tenant_id": "tenant-a"},
    )
    if result_kind == "failure":
        outcome = StoredFailureOutcome(
            failure=PublicFailureInfo(
                category="internal",
                message="Extraction failed.",
                retryable=False,
                phase="execution",
            )
        )
    else:
        result = {"kind": result_kind}
        if result_kind == "ExtractionResult":
            result["documents"] = [
                {
                    "source_index": 0,
                    "source_uri": "s3://bucket/a.md",
                    "filename": "a.md",
                    "status": "success",
                    "items": [
                        {
                            "scope": {"kind": "document"},
                            "extracted_data": {"total": 5},
                            "raw_text": '{"total":5}',
                            "validation_status": "passed",
                            "usage": {"total_tokens": 9},
                        }
                    ],
                },
                {
                    "source_index": 0,
                    "source_uri": "s3://bucket/b.pdf",
                    "filename": "b.pdf",
                    "status": "partial_success",
                    "items": [
                        {
                            "scope": {"kind": "page", "page_no": 5},
                            "raw_text": "invalid",
                            "errors": ["schema mismatch"],
                            "validation_status": "failed",
                        },
                        {
                            "scope": {"kind": "page", "page_no": 6},
                            "validation_status": "not_run",
                        },
                    ],
                },
            ]
        elif result_kind == "PresignedArtifactResult":
            result["documents"] = [
                {
                    "source_index": 0,
                    "source_uri": "s3://bucket/a.md",
                    "filename": "a.md",
                    "status": "success",
                    "artifacts": [
                        {
                            "artifact_type": "json",
                            "mime_type": "application/json",
                            "uri": "https://storage.test/result.json",
                        }
                    ],
                }
            ]
        durable = DoclingTaskResult.model_validate(
            {
                "result": result,
                "processing_time": 1,
                "num_converted": 2,
                "num_succeeded": 1,
                "num_partially_succeeded": 1,
                "num_failed": 0,
            }
        )
        outcome = StoredSuccessOutcome.model_validate_json(
            StoredSuccessOutcome(result=durable).model_dump_json()
        )
    orchestrator = SimpleNamespace(
        task_status=AsyncMock(return_value=task),
        task_outcome=AsyncMock(return_value=outcome),
        get_queue_position=AsyncMock(return_value=0),
    )
    app = create_app()
    app.dependency_overrides[get_async_orchestrator] = lambda: orchestrator
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        for tenant in ("tenant-b", None):
            headers = (
                {docling_serve_settings.eng_ray_tenant_id_header: tenant}
                if tenant
                else {}
            )
            response = await client.get("/v1/result/extract", headers=headers)
            assert response.status_code == 404
            orchestrator.task_outcome.assert_not_awaited()
        headers = {docling_serve_settings.eng_ray_tenant_id_header: "tenant-a"}
        response = await client.get("/v1/result/extract", headers=headers)
        poll = await client.get("/v1/status/poll/extract", headers=headers)
        assert poll.status_code == 200
        assert poll.json()["task_type"] == "extract"
    assert response.status_code == 200, response.text
    body = response.json()
    if result_kind == "failure":
        assert body["kind"] == "TaskFailureResult"
        assert body["failure"]["message"] == "Extraction failed."
    else:
        assert body["num_partially_succeeded"] == 1
        if result_kind == "ExtractionResult":
            assert (
                body["documents"] == durable.result.model_dump(mode="json")["documents"]
            )
            assert body["documents"][0]["items"][0]["scope"] == {"kind": "document"}
            assert body["documents"][1]["items"][0]["scope"]["page_no"] == 5
            assert "pages" not in body["documents"][0]
            assert "input" not in body["documents"][0]
        elif result_kind == "PresignedArtifactResult":
            assert (
                body["documents"][0]["artifacts"][0]["uri"]
                == "https://storage.test/result.json"
            )
        else:
            assert "documents" not in body


@pytest.mark.parametrize(
    "engine, params, message",
    [
        ("api_lmstudio", {}, "chat_template_kwargs require"),
        ("api_ollama", {}, "chat_template_kwargs require"),
        ("api", {"messages": []}, "request-owned"),
        ("api", {"chat_template_kwargs": {"template": "static"}}, "request-owned"),
        (
            "api",
            {"chat_template_kwargs": {"mode": "unstructured"}},
            "requires structured mode",
        ),
    ],
)
async def test_api_transport_incompatibility_fails_before_queue(
    monkeypatch, engine, params, message
):
    from docling.datamodel.extraction_options import ExtractionVlmOptions

    monkeypatch.setattr(docling_serve_settings, "eng_kind", AsyncEngine.LOCAL)
    monkeypatch.setattr(docling_serve_settings, "enable_remote_services", True)
    monkeypatch.setattr(docling_serve_settings, "allow_custom_extraction_config", True)
    custom = ExtractionVlmOptions.from_preset("nuextract_2b").model_dump(mode="json")
    custom["engine_options"] = {"engine_type": engine, "params": params}
    orchestrator = SimpleNamespace(enqueue=AsyncMock())
    app = create_app()
    app.dependency_overrides[get_async_orchestrator] = lambda: orchestrator
    monkeypatch.setattr(docling_serve_settings, "eng_kind", AsyncEngine.RAY)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/extract/source/async",
            json={
                "options": {"target": NATIVE, "extraction_custom_config": custom},
                "sources": [{"kind": "http", "url": "https://example.com/test.pdf"}],
            },
        )
    assert response.status_code == 422, response.text
    assert message in response.text
    orchestrator.enqueue.assert_not_awaited()

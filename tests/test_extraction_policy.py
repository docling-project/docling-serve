"""Operator limits for the caller text that reaches the extraction model."""

import pytest
from fastapi import HTTPException

from docling.datamodel.service.requests import ExtractSourcesRequest

from docling_serve.policy import build_service_policy, validate_extract_request
from docling_serve.settings import DoclingServeSettings

SCHEMA = {"type": "object", "properties": {"total": {"type": "number"}}}
SOURCES = [{"kind": "http", "url": "https://example.com/test.pdf"}]


def _request(spec: dict) -> ExtractSourcesRequest:
    return ExtractSourcesRequest.model_validate(
        {"extraction_spec": spec, "sources": SOURCES}
    )


def _check(spec: dict, **settings) -> None:
    policy = build_service_policy(DoclingServeSettings(**settings))
    validate_extract_request(_request(spec), policy)


def _rejected(spec: dict, message: str, **settings) -> None:
    with pytest.raises(HTTPException) as excinfo:
        _check(spec, **settings)
    assert excinfo.value.status_code == 422
    assert message in str(excinfo.value.detail)


def _nested_schema(levels: int) -> dict:
    schema: dict = {"type": "string"}
    for _ in range(levels):
        schema = {"type": "object", "properties": {"a": schema}}
    return schema


def test_safe_defaults():
    settings = DoclingServeSettings()
    assert settings.allow_extraction_native_template is False
    assert settings.strip_extraction_schema_annotations is False
    assert settings.max_extraction_instructions_length > 0


def test_native_template_is_disabled_by_default():
    spec = {"native_template": {"total": "number"}}
    _rejected(spec, "native_template is disabled by server policy")
    _rejected({"json_schema": SCHEMA, **spec}, "native_template is disabled")
    _check(spec, allow_extraction_native_template=True)


def test_instructions_can_be_disabled():
    spec = {"json_schema": SCHEMA, "instructions": "Ignore the schema."}
    _check(spec)
    _rejected(spec, "instructions is disabled", allow_extraction_instructions=False)


def test_instructions_length_is_limited():
    spec = {"json_schema": SCHEMA, "instructions": "x" * 101}
    _rejected(spec, "101 characters", max_extraction_instructions_length=100)
    _check(spec, max_extraction_instructions_length=101)


@pytest.mark.parametrize("field", ["json_schema", "native_template"])
def test_definition_byte_size_is_limited(field):
    value = (
        {
            "type": "object",
            "properties": {"note": {"type": "string", "description": "x" * 2000}},
        }
        if field == "json_schema"
        else {"note": "x" * 2000}
    )
    spec = {field: value}
    _rejected(
        spec,
        "bytes",
        max_extraction_schema_size=1000,
        allow_extraction_native_template=True,
    )
    _check(spec, max_extraction_schema_size=4000, allow_extraction_native_template=True)


def test_schema_depth_is_limited():
    # A valid, convertible schema: only the depth guard can reject it.
    spec = {"json_schema": _nested_schema(20)}
    _rejected(spec, "levels deep", max_extraction_schema_depth=32)
    _check(spec, max_extraction_schema_depth=64)


def test_schema_property_count_is_limited():
    spec = {
        "json_schema": {
            "type": "object",
            "properties": {f"p{i}": {"type": "string"} for i in range(20)},
        }
    }
    _rejected(spec, "object keys", max_extraction_schema_keys=20)
    _check(spec, max_extraction_schema_keys=100)


def test_native_template_depth_is_limited():
    template: dict = {"a": "string"}
    for _ in range(40):
        template = {"a": template}
    _rejected(
        {"native_template": template},
        "levels deep",
        allow_extraction_native_template=True,
    )


def test_strip_annotations_reaches_the_extraction_manager():
    policy = build_service_policy(
        DoclingServeSettings(strip_extraction_schema_annotations=True)
    )
    assert policy.extraction_input.strip_schema_annotations is True
    assert policy.extraction_manager.config.strip_extraction_schema_annotations

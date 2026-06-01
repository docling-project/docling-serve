import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from docling.datamodel.service.options import ConvertDocumentsOptions
from docling.datamodel.service.requests import (
    BatchConvertSourcesRequest,
    ConvertSourcesRequest,
    HttpSourceRequest,
    S3SourceRequest,
)
from docling.datamodel.service.targets import InBodyTarget, PresignedUrlTarget, S3Target

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions
from docling_serve.policy import (
    build_service_policy,
    normalize_batch_convert_request,
    normalize_convert_options,
    normalize_convert_request,
    validate_batch_convert_request,
    validate_convert_options,
    validate_convert_request,
)
from docling_serve.settings import DoclingServeSettings


def test_convert_options_shim_points_to_shared_type():
    assert ConvertDocumentsRequestOptions is ConvertDocumentsOptions


def test_page_range_serializes_to_json_array():
    options = ConvertDocumentsOptions(page_range=(2, 5))

    assert options.model_dump(mode="json")["page_range"] == [2, 5]


def test_normalize_convert_options_sets_default_timeout():
    policy = build_service_policy(DoclingServeSettings())

    normalized = normalize_convert_options(ConvertDocumentsOptions(), policy)

    assert normalized.document_timeout == policy.max_document_timeout


def test_validate_convert_options_rejects_timeout_above_policy():
    policy = build_service_policy(DoclingServeSettings(max_document_timeout=10))

    with pytest.raises(HTTPException, match="document_timeout exceeds"):
        validate_convert_options(ConvertDocumentsOptions(document_timeout=11), policy)


def test_convert_sources_request_rejects_s3_inputs_at_model_layer():
    with pytest.raises(ValidationError):
        ConvertSourcesRequest(
            options=ConvertDocumentsOptions(),
            sources=[
                S3SourceRequest(
                    endpoint="s3.example.com",
                    access_key="key",
                    secret_key="secret",
                    bucket="bucket",
                )
            ],
            target=S3Target(
                endpoint="s3.example.com",
                access_key="key",
                secret_key="secret",
                bucket="bucket",
            ),
        )


def test_normalize_convert_request_preserves_sources_and_target():
    policy = build_service_policy(DoclingServeSettings())
    request = ConvertSourcesRequest(
        options=ConvertDocumentsOptions(document_timeout=None),
        sources=[HttpSourceRequest(url="https://example.com/test.pdf", headers={})],
        target=InBodyTarget(),
    )

    normalized = normalize_convert_request(request, policy)

    assert normalized.sources == request.sources
    assert normalized.target == request.target
    assert normalized.options.document_timeout == policy.max_document_timeout


def test_normalize_convert_request_works_for_convert_sources_request():
    policy = build_service_policy(DoclingServeSettings())
    request = ConvertSourcesRequest(
        options=ConvertDocumentsOptions(document_timeout=None),
        sources=[HttpSourceRequest(url="https://example.com/test.pdf", headers={})],
        target=InBodyTarget(),
    )

    normalized = normalize_convert_request(request, policy)

    assert isinstance(normalized, ConvertSourcesRequest)
    assert normalized.sources == request.sources
    assert normalized.options.document_timeout == policy.max_document_timeout


def test_validate_convert_request_rejects_presigned_url_when_storage_disabled():
    policy = build_service_policy(DoclingServeSettings(artifact_storage_enabled=False))
    request = ConvertSourcesRequest(
        sources=[HttpSourceRequest(url="https://example.com/test.pdf", headers={})],
        target=PresignedUrlTarget(),
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_convert_request(request, policy)

    assert exc_info.value.status_code == 422
    assert "artifact storage" in exc_info.value.detail.lower()


def test_validate_convert_request_rejects_too_many_sources():
    policy = build_service_policy(DoclingServeSettings(max_sources_per_request=2))
    request = ConvertSourcesRequest(
        sources=[
            HttpSourceRequest(url="https://example.com/a.pdf", headers={}),
            HttpSourceRequest(url="https://example.com/b.pdf", headers={}),
            HttpSourceRequest(url="https://example.com/c.pdf", headers={}),
        ],
        target=InBodyTarget(),
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_convert_request(request, policy)

    assert exc_info.value.status_code == 422
    assert "Too many sources" in exc_info.value.detail


def test_validate_convert_request_allows_presigned_url_when_storage_enabled():
    policy = build_service_policy(DoclingServeSettings(artifact_storage_enabled=True))
    request = ConvertSourcesRequest(
        sources=[HttpSourceRequest(url="https://example.com/test.pdf", headers={})],
        target=PresignedUrlTarget(),
    )

    validate_convert_request(request, policy)


def test_validate_batch_convert_request_rejects_s3_source_with_presigned_target():
    policy = build_service_policy(DoclingServeSettings(artifact_storage_enabled=True))
    request = BatchConvertSourcesRequest(
        sources=[
            S3SourceRequest(
                endpoint="s3.example.com",
                access_key="key",
                secret_key="secret",
                bucket="bucket",
            )
        ],
        target=PresignedUrlTarget(),
    )

    with pytest.raises(HTTPException) as exc_info:
        validate_batch_convert_request(request, policy)

    assert exc_info.value.status_code == 422
    assert "S3 sources require an S3 target" in exc_info.value.detail


def test_validate_batch_convert_request_allows_s3_source_with_s3_target_without_kfp():
    policy = build_service_policy(DoclingServeSettings())
    request = BatchConvertSourcesRequest(
        sources=[
            S3SourceRequest(
                endpoint="s3.example.com",
                access_key="key",
                secret_key="secret",
                bucket="bucket",
            )
        ],
        target=S3Target(
            endpoint="s3.example.com",
            access_key="key",
            secret_key="secret",
            bucket="converted",
        ),
    )

    validate_batch_convert_request(request, policy)


def test_validate_batch_convert_request_allows_http_source_with_s3_target():
    policy = build_service_policy(DoclingServeSettings())
    request = BatchConvertSourcesRequest(
        sources=[HttpSourceRequest(url="https://example.com/test.pdf", headers={})],
        target=S3Target(
            endpoint="s3.example.com",
            access_key="key",
            secret_key="secret",
            bucket="converted",
        ),
    )

    validate_batch_convert_request(request, policy)


def test_normalize_batch_convert_request_sets_default_timeout():
    policy = build_service_policy(DoclingServeSettings())
    request = BatchConvertSourcesRequest(
        options=ConvertDocumentsOptions(document_timeout=None),
        sources=[HttpSourceRequest(url="https://example.com/test.pdf", headers={})],
        target=PresignedUrlTarget(),
    )

    normalized = normalize_batch_convert_request(request, policy)

    assert isinstance(normalized, BatchConvertSourcesRequest)
    assert normalized.options.document_timeout == policy.max_document_timeout

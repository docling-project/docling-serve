from __future__ import annotations

from dataclasses import dataclass
from typing import TypeVar

from fastapi import HTTPException, status

from docling.datamodel.service.options import ConvertDocumentsOptions
from docling.datamodel.service.requests import (
    BaseChunkDocumentsRequest,
    ConvertDocumentsRequest,
    ConvertSourcesRequest,
    S3SourceRequest,
)
from docling.datamodel.service.targets import PresignedUrlTarget, S3Target
from docling.models.factories import get_ocr_factory

from docling_serve.settings import AsyncEngine, DoclingServeSettings

TConvertRequest = TypeVar(
    "TConvertRequest", ConvertSourcesRequest, ConvertDocumentsRequest
)


@dataclass(frozen=True, slots=True)
class ServicePolicy:
    max_document_timeout: float
    allow_external_plugins: bool
    allowed_ocr_presets: frozenset[str]
    s3_enabled: bool
    callbacks_enabled: bool
    custom_vlm_enabled: bool
    artifact_storage_enabled: bool
    max_sources_per_request: int


def build_service_policy(settings: DoclingServeSettings) -> ServicePolicy:
    ocr_factory = get_ocr_factory(
        allow_external_plugins=settings.allow_external_plugins
    )
    registered_ocr_presets = {str(kind) for kind in ocr_factory.registered_kind}
    if settings.allowed_ocr_presets is None:
        allowed_ocr_presets = registered_ocr_presets
    else:
        allowed_ocr_presets = set(settings.allowed_ocr_presets) & registered_ocr_presets

    return ServicePolicy(
        max_document_timeout=settings.max_document_timeout,
        allow_external_plugins=settings.allow_external_plugins,
        allowed_ocr_presets=frozenset(allowed_ocr_presets),
        s3_enabled=settings.eng_kind == AsyncEngine.KFP,
        callbacks_enabled=True,
        custom_vlm_enabled=settings.allow_custom_vlm_config,
        artifact_storage_enabled=settings.artifact_storage_enabled,
        max_sources_per_request=settings.max_sources_per_request,
    )


def normalize_convert_options(
    options: ConvertDocumentsOptions, policy: ServicePolicy
) -> ConvertDocumentsOptions:
    if options.document_timeout is not None:
        return options
    return options.model_copy(
        update={"document_timeout": policy.max_document_timeout}, deep=True
    )


def normalize_convert_request(
    request: TConvertRequest, policy: ServicePolicy
) -> TConvertRequest:
    return request.model_copy(
        update={"options": normalize_convert_options(request.options, policy)},
        deep=True,
    )


def validate_convert_options(
    options: ConvertDocumentsOptions, policy: ServicePolicy
) -> None:
    if options.document_timeout is not None:
        if options.document_timeout <= 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="document_timeout must be greater than 0.",
            )
        if options.document_timeout > policy.max_document_timeout:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "document_timeout exceeds the configured maximum "
                    f"of {policy.max_document_timeout} seconds."
                ),
            )

    if options.ocr_preset not in policy.allowed_ocr_presets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"ocr_preset '{options.ocr_preset}' is not allowed. "
                f"Allowed values: {sorted(policy.allowed_ocr_presets)}."
            ),
        )

    if options.vlm_pipeline_custom_config and not policy.custom_vlm_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Custom VLM configuration is disabled by server policy.",
        )


def validate_convert_request(
    request: ConvertSourcesRequest | ConvertDocumentsRequest, policy: ServicePolicy
) -> None:
    validate_convert_options(request.options, policy)

    if request.callbacks and not policy.callbacks_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Callbacks are disabled by server policy.",
        )

    if isinstance(request, ConvertSourcesRequest):
        if len(request.sources) > policy.max_sources_per_request:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"Too many sources: {len(request.sources)} exceeds the "
                    f"maximum of {policy.max_sources_per_request}."
                ),
            )

    if isinstance(request.target, PresignedUrlTarget):
        if not policy.artifact_storage_enabled:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Presigned URL target requires artifact storage to be configured "
                    "and enabled on the server."
                ),
            )

    has_s3_source = any(
        isinstance(source, S3SourceRequest) for source in request.sources
    )
    has_s3_target = isinstance(request.target, S3Target)

    if has_s3_source:
        if not policy.s3_enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail='source kind "s3" requires engine kind "KFP".',
            )
        if not has_s3_target:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail='source kind "s3" requires target kind "s3".',
            )

    if has_s3_target and not has_s3_source:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail='target kind "s3" requires source kind "s3".',
        )


def validate_chunk_request(
    request: BaseChunkDocumentsRequest, policy: ServicePolicy
) -> None:
    validate_convert_options(request.convert_options, policy)

    if request.callbacks and not policy.callbacks_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Callbacks are disabled by server policy.",
        )

    if isinstance(request.target, PresignedUrlTarget):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="presigned_url target is not supported for chunk endpoints.",
        )

    has_s3_source = any(
        isinstance(source, S3SourceRequest) for source in request.sources
    )
    has_s3_target = isinstance(request.target, S3Target)

    if has_s3_source:
        if not policy.s3_enabled:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail='source kind "s3" requires engine kind "KFP".',
            )
        if not has_s3_target:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail='source kind "s3" requires target kind "s3".',
            )

    if has_s3_target and not has_s3_source:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail='target kind "s3" requires source kind "s3".',
        )

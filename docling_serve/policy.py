from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeVar

from fastapi import HTTPException, status

from docling.datamodel.service.options import ConvertDocumentsOptions
from docling.datamodel.service.requests import (
    BaseChunkDocumentsRequest,
    BatchConvertSourcesRequest,
    ConvertSourcesRequest,
    S3SourceRequest,
    TargetRequest,
)
from docling.datamodel.service.targets import (
    InBodyTarget,
    PresignedUrlTarget,
    S3Target,
)
from docling.models.factories import get_ocr_factory
from docling_core.types.doc import ImageRefMode

from docling_serve.settings import DoclingServeSettings

ALL_TARGET_TYPES = frozenset({"inbody", "zip", "s3", "put", "presigned_url"})
_ConvertRequestT = TypeVar(
    "_ConvertRequestT", ConvertSourcesRequest, BatchConvertSourcesRequest
)


@dataclass(frozen=True, slots=True)
class ServicePolicy:
    max_document_timeout: float
    max_images_scale: float
    allow_external_plugins: bool
    allowed_ocr_presets: frozenset[str]
    allowed_target_types: frozenset[str]
    callbacks_enabled: bool
    custom_vlm_enabled: bool
    artifact_storage_enabled: bool
    max_sources_per_request: int
    allowed_image_export_modes: frozenset[str]


def build_service_policy(settings: DoclingServeSettings) -> ServicePolicy:
    ocr_factory = get_ocr_factory(
        allow_external_plugins=settings.allow_external_plugins
    )
    registered_ocr_presets = {str(kind) for kind in ocr_factory.registered_kind}
    if settings.allowed_ocr_presets is None:
        allowed_ocr_presets = registered_ocr_presets
    else:
        allowed_ocr_presets = set(settings.allowed_ocr_presets) & registered_ocr_presets
    if settings.allowed_target_types is None:
        allowed_target_types = ALL_TARGET_TYPES
    else:
        allowed_target_types = (
            frozenset(settings.allowed_target_types) & ALL_TARGET_TYPES
        )

    # Determine allowed image export modes
    if settings.allowed_image_export_modes is None:
        # All modes allowed by default
        allowed_image_export_modes = {"placeholder", "referenced", "embedded"}
    else:
        # Validate that only known modes are specified
        valid_modes = {"placeholder", "referenced", "embedded"}
        allowed_image_export_modes = (
            set(settings.allowed_image_export_modes) & valid_modes
        )

    return ServicePolicy(
        max_document_timeout=settings.max_document_timeout,
        max_images_scale=settings.max_images_scale,
        allow_external_plugins=settings.allow_external_plugins,
        allowed_ocr_presets=frozenset(allowed_ocr_presets),
        allowed_target_types=allowed_target_types,
        callbacks_enabled=True,
        custom_vlm_enabled=settings.allow_custom_vlm_config,
        artifact_storage_enabled=settings.artifact_storage_enabled,
        max_sources_per_request=settings.max_sources_per_request,
        allowed_image_export_modes=frozenset(allowed_image_export_modes),
    )


def resolve_default_target(policy: ServicePolicy) -> TargetRequest:
    """Pick a target for requests that omit one.

    Clients drop fields left at their model default, so an omitted ``target``
    arrives carrying whatever default the request model happens to declare —
    which may not be a target this deployment allows, falsely tripping the
    policy checks with a 422. Resolve the omitted case to something the
    deployment actually supports instead: prefer presigned whenever artifact
    storage is enabled (keeps result payloads out of the response body), and
    otherwise fall back to inbody. If inbody is not allowed either the request
    is misconfigured; return it anyway and let validation surface a clear error.
    """
    if (
        "presigned_url" in policy.allowed_target_types
        and policy.artifact_storage_enabled
    ):
        return PresignedUrlTarget()
    return InBodyTarget()


def normalize_convert_options(
    options: ConvertDocumentsOptions, policy: ServicePolicy
) -> ConvertDocumentsOptions:
    updates: dict[str, Any] = {}

    if options.document_timeout is None:
        updates["document_timeout"] = policy.max_document_timeout

    # Placeholder export mode discards all image data, so generating images would
    # be wasted work. Coerce the include_* flags off rather than rejecting the
    # request: include_images defaults to True, so a 422 here would fail requests
    # purely on a default the caller never set.
    if options.image_export_mode == ImageRefMode.PLACEHOLDER:
        if options.include_images:
            updates["include_images"] = False
        if options.include_page_images:
            updates["include_page_images"] = False

    if not updates:
        return options
    return options.model_copy(update=updates, deep=True)


def normalize_request(
    request: _ConvertRequestT, policy: ServicePolicy
) -> _ConvertRequestT:
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
    if options.images_scale > policy.max_images_scale:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "images_scale exceeds the configured maximum "
                f"of {policy.max_images_scale}."
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

    image_export_mode = getattr(
        options.image_export_mode, "value", options.image_export_mode
    )
    if image_export_mode not in policy.allowed_image_export_modes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"image_export_mode '{image_export_mode}' is not allowed. "
                f"Allowed values: {sorted(policy.allowed_image_export_modes)}."
            ),
        )

    if options.vlm_pipeline_custom_config and not policy.custom_vlm_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Custom VLM configuration is disabled by server policy.",
        )


def validate_target_kind(target_kind: str, policy: ServicePolicy) -> None:
    if target_kind in policy.allowed_target_types:
        return

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=(
            f"target kind '{target_kind}' is not allowed. "
            f"Allowed values: {sorted(policy.allowed_target_types)}."
        ),
    )


def validate_convert_request(
    request: ConvertSourcesRequest, policy: ServicePolicy
) -> None:
    validate_convert_options(request.options, policy)
    validate_target_kind(request.target.kind, policy)

    if request.callbacks and not policy.callbacks_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Callbacks are disabled by server policy.",
        )

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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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


def validate_batch_convert_request(
    request: BatchConvertSourcesRequest, policy: ServicePolicy
) -> None:
    validate_convert_options(request.options, policy)

    if request.callbacks and not policy.callbacks_enabled:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Callbacks are disabled by server policy.",
        )

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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "Presigned URL target requires artifact storage to be configured "
                    "and enabled on the server."
                ),
            )

    has_s3_source = any(
        isinstance(source, S3SourceRequest) for source in request.sources
    )
    has_s3_target = isinstance(request.target, S3Target)

    # Batch endpoint intentionally allows S3 sources on the Ray engine; only the
    # S3 source -> S3 target pairing is enforced here.
    if has_s3_source and not has_s3_target:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="S3 sources require an S3 target on the batch endpoint.",
        )


def validate_chunk_request(
    request: BaseChunkDocumentsRequest, policy: ServicePolicy
) -> None:
    validate_convert_options(request.convert_options, policy)
    validate_target_kind(request.target.kind, policy)

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

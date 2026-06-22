"""Bridge between the shared service policy and gRPC requests.

The REST layer enforces ``docling_serve.policy`` on Pydantic request models.
gRPC builds sources/options/target separately (it never constructs a
``ConvertSourcesRequest``), so this module applies the same rules to those
parts. The option- and target-kind validators are reused directly from
``policy.py``; only the request-shape rules (source count, S3 pairing,
presigned-target restrictions) are mirrored here because they are expressed
against REST request models upstream. ``policy.py`` remains the source of
truth — when its rules change, this bridge must follow.
"""

from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from docling.datamodel.service.options import ConvertDocumentsOptions
from docling.datamodel.service.targets import PresignedUrlTarget
from docling_jobkit.datamodel.s3_coords import S3Coordinates
from docling_jobkit.datamodel.task_targets import S3Target

from docling_serve.policy import (
    ServicePolicy,
    normalize_convert_options,
    validate_convert_options,
    validate_target_kind,
)


def normalize_options(
    options: ConvertDocumentsOptions, policy: ServicePolicy
) -> ConvertDocumentsOptions:
    """Apply policy defaults (e.g. document_timeout) like the REST layer does."""
    return normalize_convert_options(options, policy)


def validate_request(
    sources: list,
    options: ConvertDocumentsOptions,
    target,
    policy: ServicePolicy,
    *,
    chunk: bool = False,
) -> Optional[str]:
    """Validate a gRPC request against the service policy.

    Returns an error detail string when the request violates policy,
    or None when it is allowed.
    """
    try:
        validate_convert_options(options, policy)
        validate_target_kind(target.kind, policy)
    except HTTPException as exc:
        return str(exc.detail)

    if len(sources) > policy.max_sources_per_request:
        return (
            f"Too many sources: {len(sources)} exceeds the "
            f"maximum of {policy.max_sources_per_request}."
        )

    if isinstance(target, PresignedUrlTarget):
        if chunk:
            return "presigned_url target is not supported for chunk endpoints."
        if not policy.artifact_storage_enabled:
            return (
                "Presigned URL target requires artifact storage to be configured "
                "and enabled on the server."
            )

    has_s3_source = any(isinstance(source, S3Coordinates) for source in sources)
    has_s3_target = isinstance(target, S3Target)

    if has_s3_source:
        if not policy.s3_enabled:
            return 'source kind "s3" requires engine kind "KFP".'
        if not has_s3_target:
            return 'source kind "s3" requires target kind "s3".'

    if has_s3_target and not has_s3_source:
        return 'target kind "s3" requires source kind "s3".'

    return None

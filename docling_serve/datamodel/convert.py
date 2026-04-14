"""Deprecated compatibility shim. Use `docling.datamodel.service.options` instead."""

from docling.datamodel.service.options import (
    ConvertDocumentsOptions as ConvertDocumentsRequestOptions,
)

__all__ = ["ConvertDocumentsRequestOptions"]

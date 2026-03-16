from __future__ import annotations

import warnings

from docling_core.proto import docling_document_to_proto as docling_document_to_proto
from docling_core.proto.gen.ai.docling.core.v1 import docling_document_pb2 as pb2

# Re-export for compatibility with existing code in docling-serve
__all__ = ["docling_document_to_proto", "pb2"]

# Re-export docling_document_pb2 so "from ai.docling.core.v1 import docling_document_pb2" works.
from docling_core.proto.gen.ai.docling.core.v1 import docling_document_pb2  # noqa: F401

__all__ = ["docling_document_pb2"]

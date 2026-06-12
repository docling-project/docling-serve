import base64
import os
from pathlib import Path

import grpc
import pytest
from docling_core.types.doc import DoclingDocument
from docling_core.proto.gen.ai.docling.core.v1 import docling_document_pb2 as pb2
from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2 as serve_pb2,
)
from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_pb2_grpc as serve_pb2_grpc,
)
from docling_serve.grpc.gen.ai.docling.serve.v1 import (
    docling_serve_types_pb2 as types_pb2,
)

# Path to the docling repo tests data
DOCLING_REPO_PDFS = Path("/work/docling_2953_grpc_server/tests/data/pdf/")

SKIP_E2E_TEST = ["skipped_1page.pdf", "skipped_2pages.pdf"]

@pytest.fixture(scope="module")
def grpc_stub():
    # 2 GB message limits
    options = [
        ("grpc.max_send_message_length", 2 * 1024 * 1024 * 1024 - 1),
        ("grpc.max_receive_message_length", 2 * 1024 * 1024 * 1024 - 1),
    ]
    channel = grpc.insecure_channel("localhost:50051", options=options)
    return serve_pb2_grpc.DoclingServeServiceStub(channel)

def get_pdf_paths():
    if not DOCLING_REPO_PDFS.exists():
        return []
    return sorted(
        f for f in DOCLING_REPO_PDFS.rglob("*.pdf") if f.name not in SKIP_E2E_TEST
    )

@pytest.mark.parametrize("pdf_path", get_pdf_paths(), ids=lambda p: p.name)
def test_convert_pdf_via_grpc(grpc_stub, pdf_path):
    print(f"Testing {pdf_path.name}")
    
    with open(pdf_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    
    source = types_pb2.Source(
        file=types_pb2.FileSource(base64_string=b64, filename=pdf_path.name)
    )
    
    # Enable table structure and cell matching to exercise more logic
    options = types_pb2.ConvertDocumentOptions(
        do_table_structure=True,
    )
    
    req = serve_pb2.ConvertSourceRequest(
        request=types_pb2.ConvertDocumentRequest(
            sources=[source],
            options=options
        )
    )
    
    resp = grpc_stub.ConvertSource(req)
    
    doc_proto = resp.response.document.doc
    assert doc_proto.schema_name == "DoclingDocument"
    assert doc_proto.name  # Should have a name
    
    # Basic sanity checks on the content
    assert len(doc_proto.pages) >= 1
    
    # We should have at least some text items for these test PDFs
    assert len(doc_proto.texts) >= 1
    
    print(f"  Result: {len(doc_proto.texts)} texts, {len(doc_proto.tables)} tables")

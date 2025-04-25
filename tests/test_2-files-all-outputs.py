import os

import httpx
import pytest
import pytest_asyncio
from pytest_check import check


@pytest_asyncio.fixture
async def async_client():
    async with httpx.AsyncClient(timeout=60.0) as client:
        yield client


@pytest.mark.asyncio
async def test_convert_file(async_client):
    """Test convert single file to all outputs"""
    url = "http://localhost:5001/v1alpha/convert/file"
    options = {
        "from_formats": [
            "docx",
            "pptx",
            "html",
            "image",
            "pdf",
            "asciidoc",
            "md",
            "xlsx",
        ],
        "to_formats": ["md", "json", "html", "text", "doctags"],
        "image_export_mode": "placeholder",
        "ocr": True,
        "force_ocr": False,
        "ocr_engine": "easyocr",
        "ocr_lang": ["en"],
        "pdf_backend": "dlparse_v2",
        "table_mode": "fast",
        "abort_on_error": False,
        "return_as_file": False,
    }

    current_dir = os.path.dirname(__file__)
    file_path = os.path.join(current_dir, "2206.01062v1.pdf")

    files = [
        ("files", ("2206.01062v1.pdf", open(file_path, "rb"), "application/pdf")),
        ("files", ("2408.09869v5.pdf", open(file_path, "rb"), "application/pdf")),
    ]

    response = await async_client.post(url, files=files, data=options)
    assert response.status_code == 200, "Response should be 200 OK"

    # Check for zip file attachment
    content_disposition = response.headers.get("content-disposition")

    with check:
        assert content_disposition is not None, (
            "Content-Disposition header should be present"
        )
    with check:
        assert "attachment" in content_disposition, "Response should be an attachment"
    with check:
        assert 'filename="converted_docs.zip"' in content_disposition, (
            "Attachment filename should be 'converted_docs.zip'"
        )

    content_type = response.headers.get("content-type")
    with check:
        assert content_type == "application/zip", (
            "Content-Type should be 'application/zip'"
        )

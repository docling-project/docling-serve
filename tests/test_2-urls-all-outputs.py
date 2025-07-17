import httpx
import pytest
import pytest_asyncio
from pytest_check import check


@pytest_asyncio.fixture
async def async_client():
    async with httpx.AsyncClient(timeout=60.0) as client:
        yield client


@pytest.mark.asyncio
async def test_convert_url(async_client):
    """Test convert URL to all outputs"""
    url = "http://localhost:5001/v1/convert/source"
    payload = {
        "options": {
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
        },
        "sources": [
            {"kind": "http", "url": "https://arxiv.org/pdf/2206.01062"},
            {"kind": "http", "url": "https://arxiv.org/pdf/2408.09869"},
        ],
        "target": {"kind": "zip"},
    }

    response = await async_client.post(url, json=payload)
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

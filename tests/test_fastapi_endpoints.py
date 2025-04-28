import asyncio
import json
import os

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from pytest_check import check

from docling_serve.app import create_app


@pytest.fixture(scope="session")
def event_loop():
    return asyncio.get_event_loop()


@pytest_asyncio.fixture(scope="session")
async def app():
    app = create_app()

    async with LifespanManager(app) as manager:
        print("Launching lifespan of app.")
        yield manager.app


@pytest_asyncio.fixture(scope="session")
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        print("Client is ready")
        yield client


@pytest.mark.asyncio
async def test_health(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_convert_file(client: AsyncClient):
    """Test convert single file to all outputs"""

    endpoint = "/v1alpha/convert/file"
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

    files = {
        "files": ("2206.01062v1.pdf", open(file_path, "rb"), "application/pdf"),
    }

    response = await client.post(endpoint, files=files, data=options)
    assert response.status_code == 200, "Response should be 200 OK"

    data = response.json()

    # Response content checks
    # Helper function to safely slice strings
    def safe_slice(value, length=100):
        if isinstance(value, str):
            return value[:length]
        return str(value)  # Convert non-string values to string for debug purposes

    # Document check
    check.is_in(
        "document",
        data,
        msg=f"Response should contain 'document' key. Received keys: {list(data.keys())}",
    )
    # MD check
    check.is_in(
        "md_content",
        data.get("document", {}),
        msg=f"Response should contain 'md_content' key. Received keys: {list(data.get('document', {}).keys())}",
    )
    if data.get("document", {}).get("md_content") is not None:
        check.is_in(
            "## DocLayNet: ",
            data["document"]["md_content"],
            msg=f"Markdown document should contain 'DocLayNet: '. Received: {safe_slice(data['document']['md_content'])}",
        )
    # JSON check
    check.is_in(
        "json_content",
        data.get("document", {}),
        msg=f"Response should contain 'json_content' key. Received keys: {list(data.get('document', {}).keys())}",
    )
    if data.get("document", {}).get("json_content") is not None:
        check.is_in(
            '{"schema_name": "DoclingDocument"',
            json.dumps(data["document"]["json_content"]),
            msg=f'JSON document should contain \'{{\\n  "schema_name": "DoclingDocument\'". Received: {safe_slice(data["document"]["json_content"])}',
        )
    # HTML check
    check.is_in(
        "html_content",
        data.get("document", {}),
        msg=f"Response should contain 'html_content' key. Received keys: {list(data.get('document', {}).keys())}",
    )
    if data.get("document", {}).get("html_content") is not None:
        check.is_in(
            "<!DOCTYPE html>\n<html>\n<head>",
            data["document"]["html_content"],
            msg=f"HTML document should contain '<!DOCTYPE html>\n<html>\n<head>'. Received: {safe_slice(data['document']['html_content'])}",
        )
    # Text check
    check.is_in(
        "text_content",
        data.get("document", {}),
        msg=f"Response should contain 'text_content' key. Received keys: {list(data.get('document', {}).keys())}",
    )
    if data.get("document", {}).get("text_content") is not None:
        check.is_in(
            "DocLayNet: A Large Human-Annotated Dataset",
            data["document"]["text_content"],
            msg=f"Text document should contain 'DocLayNet: A Large Human-Annotated Dataset'. Received: {safe_slice(data['document']['text_content'])}",
        )
    # DocTags check
    check.is_in(
        "doctags_content",
        data.get("document", {}),
        msg=f"Response should contain 'doctags_content' key. Received keys: {list(data.get('document', {}).keys())}",
    )
    if data.get("document", {}).get("doctags_content") is not None:
        check.is_in(
            "<doctag><page_header>",
            data["document"]["doctags_content"],
            msg=f"DocTags document should contain '<doctag><page_header>'. Received: {safe_slice(data['document']['doctags_content'])}",
        )

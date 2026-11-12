import os

import httpx
import pytest
import pytest_asyncio

from docling_serve.settings import docling_serve_settings


@pytest_asyncio.fixture
async def async_client():
    headers = {}
    if docling_serve_settings.api_key:
        headers["X-Api-Key"] = docling_serve_settings.api_key
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
        yield client


@pytest.mark.asyncio
async def test_convert_oxr_file(async_client):
    """Test convert a single saved OXR parse result"""
    url = "http://localhost:5001/v1/convert/file"
    options = {
        "from_formats": ["oxr"],
        "to_formats": ["md"],
        "abort_on_error": False,
    }

    current_dir = os.path.dirname(__file__)
    file_path = os.path.join(current_dir, "real_code_and_formula.oxr.json")
    with open(file_path, "rb") as source:
        files = {
            "files": (
                "real_code_and_formula.oxr.json",
                source,
                "application/json",
            ),
        }
        response = await async_client.post(url, files=files, data=options)

    assert response.status_code == 200, response.text
    data = response.json()
    document = data.get("document")
    assert document is not None, f"Response keys: {list(data.keys())}"
    markdown = document.get("md_content")
    assert markdown is not None, f"Document keys: {list(document.keys())}"
    assert "# JavaScript Code Example" in markdown
    assert "a^{2}+8=12" in markdown

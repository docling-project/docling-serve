import base64
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from websockets.sync.client import connect


@pytest_asyncio.fixture
async def async_client():
    async with httpx.AsyncClient(timeout=60.0) as client:
        yield client


@pytest.mark.asyncio
async def test_convert_url(async_client: httpx.AsyncClient):
    """Test convert URL to all outputs"""

    doc_filename = Path("tests/2408.09869v5.pdf")
    encoded_doc = base64.b64encode(doc_filename.read_bytes()).decode()

    base_url = "http://localhost:5001/v1"
    payload = {
        "options": {
            "to_formats": ["md", "json"],
            "image_export_mode": "placeholder",
            "ocr": True,
            "abort_on_error": False,
            # "do_picture_description": True,
            # "picture_description_api": {
            #     "url": "http://localhost:11434/v1/chat/completions",
            #     "params": {
            #         "model": "granite3.2-vision:2b",
            #     }
            # },
            # "picture_description_local": {
            #     "repo_id": "HuggingFaceTB/SmolVLM-256M-Instruct",
            # },
        },
        # "sources": [{"kind": "http", "url": "https://arxiv.org/pdf/2501.17887"}],
        "sources": [
            {
                "kind": "file",
                "base64_string": encoded_doc,
                "filename": doc_filename.name,
            }
        ],
    }
    # print(json.dumps(payload, indent=2))

    for n in range(5):
        response = await async_client.post(
            f"{base_url}/convert/source/async", json=payload
        )
        assert response.status_code == 200, "Response should be 200 OK"

    task = response.json()

    uri = f"ws://localhost:5001/v1/status/ws/{task['task_id']}"
    with connect(uri) as websocket:
        for message in websocket:
            print(message)

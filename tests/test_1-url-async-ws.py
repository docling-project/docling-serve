import base64
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from websockets.sync.client import connect

from docling_serve.settings import docling_serve_settings


@pytest_asyncio.fixture
async def async_client():
    headers = {}
    if docling_serve_settings.api_key:
        headers["X-Api-Key"] = docling_serve_settings.api_key
    async with httpx.AsyncClient(timeout=60.0, headers=headers) as client:
        yield client


@pytest.mark.asyncio
async def test_convert_url(async_client: httpx.AsyncClient):
    """Test convert URL to all outputs"""
    headers = {}
    if docling_serve_settings.api_key:
        headers["X-Api-Key"] = docling_serve_settings.api_key

    doc_filename = Path("tests/2408.09869v5.pdf")
    encoded_doc = base64.b64encode(doc_filename.read_bytes()).decode()

    base_url = "http://localhost:5001/v1"
    payload = {
        "options": {
            "to_formats": ["md", "json"],
            "image_export_mode": "placeholder",
            "ocr": True,
            "abort_on_error": False,
            # "layout_custom_config": {
            #     "kind": "layout_object_detection",
            #     "engine_options": {
            #         "engine_type": "onnxruntime",
            #     },
            # },
            # "table_structure_custom_config": {
            #     "kind": "table_structure_object_detection",
            #     "engine_options": {
            #         "engine_type": "onnxruntime",
            #         # "engine_type": "transformers",
            #     },
            # },
            "do_picture_description": False,
            "picture_description_preset": "granite_vision",
            # "picture_description_preset": "default",
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

    uri = f"ws://localhost:5001/v1/status/ws/{task['task_id']}?api_key={docling_serve_settings.api_key}"
    with connect(uri) as websocket:
        for message in websocket:
            print(message)

    result_resp = await async_client.get(f"{base_url}/result/{task['task_id']}")
    assert result_resp.status_code == 200, "Response should be 200 OK"
    result = result_resp.json()
    print(f"{result['processing_time']=}")
    assert result["processing_time"] > 1.0

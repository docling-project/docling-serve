import json
import random
import time

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
async def test_convert_url(async_client):
    """Test convert URL to all outputs"""

    example_docs = [
        "https://arxiv.org/pdf/2411.19710",
        "https://arxiv.org/pdf/2501.17887",
        "https://www.nature.com/articles/s41467-024-50779-y.pdf",
        "https://arxiv.org/pdf/2306.12802",
        "https://arxiv.org/pdf/2311.18481",
    ]

    base_url = "http://localhost:5001/v1"
    payload = {
        "options": {
            "to_formats": ["md", "json"],
            "image_export_mode": "placeholder",
            "ocr": True,
            "abort_on_error": False,
        },
        "sources": [{"kind": "http", "url": random.choice(example_docs)}],
    }
    print(json.dumps(payload, indent=2))

    for n in range(3):
        response = await async_client.post(
            f"{base_url}/convert/source/async", json=payload
        )
        assert response.status_code == 200, "Response should be 200 OK"

    task = response.json()

    print(json.dumps(task, indent=2))

    while task["task_status"] not in ("success", "failure"):
        response = await async_client.get(f"{base_url}/status/poll/{task['task_id']}")
        assert response.status_code == 200, "Response should be 200 OK"
        task = response.json()
        print(f"{task['task_status']=}")
        print(f"{task['task_position']=}")

        time.sleep(2)

    assert task["task_status"] == "success"


@pytest.mark.asyncio
@pytest.mark.parametrize("include_converted_doc", [False, True])
async def test_chunk_url(async_client, include_converted_doc: bool):
    """Test chunk URL"""

    example_docs = [
        "https://arxiv.org/pdf/2311.18481",
    ]

    base_url = "http://localhost:5001/v1"
    payload = {
        "sources": [{"kind": "http", "url": random.choice(example_docs)}],
        "include_converted_doc": include_converted_doc,
    }

    response = await async_client.post(
        f"{base_url}/chunk/hybrid/source/async", json=payload
    )
    assert response.status_code == 200, "Response should be 200 OK"

    task = response.json()

    print(json.dumps(task, indent=2))

    while task["task_status"] not in ("success", "failure"):
        response = await async_client.get(f"{base_url}/status/poll/{task['task_id']}")
        assert response.status_code == 200, "Response should be 200 OK"
        task = response.json()
        print(f"{task['task_status']=}")
        print(f"{task['task_position']=}")

        time.sleep(2)

    assert task["task_status"] == "success"

    result_resp = await async_client.get(f"{base_url}/result/{task['task_id']}")
    assert result_resp.status_code == 200, "Response should be 200 OK"
    result = result_resp.json()
    print("Got result.")

    assert "chunks" in result
    assert len(result["chunks"]) > 0

    assert "documents" in result
    assert len(result["documents"]) > 0
    assert result["documents"][0]["status"] == "success"

    if include_converted_doc:
        assert result["documents"][0]["content"]["json_content"] is not None
        assert (
            result["documents"][0]["content"]["json_content"]["schema_name"]
            == "DoclingDocument"
        )
    else:
        assert result["documents"][0]["content"]["json_content"] is None

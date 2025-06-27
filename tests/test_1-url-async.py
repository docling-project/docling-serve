import json
import random
import time

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def async_client():
    async with httpx.AsyncClient(timeout=60.0) as client:
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

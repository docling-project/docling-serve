import json
import time
from pathlib import Path

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

    base_url = "http://localhost:5001/v1"
    payload = {
        "to_formats": ["md", "json", "html"],
        "image_export_mode": "placeholder",
        "ocr": False,
        "abort_on_error": False,
    }

    file_path = Path(__file__).parent / "2206.01062v1.pdf"
    files = {
        "files": (file_path.name, file_path.open("rb"), "application/pdf"),
    }

    for n in range(1):
        response = await async_client.post(
            f"{base_url}/convert/file/async", files=files, data=payload
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
    print(f"Task completed with status {task['task_status']=}")

    result_resp = await async_client.get(f"{base_url}/result/{task['task_id']}")
    assert result_resp.status_code == 200, "Response should be 200 OK"
    result = result_resp.json()
    print("Got result.")

    assert "md_content" in result["document"]
    assert result["document"]["md_content"] is not None
    assert len(result["document"]["md_content"]) > 10

    assert "html_content" in result["document"]
    assert result["document"]["html_content"] is not None
    assert len(result["document"]["html_content"]) > 10

    assert "json_content" in result["document"]
    assert result["document"]["json_content"] is not None
    assert result["document"]["json_content"]["schema_name"] == "DoclingDocument"

import asyncio
import base64
import json
import time
from pathlib import Path

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

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

    doc_filename = Path("tests/2408.09869v5.pdf")
    encoded_doc = base64.b64encode(doc_filename.read_bytes()).decode()

    payload = {
        "options": {
            "to_formats": ["json"],
        },
        "file_sources": [{"base64_string": encoded_doc, "filename": doc_filename.name}],
    }

    response = await client.post("/v1alpha/convert/source/async", json=payload)
    assert response.status_code == 200, "Response should be 200 OK"

    task = response.json()

    print(json.dumps(task, indent=2))

    while task["task_status"] not in ("success", "failure"):
        response = await client.get(f"/v1alpha/status/poll/{task['task_id']}")
        assert response.status_code == 200, "Response should be 200 OK"
        task = response.json()
        print(f"{task['task_status']=}")
        print(f"{task['task_position']=}")

        time.sleep(2)

    assert task["task_status"] == "success"

    # Get result once
    result_response = await client.get(f"/v1alpha/result/{task['task_id']}")
    assert result_response.status_code == 200, "Response should be 200 OK"
    print("Result 1 ok.")
    result = result_response.json()
    assert result["document"]["json_content"]["schema_name"] == "DoclingDocument"

    # Get result twice
    result_response = await client.get(f"/v1alpha/result/{task['task_id']}")
    assert result_response.status_code == 200, "Response should be 200 OK"
    print("Result 2 ok.")
    result = result_response.json()
    assert result["document"]["json_content"]["schema_name"] == "DoclingDocument"

    # Clear
    clear_response = await client.get("/v1alpha/clear/results?older_then=0")
    assert clear_response.status_code == 200, "Response should be 200 OK"
    print("Clear ok.")

    # Get result twice
    result_response = await client.get(f"/v1alpha/result/{task['task_id']}")
    assert result_response.status_code == 404, "Response should be removed"

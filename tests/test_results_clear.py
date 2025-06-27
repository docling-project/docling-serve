import asyncio
import base64
import json
from pathlib import Path

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from docling_serve.app import create_app
from docling_serve.settings import docling_serve_settings


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


async def convert_file(client: AsyncClient):
    doc_filename = Path("tests/2408.09869v5.pdf")
    encoded_doc = base64.b64encode(doc_filename.read_bytes()).decode()

    payload = {
        "options": {
            "to_formats": ["json"],
        },
        "sources": [
            {
                "kind": "file",
                "base64_string": encoded_doc,
                "filename": doc_filename.name,
            }
        ],
    }

    response = await client.post("/v1/convert/source/async", json=payload)
    assert response.status_code == 200, "Response should be 200 OK"

    task = response.json()

    print(json.dumps(task, indent=2))

    while task["task_status"] not in ("success", "failure"):
        response = await client.get(f"/v1/status/poll/{task['task_id']}")
        assert response.status_code == 200, "Response should be 200 OK"
        task = response.json()
        print(f"{task['task_status']=}")
        print(f"{task['task_position']=}")

        await asyncio.sleep(2)

    assert task["task_status"] == "success"

    return task


@pytest.mark.asyncio
async def test_clear_results(client: AsyncClient):
    """Test removal of task."""

    # Set long delay deletion
    docling_serve_settings.result_removal_delay = 100

    # Convert and wait for completion
    task = await convert_file(client)

    # Get result once
    result_response = await client.get(f"/v1/result/{task['task_id']}")
    assert result_response.status_code == 200, "Response should be 200 OK"
    print("Result 1 ok.")
    result = result_response.json()
    assert result["document"]["json_content"]["schema_name"] == "DoclingDocument"

    # Get result twice
    result_response = await client.get(f"/v1/result/{task['task_id']}")
    assert result_response.status_code == 200, "Response should be 200 OK"
    print("Result 2 ok.")
    result = result_response.json()
    assert result["document"]["json_content"]["schema_name"] == "DoclingDocument"

    # Clear
    clear_response = await client.get("/v1/clear/results?older_then=0")
    assert clear_response.status_code == 200, "Response should be 200 OK"
    print("Clear ok.")

    # Get deleted result
    result_response = await client.get(f"/v1/result/{task['task_id']}")
    assert result_response.status_code == 404, "Response should be removed"
    print("Result was no longer found.")


@pytest.mark.asyncio
async def test_delay_remove(client: AsyncClient):
    """Test automatic removal of task with delay."""

    # Set short delay deletion
    docling_serve_settings.result_removal_delay = 5

    # Convert and wait for completion
    task = await convert_file(client)

    # Get result once
    result_response = await client.get(f"/v1/result/{task['task_id']}")
    assert result_response.status_code == 200, "Response should be 200 OK"
    print("Result ok.")
    result = result_response.json()
    assert result["document"]["json_content"]["schema_name"] == "DoclingDocument"

    print("Sleeping to wait the automatic task deletion.")
    await asyncio.sleep(10)

    # Get deleted result
    result_response = await client.get(f"/v1/result/{task['task_id']}")
    assert result_response.status_code == 404, "Response should be removed"

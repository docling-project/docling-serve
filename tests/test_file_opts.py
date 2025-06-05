import asyncio
import json
import os

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from docling_core.types import DoclingDocument
from docling_core.types.doc.document import PictureDescriptionData

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
async def test_convert_file(client: AsyncClient):
    """Test convert single file to all outputs"""

    endpoint = "/v1alpha/convert/file"
    options = {
        "to_formats": ["md", "json"],
        "image_export_mode": "placeholder",
        "ocr": False,
        "do_picture_description": True,
        "picture_description_api": json.dumps(
            {
                "url": "http://localhost:11434/v1/chat/completions",  # ollama
                "params": {"model": "granite3.2-vision:2b"},
                "timeout": 60,
                "prompt": "Describe this image in a few sentences. ",
            }
        ),
    }

    current_dir = os.path.dirname(__file__)
    file_path = os.path.join(current_dir, "2206.01062v1.pdf")

    files = {
        "files": ("2206.01062v1.pdf", open(file_path, "rb"), "application/pdf"),
    }

    response = await client.post(endpoint, files=files, data=options)
    assert response.status_code == 200, "Response should be 200 OK"

    data = response.json()

    doc = DoclingDocument.model_validate(data["document"]["json_content"])

    for pic in doc.pictures:
        for ann in pic.annotations:
            if isinstance(ann, PictureDescriptionData):
                print(f"{pic.self_ref}")
                print(ann.text)

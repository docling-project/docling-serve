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


@pytest.mark.asyncio
async def test_convert_file_async_chunked(async_client):
    """Test async convert single file to chunked output"""
    base_url = "http://localhost:5001/v1"
    payload = {
        "do_chunking": True,
        "chunking_options": json.dumps(
            {
                "tokenizer": "Qwen/Qwen3-Embedding-0.6B",
                "max_tokens": 512,
                "use_markdown_tables": True,
                "merge_peers": True,
            }
        ),
        "abort_on_error": False,
    }

    file_path = Path(__file__).parent / "2206.01062v1.pdf"
    files = {
        "files": (file_path.name, file_path.open("rb"), "application/pdf"),
    }

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

    # Response content checks
    assert "chunks" in result
    chunks = result["chunks"]
    assert isinstance(chunks, list)
    assert len(chunks) > 0

    first_chunk = chunks[0]
    assert "filename" in first_chunk
    assert first_chunk["filename"] == "2206.01062v1.pdf"
    assert "chunk_index" in first_chunk
    assert first_chunk["chunk_index"] == 0
    assert "chunk_text" in first_chunk
    assert len(first_chunk["chunk_text"]) > 0
    assert "contextualized_text" in first_chunk
    assert len(first_chunk["contextualized_text"]) > 0

    # Content validation - check for expected content in chunks
    chunk_texts = [chunk.get("chunk_text", "") or "" for chunk in chunks]
    all_chunk_text = " ".join(chunk_texts)
    assert "DocLayNet" in all_chunk_text, "Chunks should contain 'DocLayNet'"
    assert "Large Human-Annotated Dataset" in all_chunk_text, (
        "Chunks should contain 'Large Human-Annotated Dataset'"
    )

    assert "status" in result
    assert result["status"] == "success"
    assert "processing_time" in result
    assert "chunking_info" in result

import json
import os

import httpx
import pytest
import pytest_asyncio
from pytest_check import check


@pytest_asyncio.fixture
async def async_client():
    async with httpx.AsyncClient(timeout=60.0) as client:
        yield client


@pytest.mark.asyncio
async def test_convert_file(async_client):
    """Test convert single file to all outputs"""
    url = "http://localhost:5001/v1/convert/file"
    options = {
        "from_formats": [
            "docx",
            "pptx",
            "html",
            "image",
            "pdf",
            "asciidoc",
            "md",
            "xlsx",
        ],
        "to_formats": ["md", "json", "html", "text", "doctags"],
        "image_export_mode": "placeholder",
        "ocr": True,
        "force_ocr": False,
        "ocr_engine": "easyocr",
        "ocr_lang": ["en"],
        "pdf_backend": "dlparse_v2",
        "table_mode": "fast",
        "abort_on_error": False,
    }

    current_dir = os.path.dirname(__file__)
    file_path = os.path.join(current_dir, "2206.01062v1.pdf")

    files = [
        ("files", ("2206.01062v1.pdf", open(file_path, "rb"), "application/pdf")),
        ("files", ("2408.09869v5.pdf", open(file_path, "rb"), "application/pdf")),
    ]

    response = await async_client.post(url, files=files, data=options)
    assert response.status_code == 200, "Response should be 200 OK"

    # Check for zip file attachment
    content_disposition = response.headers.get("content-disposition")

    with check:
        assert content_disposition is not None, (
            "Content-Disposition header should be present"
        )
    with check:
        assert "attachment" in content_disposition, "Response should be an attachment"
    with check:
        assert 'filename="converted_docs.zip"' in content_disposition, (
            "Attachment filename should be 'converted_docs.zip'"
        )

    content_type = response.headers.get("content-type")
    with check:
        assert content_type == "application/zip", (
            "Content-Type should be 'application/zip'"
        )


@pytest.mark.asyncio
async def test_convert_files_chunked(async_client):
    """Test convert multiple files to chunked output"""
    url = "http://localhost:5001/v1/convert/file"
    options = {
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

    current_dir = os.path.dirname(__file__)

    files = [
        (
            "files",
            (
                "2206.01062v1.pdf",
                open(os.path.join(current_dir, "2206.01062v1.pdf"), "rb"),
                "application/pdf",
            ),
        ),
        (
            "files",
            (
                "2408.09869v5.pdf",
                open(os.path.join(current_dir, "2408.09869v5.pdf"), "rb"),
                "application/pdf",
            ),
        ),
    ]

    response = await async_client.post(url, files=files, data=options)
    if response.status_code != 200:
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.text}")
    assert response.status_code == 200, "Response should be 200 OK"

    data = response.json()

    # Response content checks
    check.is_in(
        "chunks",
        data,
        msg=f"Response should contain 'chunks' key. Received keys: {list(data.keys())}",
    )
    chunks = data["chunks"]
    check.is_instance(chunks, list)
    check.greater(len(chunks), 1)

    # Check chunks from different files
    filenames = {c["filename"] for c in chunks}
    check.equal(len(filenames), 2)
    check.is_in("2206.01062v1.pdf", filenames)
    check.is_in("2408.09869v5.pdf", filenames)

    # Content validation - verify expected content appears in chunks
    chunk_texts = [chunk.get("chunk_text", "") or "" for chunk in chunks]
    all_chunk_text = " ".join(chunk_texts)
    check.is_in(
        "DocLayNet",
        all_chunk_text,
        msg="Chunks should contain 'DocLayNet' from the first document",
    )

    first_chunk = chunks[0]
    check.is_in("filename", first_chunk)
    check.is_in("chunk_index", first_chunk)
    check.is_in("chunk_text", first_chunk)
    check.greater(len(first_chunk["chunk_text"]), 0)
    check.is_in("contextualized_text", first_chunk)
    check.greater(len(first_chunk["contextualized_text"]), 0)

    # Verify chunk distribution across files
    for filename in filenames:
        file_chunks = [c for c in chunks if c["filename"] == filename]
        check.greater(len(file_chunks), 0, f"Should have chunks for {filename}")

        # Verify chunk indexing starts at 0 for each file
        chunk_indices = [c["chunk_index"] for c in file_chunks]
        check.is_in(0, chunk_indices, f"Should have chunk_index 0 for {filename}")

    check.is_in("status", data)
    check.equal(data["status"], "success")
    check.is_in("processing_time", data)
    check.is_in("chunking_info", data)

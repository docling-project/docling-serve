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

    files = {
        "files": ("2206.01062v1.pdf", open(file_path, "rb"), "application/pdf"),
    }

    response = await async_client.post(url, files=files, data=options)
    assert response.status_code == 200, "Response should be 200 OK"

    data = response.json()

    # Response content checks
    # Helper function to safely slice strings
    def safe_slice(value, length=100):
        if isinstance(value, str):
            return value[:length]
        return str(value)  # Convert non-string values to string for debug purposes

    # Document check
    check.is_in(
        "document",
        data,
        msg=f"Response should contain 'document' key. Received keys: {list(data.keys())}",
    )
    # MD check
    check.is_in(
        "md_content",
        data.get("document", {}),
        msg=f"Response should contain 'md_content' key. Received keys: {list(data.get('document', {}).keys())}",
    )
    if data.get("document", {}).get("md_content") is not None:
        check.is_in(
            "## DocLayNet: ",
            data["document"]["md_content"],
            msg=f"Markdown document should contain 'DocLayNet: '. Received: {safe_slice(data['document']['md_content'])}",
        )
    # JSON check
    check.is_in(
        "json_content",
        data.get("document", {}),
        msg=f"Response should contain 'json_content' key. Received keys: {list(data.get('document', {}).keys())}",
    )
    if data.get("document", {}).get("json_content") is not None:
        check.is_in(
            '{"schema_name": "DoclingDocument"',
            json.dumps(data["document"]["json_content"]),
            msg=f'JSON document should contain \'{{\\n  "schema_name": "DoclingDocument\'". Received: {safe_slice(data["document"]["json_content"])}',
        )
    # HTML check
    if data.get("document", {}).get("html_content") is not None:
        check.is_in(
            "<!DOCTYPE html>\n<html>\n<head>",
            data["document"]["html_content"],
            msg=f"HTML document should contain '<!DOCTYPE html>\\n<html>'. Received: {safe_slice(data['document']['html_content'])}",
        )
    # Text check
    check.is_in(
        "text_content",
        data.get("document", {}),
        msg=f"Response should contain 'text_content' key. Received keys: {list(data.get('document', {}).keys())}",
    )
    if data.get("document", {}).get("text_content") is not None:
        check.is_in(
            "DocLayNet: A Large Human-Annotated Dataset",
            data["document"]["text_content"],
            msg=f"Text document should contain 'DocLayNet: A Large Human-Annotated Dataset'. Received: {safe_slice(data['document']['text_content'])}",
        )
    # DocTags check
    check.is_in(
        "doctags_content",
        data.get("document", {}),
        msg=f"Response should contain 'doctags_content' key. Received keys: {list(data.get('document', {}).keys())}",
    )
    if data.get("document", {}).get("doctags_content") is not None:
        check.is_in(
            "<doctag><page_header><loc",
            data["document"]["doctags_content"],
            msg=f"DocTags document should contain '<doctag><page_header><loc'. Received: {safe_slice(data['document']['doctags_content'])}",
        )


@pytest.mark.asyncio
async def test_convert_file_chunked(async_client):
    """Test convert single file to chunked output"""
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
    file_path = os.path.join(current_dir, "2206.01062v1.pdf")

    files = {
        "files": ("2206.01062v1.pdf", open(file_path, "rb"), "application/pdf"),
    }

    response = await async_client.post(url, files=files, data=options)
    if response.status_code != 200:
        print(f"Response status: {response.status_code}")
        print(f"Response content: {response.text}")
    assert response.status_code == 200, "Response should be 200 OK"

    data = response.json()

    # Helper function to safely slice strings
    def safe_slice(value, length=100):
        if isinstance(value, str):
            return value[:length]
        return str(value)

    # Response content checks
    check.is_in(
        "chunks",
        data,
        msg=f"Response should contain 'chunks' key. Received keys: {list(data.keys())}",
    )
    chunks = data["chunks"]
    check.is_instance(chunks, list)
    check.greater(len(chunks), 0)

    first_chunk = chunks[0]

    # Verify new fields
    check.is_in("page_numbers", first_chunk)
    check.is_instance(first_chunk["page_numbers"], list)
    if first_chunk["page_numbers"]:
        check.equal(first_chunk["page_numbers"][0], 1)  # Should include page 1

    # Check for headings field (may be None for some chunks)
    check.is_in("headings", first_chunk)
    if first_chunk.get("headings"):
        check.is_instance(first_chunk["headings"], list)

    check.is_in("chunk_text", first_chunk)
    check.is_in("contextualized_text", first_chunk)

    # Content validation - check for expected content in chunks
    chunk_texts = [chunk.get("chunk_text", "") or "" for chunk in chunks]
    all_chunk_text = " ".join(chunk_texts)
    check.is_in(
        "DocLayNet",
        all_chunk_text,
        msg=f"Chunks should contain 'DocLayNet'. Received: {safe_slice(all_chunk_text)}",
    )
    check.is_in(
        "Large Human-Annotated Dataset",
        all_chunk_text,
        msg=f"Chunks should contain 'Large Human-Annotated Dataset'. Received: {safe_slice(all_chunk_text)}",
    )

    # Verify metadata doesn't have origin (redundant with filename)
    if first_chunk.get("metadata"):
        check.is_not_in("origin", first_chunk["metadata"])

    check.is_in("filename", first_chunk)
    check.equal(first_chunk["filename"], "2206.01062v1.pdf")
    check.is_in("chunk_index", first_chunk)
    check.equal(first_chunk["chunk_index"], 0)
    check.is_in("chunk_text", first_chunk)
    check.greater(len(first_chunk["chunk_text"]), 0)
    check.is_in("contextualized_text", first_chunk)
    check.greater(len(first_chunk["contextualized_text"]), 0)

    check.is_in("status", data)
    check.equal(data["status"], "success")
    check.is_in("processing_time", data)
    check.is_in("chunking_info", data)


@pytest.mark.asyncio
async def test_convert_file_chunked_no_raw_text(async_client):
    """Test convert single file to chunked output without raw text"""
    url = "http://localhost:5001/v1/convert/file"
    options = {
        "do_chunking": True,
        "chunking_options": json.dumps(
            {
                "tokenizer": "Qwen/Qwen3-Embedding-0.6B",
                "max_tokens": 512,
                "use_markdown_tables": True,
                "merge_peers": True,
                "include_raw_text": False,
            }
        ),
        "abort_on_error": False,
    }

    current_dir = os.path.dirname(__file__)
    file_path = os.path.join(current_dir, "2206.01062v1.pdf")

    files = {
        "files": ("2206.01062v1.pdf", open(file_path, "rb"), "application/pdf"),
    }

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
    check.greater(len(chunks), 0)

    first_chunk = chunks[0]

    # Verify chunk_text is None when include_raw_text is False
    check.is_in("chunk_text", first_chunk)
    check.equal(first_chunk["chunk_text"], None)
    check.is_in("contextualized_text", first_chunk)
    check.greater(len(first_chunk["contextualized_text"]), 0)

    # Content validation on contextualized text
    contextualized_texts = [chunk.get("contextualized_text", "") for chunk in chunks]
    all_contextualized_text = " ".join(contextualized_texts)
    check.is_in(
        "DocLayNet",
        all_contextualized_text,
        msg="Contextualized text should contain 'DocLayNet'",
    )

    # Verify page numbers are still extracted
    check.is_in("page_numbers", first_chunk)
    if first_chunk.get("page_numbers"):
        check.equal(first_chunk["page_numbers"][0], 1)

    check.is_in("status", data)
    check.equal(data["status"], "success")
    check.is_in("processing_time", data)
    check.is_in("chunking_info", data)

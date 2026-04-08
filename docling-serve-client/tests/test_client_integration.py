import os
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions

from docling.datamodel.base_models import OutputFormat
from docling.service_client import DoclingServiceClient, RawServiceResult

INTEGRATION_API_KEY = "integration-key"
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent


def _free_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_service_url() -> Iterator[str]:
    port = _free_tcp_port()
    base_url = f"http://127.0.0.1:{port}"

    env = os.environ.copy()
    env["DOCLING_SERVE_LOAD_MODELS_AT_BOOT"] = "false"
    env["DOCLING_SERVE_OTEL_ENABLE_METRICS"] = "false"
    env["DOCLING_SERVE_OTEL_ENABLE_PROMETHEUS"] = "false"
    env["DOCLING_SERVE_API_KEY"] = INTEGRATION_API_KEY

    process = subprocess.Popen(
        [
            "uv",
            "run",
            "docling-serve",
            "run",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=PACKAGE_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    timeout_s = 60.0
    start = time.monotonic()
    ready = False
    while time.monotonic() - start < timeout_s:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise RuntimeError(f"docling-serve failed to start.\n{stderr}")
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(f"{base_url}/health")
            if response.status_code == 200:
                ready = True
                break
        except httpx.HTTPError:
            pass
        time.sleep(0.5)

    if not ready:
        process.terminate()
        stderr = process.stderr.read() if process.stderr is not None else ""
        raise RuntimeError(f"docling-serve did not become ready.\n{stderr}")

    try:
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)


def _json_options() -> ConvertDocumentsRequestOptions:
    return ConvertDocumentsRequestOptions(
        do_ocr=False,
        do_table_structure=False,
        include_images=False,
        to_formats=[OutputFormat.JSON],
        abort_on_error=False,
    )


def test_convert_and_submit_with_polling_watcher(
    live_service_url: str, tmp_path: Path
) -> None:
    source = FIXTURES_DIR / "2206.01062v1.pdf"
    assert source.exists()

    with DoclingServiceClient(
        url=live_service_url,
        api_key=INTEGRATION_API_KEY,
        status_watcher="polling",
        poll_server_wait=0.2,
        job_timeout=300.0,
        options=_json_options(),
    ) as client:
        health = client.health()
        assert health.status == "ok"

        converted = client.convert(source=source)
        assert converted.status.value in {"success", "partial_success"}
        assert converted.document.name == "2206.01062v1"

        job = client.submit(source=source, target_format=OutputFormat.JSON)
        submitted = job.result(timeout=300.0)
        assert submitted.status.value in {"success", "partial_success"}
        assert submitted.document.name == "2206.01062v1"


def test_submit_non_json_returns_raw_payload(
    live_service_url: str, tmp_path: Path
) -> None:
    source = FIXTURES_DIR / "2206.01062v1.pdf"
    assert source.exists()

    with DoclingServiceClient(
        url=live_service_url,
        api_key=INTEGRATION_API_KEY,
        status_watcher="polling",
        poll_server_wait=0.2,
        job_timeout=300.0,
    ) as client:
        options = ConvertDocumentsRequestOptions(
            do_ocr=False,
            do_table_structure=False,
            include_images=False,
            to_formats=[OutputFormat.MARKDOWN],
            abort_on_error=False,
        )
        job = client.submit(
            source=source, options=options, target_format=OutputFormat.MARKDOWN
        )
        raw_result = job.result(timeout=300.0)

        assert isinstance(raw_result, RawServiceResult)
        assert len(raw_result.content) > 0
        assert "zip" in raw_result.content_type


def test_convert_all_preserves_input_order(
    live_service_url: str, tmp_path: Path
) -> None:
    source = FIXTURES_DIR / "2206.01062v1.pdf"
    assert source.exists()
    source_a = tmp_path / "order-a.pdf"
    source_b = tmp_path / "order-b.pdf"
    source_a.write_bytes(source.read_bytes())
    source_b.write_bytes(source.read_bytes())

    with DoclingServiceClient(
        url=live_service_url,
        api_key=INTEGRATION_API_KEY,
        status_watcher="polling",
        poll_server_wait=0.2,
        job_timeout=300.0,
    ) as client:
        results = list(
            client.convert_all(
                sources=[source_a, source_b],
                options=_json_options(),
                max_concurrency=2,
            )
        )

    assert len(results) == 2
    assert results[0].input.file.name == "order-a.pdf"
    assert results[1].input.file.name == "order-b.pdf"


def test_websocket_watcher_end_to_end(live_service_url: str, tmp_path: Path) -> None:
    source = FIXTURES_DIR / "2206.01062v1.pdf"
    assert source.exists()

    with DoclingServiceClient(
        url=live_service_url,
        api_key=INTEGRATION_API_KEY,
        status_watcher="websocket",
        ws_fallback_to_poll=True,
        poll_server_wait=0.2,
        job_timeout=300.0,
    ) as client:
        result = client.convert(source=source, options=_json_options())

    assert result.status.value in {"success", "partial_success"}
    assert result.document.name == "2206.01062v1"


def test_submit_accepts_custom_request_headers(
    live_service_url: str,
) -> None:
    source = FIXTURES_DIR / "2206.01062v1.pdf"
    assert source.exists()

    with DoclingServiceClient(
        url=live_service_url,
        api_key=INTEGRATION_API_KEY,
        status_watcher="polling",
        poll_server_wait=0.2,
        job_timeout=300.0,
    ) as client:
        job = client.submit(
            source=source,
            options=_json_options(),
            headers={"X-Tenant-Id": "tenant-integration"},
        )
        result = job.result(timeout=300.0)

    assert result.status.value in {"success", "partial_success"}

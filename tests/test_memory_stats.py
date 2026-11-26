"""``/v1/memory/stats`` works without the cgroup v2 memory files.

``memory.current`` and ``memory.stat`` only exist on Linux with cgroup v2. On
other hosts the endpoint reports the process RSS and leaves the cgroup fields
empty instead of failing with a 500.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from docling_serve import app as app_module
from docling_serve.settings import docling_serve_settings


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: MagicMock())
    monkeypatch.setattr(docling_serve_settings, "enable_management_endpoints", True)
    with patch.object(app_module, "setup_otel_instrumentation"):
        return TestClient(app_module.create_app())


def test_memory_stats_reads_cgroup_v2_files(client, monkeypatch, tmp_path) -> None:
    mb = 1024 * 1024
    (tmp_path / "memory.current").write_text(f"{300 * mb}\n")
    (tmp_path / "memory.stat").write_text(
        f"anon {200 * mb}\nfile {80 * mb}\nslab {20 * mb}\nsock 0\n"
    )
    monkeypatch.setattr(app_module, "CGROUP_MEMORY_DIR", tmp_path)

    response = client.get("/v1/memory/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["rss"] > 0
    assert body["cgroup_total"] == 300.0
    assert body["anon"] == 200.0
    assert body["file"] == 80.0
    assert body["slab"] == 20.0


def test_memory_stats_without_cgroup_v2_reports_rss_only(
    client, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(app_module, "CGROUP_MEMORY_DIR", tmp_path / "missing")

    response = client.get("/v1/memory/stats")

    assert response.status_code == 200
    body = response.json()
    assert body["rss"] > 0
    assert body["cgroup_total"] is None
    assert body["anon"] is None
    assert body["file"] is None
    assert body["slab"] is None


def test_memory_stats_is_forbidden_when_management_endpoints_are_off(
    client, monkeypatch
) -> None:
    monkeypatch.setattr(docling_serve_settings, "enable_management_endpoints", False)

    assert client.get("/v1/memory/stats").status_code == 403

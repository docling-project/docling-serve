# SPDX-License-Identifier: MIT

"""Hermetic contract tests for GET /v1/tasks.

The route exposes the tenant-scoped active-task listing owned by
``docling-jobkit`` (``docling_jobkit.datamodel.task_listing``) without
reimplementing filtering, ordering or paging: the serve layer forwards the
resolved tenant plus the validated ``limit``/``offset`` window to
``orchestrator.list_tasks`` for the Local, RQ and Ray backends. Backend
enumeration, tenant filtering before paging, newest-first ordering and the
shared ``ActiveTaskPage`` shape are covered by the jobkit suite
(``tests/test_task_listing.py`` in the paired jobkit checkout); these tests
prove the HTTP contract only.

Hermetic: ``TestClient`` without entering lifespan (no model download, no
converter startup) and ``setup_otel_instrumentation`` patched, mirroring
``tests/test_api_docs_and_metrics_toggle.py``.
"""

import datetime
import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from docling.datamodel.service.tasks import TaskType
from docling_jobkit.datamodel.task import validate_task
from docling_jobkit.datamodel.task_listing import (
    ActiveTaskItem,
    ActiveTaskPage,
    build_active_task_page,
)
from docling_jobkit.datamodel.task_meta import TaskStatus
from docling_jobkit.orchestrators.base_orchestrator import RedisBackpressureError
from docling_jobkit.orchestrators.local.orchestrator import (
    LocalOrchestrator,
    LocalOrchestratorConfig,
)
from docling_jobkit.orchestrators.rq.orchestrator import _decode_stored_task

from docling_serve import app as app_module
from docling_serve.settings import docling_serve_settings

_T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def _at(seconds: int) -> datetime.datetime:
    return _T0 + datetime.timedelta(seconds=seconds)


def _make_task(
    task_id: str,
    *,
    tenant: str | None = "tenant-a",
    status: TaskStatus = TaskStatus.PENDING,
    created_at: datetime.datetime | None = None,
    task_type: TaskType = TaskType.CONVERT,
) -> Any:
    metadata: dict[str, Any] = {} if tenant is None else {"tenant_id": tenant}
    task = validate_task(
        {
            "task_id": task_id,
            "task_type": task_type,
            "task_status": status,
            "metadata": metadata,
        }
    )
    task.created_at = created_at or _T0
    return task


def _local_orchestrator(tmp_path, tasks: dict) -> LocalOrchestrator:
    orchestrator = LocalOrchestrator(
        config=LocalOrchestratorConfig(scratch_dir=tmp_path),
        converter_manager=None,  # type: ignore[arg-type]  # listing never touches converters
    )
    orchestrator.tasks = tasks
    # Fail-fast guard: listing must never start converters. Any accidental
    # warmup/queue startup raises instead of silently succeeding.
    orchestrator.warm_up_caches = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("warm_up_caches must not run for listing")
    )
    orchestrator.process_queue = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("process_queue must not run for listing")
    )
    return orchestrator


def _make_client(monkeypatch, *, orchestrator, api_key: str = "") -> TestClient:
    """Build the app without lifespan or real OTEL, with a stubbed orchestrator."""
    monkeypatch.setattr(docling_serve_settings, "api_key", api_key)
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: orchestrator)
    with patch.object(app_module, "setup_otel_instrumentation"):
        return TestClient(app_module.create_app(), raise_server_exceptions=False)


def _stub_orchestrator(page: ActiveTaskPage | None = None):
    stub = AsyncMock()
    if page is not None:
        stub.list_tasks.return_value = page
    return stub


def _tenant_header() -> str:
    return docling_serve_settings.eng_ray_tenant_id_header


# ---------------------------------------------------------------------------
# Tenant forwarding
# ---------------------------------------------------------------------------


def test_default_tenant_and_disabled_key_need_no_headers(monkeypatch) -> None:
    """Default tenant plus disabled-key behavior in one place.

    With no API key configured the route needs no auth header, resolves the
    absent tenant header to ``default``, and forwards the default window.
    """
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub, api_key="")

    response = client.get("/v1/tasks")

    assert response.status_code == 200
    stub.list_tasks.assert_awaited_once_with(tenant_id="default", limit=20, offset=0)


def test_custom_tenant_header_is_forwarded(monkeypatch) -> None:
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub)

    response = client.get("/v1/tasks", headers={_tenant_header(): "tenant-a"})

    assert response.status_code == 200
    stub.list_tasks.assert_awaited_once_with(tenant_id="tenant-a", limit=20, offset=0)


def test_configured_header_name_and_openapi(monkeypatch) -> None:
    monkeypatch.setattr(docling_serve_settings, "eng_ray_tenant_id_header", "X-Team")
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub)

    assert client.get("/v1/tasks", headers={"X-Team": "team-a"}).status_code == 200
    stub.list_tasks.assert_awaited_once_with(tenant_id="team-a", limit=20, offset=0)
    params = client.get("/openapi.json").json()["paths"]["/v1/tasks"]["get"][
        "parameters"
    ]
    assert any(p["name"] == "X-Team" and p["in"] == "header" for p in params)
    stub.list_tasks.reset_mock()
    assert (
        client.get(
            "/v1/tasks?tenant_id=other", headers={"X-Tenant-Id": "other"}
        ).status_code
        == 200
    )
    stub.list_tasks.assert_awaited_once_with(tenant_id="default", limit=20, offset=0)


def test_default_tenant_real_local_and_id_ties(monkeypatch, tmp_path) -> None:
    orchestrator = _local_orchestrator(
        tmp_path,
        {
            "z": _make_task("z", tenant=None),
            "a": _make_task("a", tenant="default"),
            "other": _make_task("other", tenant="other", created_at=_at(10)),
        },
    )
    client = _make_client(monkeypatch, orchestrator=orchestrator)
    response = client.get("/v1/tasks")
    assert response.status_code == 200
    assert [item["task_id"] for item in response.json()["items"]] == ["a", "z"]


@pytest.mark.parametrize("params", [{"limit": "abc"}, {"offset": "1.5"}])
def test_non_integer_window_is_rejected(monkeypatch, params) -> None:
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub)
    assert client.get("/v1/tasks", params=params).status_code == 422
    stub.list_tasks.assert_not_awaited()


def test_two_tenant_filtering_happens_before_paging(monkeypatch, tmp_path) -> None:
    """End-to-end through the real LocalOrchestrator bookkeeping.

    tenant-a owns three tasks, tenant-b two interleaved ones. Paging the
    tenant-a view must slice only tenant-a entries (newest first), proving the
    tenant filter runs before ``limit``/``offset`` rather than after. This also
    covers the single-tenant non-final/final page shape (``has_more``), so no
    separate three-task paging case is needed.
    """
    orchestrator = _local_orchestrator(
        tmp_path,
        {
            "a1": _make_task("a1", tenant="tenant-a", created_at=_at(10)),
            "b1": _make_task("b1", tenant="tenant-b", created_at=_at(15)),
            "a2": _make_task(
                "a2",
                tenant="tenant-a",
                status=TaskStatus.STARTED,
                created_at=_at(20),
            ),
            "b2": _make_task("b2", tenant="tenant-b", created_at=_at(25)),
            "a3": _make_task("a3", tenant="tenant-a", created_at=_at(30)),
        },
    )
    client = _make_client(monkeypatch, orchestrator=orchestrator)

    first = client.get(
        "/v1/tasks",
        params={"limit": 2, "offset": 0},
        headers={_tenant_header(): "tenant-a"},
    )
    second = client.get(
        "/v1/tasks",
        params={"limit": 2, "offset": 2},
        headers={_tenant_header(): "tenant-a"},
    )
    other = client.get("/v1/tasks", headers={_tenant_header(): "tenant-b"})

    assert first.status_code == 200
    assert [item["task_id"] for item in first.json()["items"]] == ["a3", "a2"]
    assert first.json()["has_more"] is True

    assert second.status_code == 200
    assert [item["task_id"] for item in second.json()["items"]] == ["a1"]
    assert second.json()["has_more"] is False

    assert other.status_code == 200
    assert [item["task_id"] for item in other.json()["items"]] == ["b2", "b1"]

    # Listing is bookkeeping-only: converter startup must never have run.
    orchestrator.warm_up_caches.assert_not_awaited()
    orchestrator.process_queue.assert_not_awaited()


def test_only_pending_and_started_are_listed(monkeypatch, tmp_path) -> None:
    orchestrator = _local_orchestrator(
        tmp_path,
        {
            "pending": _make_task("pending", tenant="tenant-a", created_at=_at(10)),
            "started": _make_task(
                "started",
                tenant="tenant-a",
                status=TaskStatus.STARTED,
                created_at=_at(20),
            ),
            "success": _make_task(
                "success",
                tenant="tenant-a",
                status=TaskStatus.SUCCESS,
                created_at=_at(30),
            ),
            "failure": _make_task(
                "failure",
                tenant="tenant-a",
                status=TaskStatus.FAILURE,
                created_at=_at(40),
            ),
        },
    )
    client = _make_client(monkeypatch, orchestrator=orchestrator)

    response = client.get("/v1/tasks", headers={_tenant_header(): "tenant-a"})

    assert response.status_code == 200
    assert [item["task_id"] for item in response.json()["items"]] == [
        "started",
        "pending",
    ]


def test_chunk_task_decodes_via_real_decoder_and_serializes(monkeypatch) -> None:
    """CHUNK transport through the real RQ decoder and shared paging.

    The backend page object may be stubbed, but the task decoding and the
    paging helper are the real jobkit implementations; the HTTP response then
    proves genuine FastAPI serialization of the CHUNK enum and compact fields.
    """
    first = _make_task(
        "c1", tenant="tenant-a", task_type=TaskType.CHUNK, created_at=_at(10)
    )
    second = _make_task(
        "c2",
        tenant="tenant-a",
        task_type=TaskType.CHUNK,
        status=TaskStatus.STARTED,
        created_at=_at(20),
    )
    decoded = [
        _decode_stored_task(
            json.loads(task.model_dump_json()), allow_external_plugins=False
        )
        for task in (first, second)
    ]
    items = [
        ActiveTaskItem(
            task_id=task.task_id,
            task_type=task.task_type,
            task_status=task.task_status,
            created_at=task.created_at,
        )
        for task in decoded
    ]
    page = build_active_task_page(items, limit=20, offset=0)
    stub = _stub_orchestrator(page)
    client = _make_client(monkeypatch, orchestrator=stub)

    response = client.get("/v1/tasks", headers={_tenant_header(): "tenant-a"})

    assert response.status_code == 200
    body = response.json()
    assert [item["task_id"] for item in body["items"]] == ["c2", "c1"]
    assert all(item["task_type"] == "chunk" for item in body["items"])
    assert [item["task_status"] for item in body["items"]] == [
        "started",
        "pending",
    ]
    assert all(
        set(item) == {"task_id", "task_type", "task_status", "created_at"}
        for item in body["items"]
    )


# ---------------------------------------------------------------------------
# Bounds, defaults, paging
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("limit", [0, 101, -1])
def test_limit_outside_1_to_100_is_422(monkeypatch, limit: int) -> None:
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub)

    response = client.get("/v1/tasks", params={"limit": limit})

    assert response.status_code == 422
    stub.list_tasks.assert_not_awaited()


def test_negative_offset_is_422(monkeypatch) -> None:
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub)

    response = client.get("/v1/tasks", params={"offset": -1})

    assert response.status_code == 422
    stub.list_tasks.assert_not_awaited()


@pytest.mark.parametrize("limit", [1, 100])
def test_limit_boundaries_forward_exact_window(monkeypatch, limit: int) -> None:
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub)

    response = client.get("/v1/tasks", params={"limit": limit})

    assert response.status_code == 200
    stub.list_tasks.assert_awaited_once_with(tenant_id="default", limit=limit, offset=0)


def test_empty_and_out_of_range_pages(monkeypatch, tmp_path) -> None:
    orchestrator = _local_orchestrator(tmp_path, {})
    client = _make_client(monkeypatch, orchestrator=orchestrator)

    empty = client.get("/v1/tasks", headers={_tenant_header(): "nobody"})
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "has_more": False}

    orchestrator.tasks = {"a1": _make_task("a1", tenant="tenant-a")}
    beyond = client.get(
        "/v1/tasks",
        params={"limit": 20, "offset": 50},
        headers={_tenant_header(): "tenant-a"},
    )
    assert beyond.status_code == 200
    assert beyond.json() == {"items": [], "has_more": False}


def test_items_carry_only_the_four_identity_fields(monkeypatch, tmp_path) -> None:
    orchestrator = _local_orchestrator(
        tmp_path, {"a1": _make_task("a1", tenant="tenant-a")}
    )
    client = _make_client(monkeypatch, orchestrator=orchestrator)

    response = client.get("/v1/tasks", headers={_tenant_header(): "tenant-a"})

    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert set(items[0]) == {"task_id", "task_type", "task_status", "created_at"}
    assert set(response.json()) == {"items", "has_more"}


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_missing_api_key_is_401_and_backend_is_not_called(monkeypatch) -> None:
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub, api_key="secret")

    response = client.get("/v1/tasks")

    assert response.status_code == 401
    stub.list_tasks.assert_not_awaited()


def test_wrong_api_key_is_401_and_backend_is_not_called(monkeypatch) -> None:
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub, api_key="secret")

    response = client.get("/v1/tasks", headers={"X-Api-Key": "wrong"})

    assert response.status_code == 401
    stub.list_tasks.assert_not_awaited()


def test_correct_api_key_reaches_the_backend(monkeypatch) -> None:
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub, api_key="secret")

    response = client.get(
        "/v1/tasks",
        headers={"X-Api-Key": "secret", _tenant_header(): "tenant-a"},
    )

    assert response.status_code == 200
    stub.list_tasks.assert_awaited_once_with(tenant_id="tenant-a", limit=20, offset=0)


# ---------------------------------------------------------------------------
# Failures and schema
# ---------------------------------------------------------------------------


def test_backend_failure_never_surfaces_as_an_empty_page(monkeypatch) -> None:
    stub = AsyncMock()
    stub.list_tasks.side_effect = RuntimeError("boom")
    client = _make_client(monkeypatch, orchestrator=stub)

    response = client.get("/v1/tasks")

    assert response.status_code == 500


def test_backpressure_surfaces_as_503(monkeypatch) -> None:
    stub = AsyncMock()
    stub.list_tasks.side_effect = RedisBackpressureError("busy")
    client = _make_client(monkeypatch, orchestrator=stub)

    response = client.get("/v1/tasks")

    assert response.status_code == 503


def test_openapi_declares_response_query_and_header(monkeypatch) -> None:
    stub = _stub_orchestrator(ActiveTaskPage(items=[], has_more=False))
    client = _make_client(monkeypatch, orchestrator=stub)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    operation = schema["paths"]["/v1/tasks"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ActiveTaskPage"
    }

    params = {item["name"]: item for item in operation["parameters"]}
    assert params["limit"]["in"] == "query"
    assert params["limit"]["schema"]["minimum"] == 1
    assert params["limit"]["schema"]["maximum"] == 100
    assert params["limit"]["schema"]["default"] == 20
    assert params["offset"]["in"] == "query"
    assert params["offset"]["schema"]["minimum"] == 0
    assert params["offset"]["schema"]["default"] == 0
    assert params[_tenant_header()]["in"] == "header"
    # No tenant selector query parameter and no other paging surface.
    assert "tenant_id" not in params
    assert "tenant" not in params
    assert "cursor" not in params
    assert "total" not in params

    item_schema = schema["components"]["schemas"]["ActiveTaskItem"]
    assert set(item_schema["properties"]) == {
        "task_id",
        "task_type",
        "task_status",
        "created_at",
    }
    page_schema = schema["components"]["schemas"]["ActiveTaskPage"]
    assert set(page_schema["properties"]) == {"items", "has_more"}

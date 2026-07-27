from typing import Literal
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, SecretStr

from docling.datamodel.base_models import ConversionStatus
from docling.datamodel.service.requests import (
    AzureBlobSourceRequest,
    GoogleCloudStorageSourceRequest,
    GoogleDriveSourceRequest,
)
from docling.datamodel.service.responses import (
    ArtifactRef,
    DoclingTaskResult,
    DocumentArtifactItem,
    PresignedArtifactResult,
)
from docling.datamodel.service.targets import S3Target
from docling.datamodel.service.tasks import TaskType
from docling_jobkit.connectors.connector_factory import (
    SourceConnectorFactory,
    TargetConnectorFactory,
)
from docling_jobkit.connectors.source_processor import BaseSourceProcessor
from docling_jobkit.connectors.target_processor import BaseTargetProcessor
from docling_jobkit.datamodel.task import Task, validate_task
from docling_jobkit.datamodel.task_meta import TaskStatus


class PluginSource(BaseModel):
    kind: Literal["plugin_source"] = "plugin_source"
    token: SecretStr


class PluginSourceProcessor(BaseSourceProcessor):
    @classmethod
    def get_config_types(cls):
        return (PluginSource,)

    def _initialize(self):
        pass

    def _finalize(self):
        pass

    def _fetch_documents(self, *, max_file_size=None):
        del max_file_size
        return iter(())


class PluginArtifactTarget(BaseModel):
    kind: Literal["plugin_artifact"] = "plugin_artifact"
    bucket: str
    token: SecretStr


class PluginArtifactTargetProcessor(BaseTargetProcessor):
    @classmethod
    def get_config_types(cls):
        return (PluginArtifactTarget,)

    def _initialize(self):
        pass

    def _finalize(self):
        pass

    def upload_file(self, filename, target_filename, content_type):
        pass

    def upload_object(self, obj, target_filename, content_type):
        pass


class PluginArchiveTarget(PluginArtifactTarget):
    kind: Literal["plugin_archive"] = "plugin_archive"


class PluginArchiveTargetProcessor(PluginArtifactTargetProcessor):
    @classmethod
    def get_config_types(cls):
        return (PluginArchiveTarget,)

    @classmethod
    def result_mode(cls):
        return "archive"


class _FakeOrchestrator:
    def __init__(self) -> None:
        self.enqueued: list[dict] = []

    async def enqueue(self, **kwargs):
        self.enqueued.append(kwargs)
        return Task.model_construct(
            task_id="task-batch",
            task_type=kwargs["task_type"],
            sources=kwargs["sources"],
            target=kwargs["target"],
            convert_options=kwargs["convert_options"],
            callbacks=kwargs["callbacks"],
            metadata=kwargs["metadata"],
        )

    async def get_queue_position(self, task_id: str):
        del task_id
        return 0

    async def task_outcome(self, task_id: str):
        return await self.task_result(task_id)

    async def task_status(self, task_id: str):
        del task_id
        return Task(
            task_id="task-batch",
            task_type=TaskType.CONVERT,
            task_status=TaskStatus.SUCCESS,
            sources=[],
            metadata={"tenant_id": "default"},
        )

    async def task_result(self, task_id: str):
        del task_id
        return DoclingTaskResult(
            result=PresignedArtifactResult(
                documents=[
                    DocumentArtifactItem(
                        source_index=0,
                        source_uri="https://example.com/a.pdf",
                        filename="a.pdf",
                        status=ConversionStatus.SUCCESS,
                        artifacts=[
                            ArtifactRef(
                                artifact_type="markdown",
                                mime_type="text/markdown",
                                uri="s3://converted/000000-a/a.md",
                            )
                        ],
                    )
                ]
            ),
            processing_time=1.0,
            num_converted=1,
            num_succeeded=1,
            num_partially_succeeded=0,
            num_failed=0,
        )

    async def on_result_fetched(self, task_id: str):
        del task_id


@pytest.fixture
def fake_orchestrator(monkeypatch):
    from docling_serve import app as app_module

    orchestrator = _FakeOrchestrator()
    monkeypatch.setattr(
        app_module.docling_serve_settings, "artifact_storage_enabled", True
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings, "max_sources_per_request", 10
    )
    monkeypatch.setattr(app_module, "get_async_orchestrator", lambda: orchestrator)
    return orchestrator


@pytest.fixture
def app(fake_orchestrator):
    from docling_serve import app as app_module

    del fake_orchestrator
    with patch.object(app_module, "setup_otel_instrumentation"):
        return app_module.create_app()


@pytest.fixture
def plugin_factories(monkeypatch):
    from docling_jobkit.connectors import connector_factory as connector_factory_module

    from docling_serve import policy as policy_module

    builtin_source_factory = SourceConnectorFactory()
    builtin_source_factory.load_from_plugins()
    source_factory = SourceConnectorFactory()
    source_factory.load_from_plugins()
    source_factory.register(
        PluginSourceProcessor,
        "test_plugin",
        "tests.test_batch_endpoint",
    )
    builtin_target_factory = TargetConnectorFactory()
    builtin_target_factory.load_from_plugins()
    target_factory = TargetConnectorFactory()
    target_factory.load_from_plugins()
    target_factory.register(
        PluginArtifactTargetProcessor,
        "test_plugin",
        "tests.test_batch_endpoint",
    )
    target_factory.register(
        PluginArchiveTargetProcessor,
        "test_plugin",
        "tests.test_batch_endpoint",
    )
    source_factory_for = lambda allow: (  # noqa: E731
        source_factory if allow else builtin_source_factory
    )
    target_factory_for = lambda allow: (  # noqa: E731
        target_factory if allow else builtin_target_factory
    )
    monkeypatch.setattr(
        connector_factory_module,
        "get_source_connector_factory",
        source_factory_for,
    )
    monkeypatch.setattr(
        connector_factory_module,
        "get_target_connector_factory",
        target_factory_for,
    )
    monkeypatch.setattr(
        policy_module,
        "get_source_connector_factory",
        source_factory_for,
    )
    monkeypatch.setattr(
        policy_module,
        "get_target_connector_factory",
        target_factory_for,
    )


@pytest.fixture
def plugin_app(fake_orchestrator, plugin_factories, monkeypatch):
    from docling_serve import app as app_module

    del fake_orchestrator, plugin_factories
    monkeypatch.setattr(
        app_module.docling_serve_settings, "allow_external_plugins", True
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings,
        "allowed_source_types",
        ["http", "filenet", "plugin_source"],
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings,
        "allowed_target_types",
        ["s3", "presigned_url", "plugin_artifact"],
    )
    with patch.object(app_module, "setup_otel_instrumentation"):
        return app_module.create_app()


@pytest.fixture
def plugins_not_allowlisted_app(fake_orchestrator, plugin_factories, monkeypatch):
    from docling_serve import app as app_module

    del fake_orchestrator, plugin_factories
    monkeypatch.setattr(
        app_module.docling_serve_settings, "allow_external_plugins", True
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings, "allowed_source_types", ["http"]
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings, "allowed_target_types", ["s3"]
    )
    with patch.object(app_module, "setup_otel_instrumentation"):
        return app_module.create_app()


@pytest.mark.asyncio
async def test_batch_endpoint_rejects_s3_source_with_presigned_target(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [
                    {
                        "kind": "s3",
                        "endpoint": "s3.example.com",
                        "access_key": "key",
                        "secret_key": "secret",
                        "bucket": "documents",
                    }
                ],
                "target": {"kind": "presigned_url"},
            },
        )

    assert response.status_code == 422
    assert "require a storage target" in response.text


@pytest.mark.asyncio
async def test_batch_endpoint_accepts_s3_source_with_s3_target(app, fake_orchestrator):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [
                    {
                        "kind": "s3",
                        "endpoint": "s3.example.com",
                        "access_key": "key",
                        "secret_key": "secret",
                        "bucket": "documents",
                    }
                ],
                "target": {
                    "kind": "s3",
                    "endpoint": "s3.example.com",
                    "access_key": "key",
                    "secret_key": "secret",
                    "bucket": "converted",
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["task_type"] == TaskType.CONVERT
    assert len(fake_orchestrator.enqueued[0]["sources"]) == 1
    assert isinstance(fake_orchestrator.enqueued[0]["target"], S3Target)


@pytest.mark.asyncio
async def test_batch_endpoint_accepts_http_source_with_presigned_target(
    app, fake_orchestrator
):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [
                    {"kind": "http", "url": "https://example.com/a.pdf"},
                    {"kind": "http", "url": "https://example.com/b.pdf"},
                ],
                "target": {"kind": "presigned_url"},
            },
        )

    assert response.status_code == 200
    assert len(fake_orchestrator.enqueued[0]["sources"]) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("source_payload", "expected_type"),
    [
        (
            {
                "kind": "azure_blob",
                "account_name": "acct",
                "container": "incoming",
                "connection_string": "UseDevelopmentStorage=true",
            },
            AzureBlobSourceRequest,
        ),
        (
            {
                "kind": "google_cloud_storage",
                "bucket": "incoming",
            },
            GoogleCloudStorageSourceRequest,
        ),
        (
            {
                "kind": "google_drive",
                "path_id": "folder-123",
                "refresh_token": "refresh-token",
                "credentials_path": "/tmp/client-secret.json",
            },
            GoogleDriveSourceRequest,
        ),
    ],
)
async def test_batch_endpoint_accepts_new_expandable_sources_with_storage_target(
    app,
    fake_orchestrator,
    source_payload,
    expected_type,
):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [source_payload],
                "target": {
                    "kind": "s3",
                    "endpoint": "s3.example.com",
                    "access_key": "key",
                    "secret_key": "secret",
                    "bucket": "converted",
                },
            },
        )

    assert response.status_code == 200
    assert type(fake_orchestrator.enqueued[-1]["sources"][0]) is expected_type


@pytest.mark.asyncio
async def test_batch_endpoint_rejects_zip_target(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [{"kind": "http", "url": "https://example.com/a.pdf"}],
                "target": {"kind": "zip"},
            },
        )

    assert response.status_code == 422
    assert "zip" in response.text


@pytest.mark.asyncio
async def test_task_result_returns_presigned_artifact_response(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.get("/v1/result/task-batch")

    assert response.status_code == 200
    payload = response.json()
    assert payload["num_partially_succeeded"] == 0
    assert payload["documents"][0]["source_index"] == 0


@pytest.mark.asyncio
async def test_batch_endpoint_resolves_plugin_source_and_target(
    plugin_app, fake_orchestrator
):
    async with AsyncClient(
        transport=ASGITransport(app=plugin_app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [
                    {
                        "kind": "filenet",
                        "base_url": "https://filenet.example.com/graphql",
                        "username": "user",
                        "api_key": "source-secret",
                        "repository_id": "repo",
                    },
                    {"kind": "plugin_source", "token": "external-source-secret"},
                ],
                "target": {
                    "kind": "plugin_artifact",
                    "bucket": "converted",
                    "token": "target-secret",
                },
            },
        )
        openapi = (await client.get("/openapi.json")).json()
        openapi_30 = (await client.get("/openapi-3.0.json")).json()

    from docling_jobkit.connectors.filenet.models import TaskFileNetSource

    assert response.status_code == 200
    assert type(fake_orchestrator.enqueued[-1]["sources"][0]) is TaskFileNetSource
    assert type(fake_orchestrator.enqueued[-1]["sources"][1]) is PluginSource
    assert type(fake_orchestrator.enqueued[-1]["target"]) is PluginArtifactTarget
    schemas = openapi["components"]["schemas"]
    assert "TaskFileNetSource" in schemas
    assert "PluginSource" in schemas
    assert "PluginArtifactTarget" in schemas
    assert "PluginArchiveTarget" not in schemas
    assert "GenericSourceRequest" not in schemas
    assert "GenericTargetRequest" not in schemas
    batch_schema = schemas["BatchConvertSourcesRequest"]["properties"]
    assert batch_schema["sources"]["items"]["discriminator"]["mapping"][
        "filenet"
    ].endswith("/TaskFileNetSource")
    assert batch_schema["target"]["discriminator"]["mapping"][
        "plugin_artifact"
    ].endswith("/PluginArtifactTarget")
    api_key_schema = schemas["TaskFileNetSource"]["properties"]["api_key"]
    assert api_key_schema["format"] == "password"
    assert api_key_schema["writeOnly"] is True
    assert openapi_30["components"]["schemas"]["PluginArtifactTarget"]["properties"][
        "kind"
    ]["enum"] == ["plugin_artifact"]


@pytest.mark.asyncio
async def test_plugin_validation_does_not_echo_credentials(plugin_app):
    async with AsyncClient(
        transport=ASGITransport(app=plugin_app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [
                    {
                        "kind": "filenet",
                        "base_url": "https://filenet.example.com/graphql",
                        "api_key": "source-secret",
                    }
                ],
                "target": {
                    "kind": "plugin_artifact",
                    "token": "target-secret",
                },
            },
        )

    assert response.status_code == 422
    assert "source-secret" not in response.text
    assert "target-secret" not in response.text


@pytest.mark.asyncio
async def test_expandable_plugin_source_requires_artifact_target(plugin_app):
    async with AsyncClient(
        transport=ASGITransport(app=plugin_app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [{"kind": "plugin_source", "token": "secret"}],
                "target": {"kind": "presigned_url"},
            },
        )

    assert response.status_code == 422
    assert "artifact result mode" in response.text


@pytest.mark.asyncio
async def test_registered_plugins_absent_from_allowlists_fail_at_boundary(
    plugins_not_allowlisted_app,
):
    async with AsyncClient(
        transport=ASGITransport(app=plugins_not_allowlisted_app),
        base_url="http://app.io",
    ) as client:
        source_response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [{"kind": "plugin_source", "token": "secret"}],
                "target": {
                    "kind": "s3",
                    "endpoint": "s3.example.com",
                    "access_key": "key",
                    "secret_key": "secret",
                    "bucket": "converted",
                },
            },
        )
        target_response = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [{"kind": "http", "url": "https://example.com/a.pdf"}],
                "target": {
                    "kind": "plugin_artifact",
                    "bucket": "converted",
                    "token": "secret",
                },
            },
        )

    assert source_response.status_code == 422
    assert target_response.status_code == 422


@pytest.mark.parametrize(
    ("allowed_sources", "allowed_targets", "expected"),
    [
        (["plugin_source"], ["s3"], "plugin_source"),
        (["http"], ["plugin_artifact"], "plugin_artifact"),
    ],
)
def test_external_connectors_require_plugin_enablement(
    fake_orchestrator,
    plugin_factories,
    monkeypatch,
    allowed_sources,
    allowed_targets,
    expected,
):
    from docling_serve import app as app_module

    del fake_orchestrator, plugin_factories
    monkeypatch.setattr(
        app_module.docling_serve_settings, "allow_external_plugins", False
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings, "allowed_source_types", allowed_sources
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings, "allowed_target_types", allowed_targets
    )

    with pytest.raises(ValueError, match=expected):
        app_module.create_app()


def test_archive_plugin_target_is_unavailable_remotely(
    fake_orchestrator, plugin_factories, monkeypatch
):
    from docling_serve import app as app_module

    del fake_orchestrator, plugin_factories
    monkeypatch.setattr(
        app_module.docling_serve_settings, "allow_external_plugins", True
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings, "allowed_source_types", ["http"]
    )
    monkeypatch.setattr(
        app_module.docling_serve_settings,
        "allowed_target_types",
        ["plugin_archive"],
    )

    with pytest.raises(ValueError, match="plugin_archive"):
        app_module.create_app()


@pytest.mark.asyncio
async def test_default_schema_excludes_plugins_and_local_path(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        openapi = await client.get("/openapi.json")

    schema = openapi.text
    assert "TaskFileNetSource" not in schema
    assert "plugin_source" not in schema
    assert "plugin_artifact" not in schema
    assert "local_path" not in schema


@pytest.mark.asyncio
async def test_non_batch_convert_enqueues_kind_bearing_sources(app, fake_orchestrator):
    # The fake orchestrator bypasses validate_task, so assert the enqueued sources
    # survive the real Task resolver the local/RQ/Ray orchestrators run at enqueue.
    # A kind-less FileSource/HttpSource (the pre-fix output) fails that resolver.
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://app.io"
    ) as client:
        response = await client.post(
            "/v1/convert/source/async",
            json={
                "sources": [
                    {"kind": "http", "url": "https://example.com/a.pdf"},
                    {"kind": "file", "base64_string": "aGVsbG8=", "filename": "a.pdf"},
                ],
                "target": {"kind": "inbody"},
            },
        )

    assert response.status_code == 200, response.text
    sources = fake_orchestrator.enqueued[0]["sources"]
    assert [getattr(s, "kind", None) for s in sources] == ["http", "file"]
    # Reconstructs without raising "requires a non-empty string `kind`".
    validate_task({"task_id": "t", "sources": sources, "target": {"kind": "inbody"}})


@pytest.mark.asyncio
async def test_convert_source_accepts_file_when_file_excluded_from_allowed_source_types(
    fake_orchestrator, monkeypatch
):
    # When allowed_source_types excludes 'file', the batch endpoint must reject
    # it (schema-level, no 'file' in discriminated union), but the convert
    # endpoint must still accept it because inline kinds are always valid there.
    from unittest.mock import patch

    from docling_serve import app as app_module

    monkeypatch.setattr(
        app_module.docling_serve_settings, "allowed_source_types", ["http", "s3"]
    )
    with patch.object(app_module, "setup_otel_instrumentation"):
        restricted_app = app_module.create_app()

    async with AsyncClient(
        transport=ASGITransport(app=restricted_app), base_url="http://app.io"
    ) as client:
        # Batch endpoint must reject file (schema-level 422).
        batch_resp = await client.post(
            "/v1/convert/source/batch",
            json={
                "sources": [
                    {"kind": "file", "base64_string": "aGVsbG8=", "filename": "a.pdf"}
                ],
                "target": {
                    "kind": "s3",
                    "endpoint": "s3.example.com",
                    "access_key": "key",
                    "secret_key": "secret",
                    "bucket": "converted",
                },
            },
        )
        assert batch_resp.status_code == 422, batch_resp.text

        # Convert endpoint must accept file regardless.
        convert_resp = await client.post(
            "/v1/convert/source/async",
            json={
                "sources": [
                    {"kind": "file", "base64_string": "aGVsbG8=", "filename": "a.pdf"}
                ],
                "target": {"kind": "inbody"},
            },
        )
        assert convert_resp.status_code == 200, convert_resp.text

    sources = fake_orchestrator.enqueued[0]["sources"]
    assert getattr(sources[0], "kind", None) == "file"

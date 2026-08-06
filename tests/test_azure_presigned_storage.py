from unittest.mock import MagicMock

import pytest

from docling_jobkit.config.target_config import AzurePresignedConfig

from docling_serve import orchestrator_factory
from docling_serve.settings import DoclingServeSettings


def _configure_azure(monkeypatch):
    settings = orchestrator_factory.docling_serve_settings
    monkeypatch.setattr(settings, "artifact_storage_enabled", True)
    monkeypatch.setattr(settings, "artifact_storage_backend", "azure")
    monkeypatch.setattr(
        settings,
        "artifact_storage_azure_connection_string",
        "AccountName=acct;AccountKey=dGVzdA==;",
    )
    monkeypatch.setattr(settings, "artifact_storage_azure_container", "artifacts")
    monkeypatch.setattr(settings, "artifact_storage_azure_account_name", "acct")
    monkeypatch.setattr(settings, "artifact_storage_azure_blob_prefix", "converted/")
    monkeypatch.setattr(settings, "artifact_storage_presign_ttl_seconds", 900)


def test_build_presigned_config_builds_azure_config(monkeypatch):
    _configure_azure(monkeypatch)

    config = orchestrator_factory._build_presigned_config()

    assert isinstance(config, AzurePresignedConfig)
    assert config.azure_coords.container == "artifacts"
    assert config.azure_coords.blob_prefix == "converted/"
    assert config.url_expiration == 900


def test_build_presigned_config_rejects_missing_azure_settings(monkeypatch):
    settings = orchestrator_factory.docling_serve_settings
    monkeypatch.setattr(settings, "artifact_storage_enabled", True)
    monkeypatch.setattr(settings, "artifact_storage_backend", "azure")

    with pytest.raises(
        ValueError,
        match="DOCLING_SERVE_ARTIFACT_STORAGE_AZURE_CONNECTION_STRING",
    ):
        orchestrator_factory._build_presigned_config()


def test_settings_reject_unknown_artifact_storage_backend():
    with pytest.raises(ValueError, match="artifact_storage_backend"):
        DoclingServeSettings(artifact_storage_backend="other")


def test_rq_worker_passes_generic_presigned_config(monkeypatch):
    from docling_jobkit.orchestrators.rq.orchestrator import RQOrchestrator

    from docling_serve import logging_config, rq_worker_instrumented
    from docling_serve.__main__ import rq_worker

    _configure_azure(monkeypatch)
    captured: dict[str, object] = {}

    class _Worker:
        def __init__(self, *_args, **kwargs):
            captured.update(kwargs)

        def work(self):
            return None

    monkeypatch.setattr(logging_config, "setup_logging", lambda **_kwargs: None)
    monkeypatch.setattr(
        RQOrchestrator,
        "make_rq_queue",
        lambda _config: (MagicMock(), MagicMock()),
    )
    monkeypatch.setattr(rq_worker_instrumented, "InstrumentedRQWorker", _Worker)

    rq_worker()

    config = captured["orchestrator_config"]
    assert isinstance(config.presigned_config, AzurePresignedConfig)

"""Tests for RQ job_timeout configuration in docling-serve."""

from unittest.mock import patch

from docling_serve import orchestrator_factory
from docling_serve.settings import DoclingServeSettings


class _CapturedConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_default_job_timeout_preserves_existing_behavior():
    settings = DoclingServeSettings(eng_rq_redis_url="redis://localhost:6379/")

    assert settings.eng_rq_job_timeout == 3_600 * 4


def test_job_timeout_is_configurable():
    settings = DoclingServeSettings(
        eng_rq_redis_url="redis://localhost:6379/",
        eng_rq_job_timeout=86_400,
    )

    assert settings.eng_rq_job_timeout == 86_400


def test_job_timeout_is_loaded_from_env(monkeypatch):
    monkeypatch.setenv("DOCLING_SERVE_ENG_RQ_JOB_TIMEOUT", "-1")

    settings = DoclingServeSettings(eng_rq_redis_url="redis://localhost:6379/")

    assert settings.eng_rq_job_timeout == -1


def test_job_timeout_is_passed_to_the_orchestrator_config(monkeypatch):
    monkeypatch.setattr(
        orchestrator_factory.docling_serve_settings,
        "eng_rq_job_timeout",
        86_400,
    )
    with patch(
        "docling_jobkit.orchestrators.rq.orchestrator.RQOrchestratorConfig",
        _CapturedConfig,
    ):
        config = orchestrator_factory._build_rq_config()

    assert config.job_timeout == 86_400

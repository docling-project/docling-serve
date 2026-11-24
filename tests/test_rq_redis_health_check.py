"""Tests for the RQ Redis pool health check configuration in docling-serve."""

from unittest.mock import patch

from docling_jobkit.orchestrators.rq.orchestrator import RQOrchestratorConfig

from docling_serve import orchestrator_factory
from docling_serve.settings import DoclingServeSettings


class _CapturedConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_default_health_check_interval_matches_jobkit():
    settings = DoclingServeSettings(eng_rq_redis_url="redis://localhost:6379/")

    assert (
        settings.eng_rq_redis_health_check_interval
        == RQOrchestratorConfig.model_fields["redis_health_check_interval"].default
    )


def test_health_check_interval_is_loaded_from_env(monkeypatch):
    monkeypatch.setenv("DOCLING_SERVE_ENG_RQ_REDIS_HEALTH_CHECK_INTERVAL", "0")

    settings = DoclingServeSettings(eng_rq_redis_url="redis://localhost:6379/")

    assert settings.eng_rq_redis_health_check_interval == 0


def test_health_check_interval_is_passed_to_the_orchestrator_config(monkeypatch):
    monkeypatch.setattr(
        orchestrator_factory.docling_serve_settings,
        "eng_rq_redis_health_check_interval",
        5.0,
    )
    with patch(
        "docling_jobkit.orchestrators.rq.orchestrator.RQOrchestratorConfig",
        _CapturedConfig,
    ):
        config = orchestrator_factory._build_rq_config()

    assert config.redis_health_check_interval == 5.0

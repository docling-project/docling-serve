"""Tests for RQ queue_name configuration in docling-serve."""

from docling_serve.settings import DoclingServeSettings


def test_default_queue_name_is_convert():
    settings = DoclingServeSettings(eng_rq_redis_url="redis://localhost:6379/")

    assert settings.eng_rq_queue_name == "convert"


def test_queue_name_is_configurable():
    settings = DoclingServeSettings(
        eng_rq_redis_url="redis://localhost:6379/",
        eng_rq_queue_name="dev-convert",
    )

    assert settings.eng_rq_queue_name == "dev-convert"


def test_queue_name_is_loaded_from_env(monkeypatch):
    monkeypatch.setenv("DOCLING_SERVE_ENG_RQ_QUEUE_NAME", "test-convert")

    settings = DoclingServeSettings(eng_rq_redis_url="redis://localhost:6379/")

    assert settings.eng_rq_queue_name == "test-convert"


def test_queue_name_is_loaded_from_config_file(monkeypatch, tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("eng_rq_queue_name: stage-convert\n")
    monkeypatch.setenv("DOCLING_SERVE_CONFIG_FILE", str(config_path))

    settings = DoclingServeSettings(eng_rq_redis_url="redis://localhost:6379/")

    assert settings.eng_rq_queue_name == "stage-convert"

"""ASR options for audio and video inputs reach the converter manager."""

import json

from docling.datamodel.pipeline_options_asr_model import ApiAsrOptions

from docling_serve.orchestrator_factory import _build_cm_config
from docling_serve.settings import DoclingServeSettings, docling_serve_settings

ASR_OPTIONS = {
    "url": "http://localhost:8000/v1/audio/transcriptions",
    "model": "whisper-large-v3-turbo",
    "headers": {"Authorization": "Bearer test"},
}


def test_asr_options_from_json_env(monkeypatch):
    monkeypatch.setenv("DOCLING_SERVE_ASR_OPTIONS", json.dumps(ASR_OPTIONS))

    settings = DoclingServeSettings()
    assert settings.asr_options == ASR_OPTIONS


def test_asr_options_default_unset():
    assert DoclingServeSettings().asr_options is None


def test_asr_options_passed_to_converter_manager(monkeypatch):
    monkeypatch.setattr(docling_serve_settings, "enable_remote_services", True)
    monkeypatch.setattr(docling_serve_settings, "asr_options", ASR_OPTIONS)

    asr_options = _build_cm_config().asr_options
    assert isinstance(asr_options, ApiAsrOptions)
    assert str(asr_options.url) == ASR_OPTIONS["url"]
    assert asr_options.model == ASR_OPTIONS["model"]

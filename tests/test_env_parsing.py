"""Tests for environment variable parsing in docling-serve settings."""

import json

from docling_serve.settings import DoclingServeSettings


def test_dict_from_json(monkeypatch):
    """Test parsing dict parameters from JSON strings."""
    preset_config = {"my_preset": {"engine": "openai"}}
    monkeypatch.setenv("DOCLING_SERVE_CUSTOM_VLM_PRESETS", json.dumps(preset_config))

    settings = DoclingServeSettings()
    assert settings.custom_vlm_presets == preset_config


def test_list_from_json_array(monkeypatch):
    """Test parsing list from JSON array."""
    presets = ["preset1", "preset2"]
    monkeypatch.setenv("DOCLING_SERVE_ALLOWED_VLM_PRESETS", json.dumps(presets))

    settings = DoclingServeSettings()
    assert settings.allowed_vlm_presets == presets


def test_list_from_csv(monkeypatch):
    """Test parsing list from comma-separated string."""
    monkeypatch.setenv("DOCLING_SERVE_ALLOWED_VLM_PRESETS", "preset1,preset2,preset3")

    settings = DoclingServeSettings()
    assert settings.allowed_vlm_presets == ["preset1", "preset2", "preset3"]


def test_list_csv_trims_whitespace(monkeypatch):
    """Test CSV parsing trims whitespace."""
    monkeypatch.setenv("DOCLING_SERVE_ALLOWED_VLM_ENGINES", "openai , anthropic")

    settings = DoclingServeSettings()
    assert settings.allowed_vlm_engines == ["openai", "anthropic"]


def test_default_values():
    """Test default values for new parameters."""
    settings = DoclingServeSettings()

    assert settings.default_vlm_preset == "granite_docling"
    assert settings.default_picture_description_preset == "smolvlm"
    assert settings.default_code_formula_preset == "default"
    assert settings.default_table_structure_kind == "docling_tableformer"
    assert settings.default_layout_kind == "docling_layout_default"

    assert settings.allowed_vlm_presets is None
    assert settings.custom_vlm_presets == {}

    # preload_pipelines defaults to None, normalized to ["pdf"] by model validator
    assert settings.preload_pipelines == ["pdf"]


def test_preload_pipelines_from_json_array(monkeypatch):
    """Test parsing preload_pipelines from JSON array."""
    monkeypatch.setenv("DOCLING_SERVE_PRELOAD_PIPELINES", '["pdf", "audio"]')

    settings = DoclingServeSettings()
    assert settings.preload_pipelines == ["pdf", "audio"]


def test_preload_pipelines_from_csv(monkeypatch):
    """Test parsing preload_pipelines from comma-separated string."""
    monkeypatch.setenv("DOCLING_SERVE_PRELOAD_PIPELINES", "pdf,audio")

    settings = DoclingServeSettings()
    assert settings.preload_pipelines == ["pdf", "audio"]


def test_preload_pipelines_lowercased(monkeypatch):
    """Test that preload_pipelines values are lowercased."""
    monkeypatch.setenv("DOCLING_SERVE_PRELOAD_PIPELINES", '["PDF", "AUDIO"]')

    settings = DoclingServeSettings()
    assert settings.preload_pipelines == ["pdf", "audio"]


def test_preload_pipelines_always_includes_pdf(monkeypatch):
    """Test that pdf is always included in preload_pipelines."""
    monkeypatch.setenv("DOCLING_SERVE_PRELOAD_PIPELINES", '["audio"]')

    settings = DoclingServeSettings()
    assert "pdf" in settings.preload_pipelines
    assert "audio" in settings.preload_pipelines


def test_preload_pipelines_yaml_config(monkeypatch):
    """Test loading preload_pipelines from YAML config file."""
    import tempfile
    from pathlib import Path

    import yaml

    config_data = {"preload_pipelines": ["pdf", "audio"]}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        config_path = f.name

    try:
        monkeypatch.setenv("DOCLING_SERVE_CONFIG_FILE", config_path)
        settings = DoclingServeSettings()
        assert settings.preload_pipelines == ["pdf", "audio"]
    finally:
        Path(config_path).unlink()


def test_preload_pipelines_gated_by_load_models_at_boot(monkeypatch):
    """preload_pipelines is still parsed, but the caller gates on load_models_at_boot.

    The setting itself is always available (so config validation works), but
    orchestrator_factory and __main__ pass an empty preload_formats list to
    docling-jobkit when load_models_at_boot is False.  This test verifies
    the setting values are independent so the gating logic can work.
    """
    monkeypatch.setenv("DOCLING_SERVE_LOAD_MODELS_AT_BOOT", "false")
    monkeypatch.setenv("DOCLING_SERVE_PRELOAD_PIPELINES", '["pdf", "audio"]')

    settings = DoclingServeSettings()
    assert settings.load_models_at_boot is False
    assert settings.preload_pipelines == ["pdf", "audio"]

    # The gating logic in orchestrator_factory.py / __main__.py is:
    # preload_formats = list(settings.preload_pipelines) if settings.load_models_at_boot else []
    gated = list(settings.preload_pipelines) if settings.load_models_at_boot else []
    assert gated == []

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

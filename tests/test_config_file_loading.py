"""Tests for configuration file loading in docling-serve settings."""

import json
import tempfile
from pathlib import Path

import yaml

from docling_serve.settings import DoclingServeSettings


def test_load_yaml_config(monkeypatch):
    """Test loading configuration from YAML file."""
    config_data = {
        "default_vlm_preset": "custom_preset",
        "allowed_vlm_presets": ["preset1", "preset2"],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        config_path = f.name

    try:
        monkeypatch.setenv("DOCLING_SERVE_CONFIG_FILE", config_path)
        settings = DoclingServeSettings()

        assert settings.default_vlm_preset == "custom_preset"
        assert settings.allowed_vlm_presets == ["preset1", "preset2"]
    finally:
        Path(config_path).unlink()


def test_load_json_config(monkeypatch):
    """Test loading configuration from JSON file."""
    config_data = {"default_picture_description_preset": "json_preset"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(config_data, f)
        config_path = f.name

    try:
        monkeypatch.setenv("DOCLING_SERVE_CONFIG_FILE", config_path)
        settings = DoclingServeSettings()

        assert settings.default_picture_description_preset == "json_preset"
    finally:
        Path(config_path).unlink()


def test_env_overrides_config_file(monkeypatch):
    """Test that ENV variables override config file values."""
    config_data = {"default_vlm_preset": "config_value"}

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(config_data, f)
        config_path = f.name

    try:
        monkeypatch.setenv("DOCLING_SERVE_CONFIG_FILE", config_path)
        monkeypatch.setenv("DOCLING_SERVE_DEFAULT_VLM_PRESET", "env_value")

        settings = DoclingServeSettings()
        assert settings.default_vlm_preset == "env_value"
    finally:
        Path(config_path).unlink()


def test_nonexistent_config_file_ignored(monkeypatch):
    """Test that nonexistent config file is silently ignored."""
    monkeypatch.setenv("DOCLING_SERVE_CONFIG_FILE", "/nonexistent/config.yaml")

    settings = DoclingServeSettings()
    assert settings.default_vlm_preset == "granite_docling"


def test_invalid_yaml_ignored(monkeypatch):
    """Test that invalid YAML is silently ignored."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("invalid: yaml: [")
        config_path = f.name

    try:
        monkeypatch.setenv("DOCLING_SERVE_CONFIG_FILE", config_path)
        settings = DoclingServeSettings()
        assert settings.default_vlm_preset == "granite_docling"
    finally:
        Path(config_path).unlink()

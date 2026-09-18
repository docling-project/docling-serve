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


def test_allowed_target_types_from_csv(monkeypatch):
    monkeypatch.setenv(
        "DOCLING_SERVE_ALLOWED_TARGET_TYPES", "zip, presigned_url , inbody"
    )

    settings = DoclingServeSettings()

    assert settings.allowed_target_types == ["zip", "presigned_url", "inbody"]


def test_allowed_source_types_from_csv(monkeypatch):
    monkeypatch.setenv("DOCLING_SERVE_ALLOWED_SOURCE_TYPES", "http, s3")

    settings = DoclingServeSettings()

    assert settings.allowed_source_types == ["http", "s3"]


def test_default_values():
    """Test default values for new parameters."""
    settings = DoclingServeSettings()

    assert settings.default_vlm_preset == "granite_docling"
    assert settings.default_picture_description_preset == "smolvlm"
    assert settings.default_code_formula_preset == "default"
    assert settings.default_chart_extraction_preset == "granite_vision_v4"
    assert settings.default_table_structure_kind == "docling_tableformer"
    assert settings.default_layout_kind == "docling_layout_default"

    assert settings.allowed_vlm_presets is None
    assert settings.custom_vlm_presets == {}
    assert settings.allowed_chart_extraction_presets is None
    assert settings.custom_chart_extraction_presets == {}
    assert settings.allowed_chart_extraction_engines is None
    assert settings.debug_error_details is False


def test_debug_error_details_from_env(monkeypatch):
    monkeypatch.setenv("DOCLING_SERVE_DEBUG_ERROR_DETAILS", "true")

    settings = DoclingServeSettings()

    assert settings.debug_error_details is True


def test_deprecated_ray_setting_aliases(caplog):
    settings = DoclingServeSettings(
        eng_ray_num_cpus_per_actor=3.0,
        eng_ray_memory_limit_per_actor="8Gi",
    )

    assert settings.eng_ray_converter_actor_num_cpus == 3.0
    assert settings.eng_ray_converter_actor_memory_request == "8Gi"
    assert "eng_ray_num_cpus_per_actor is deprecated" in caplog.text
    assert "eng_ray_memory_limit_per_actor is deprecated" in caplog.text


def test_new_ray_settings_override_deprecated_aliases():
    settings = DoclingServeSettings(
        eng_ray_converter_actor_num_cpus=4.0,
        eng_ray_num_cpus_per_actor=2.0,
        eng_ray_converter_actor_memory_request="10Gi",
        eng_ray_memory_limit_per_actor="8Gi",
    )

    assert settings.eng_ray_converter_actor_num_cpus == 4.0
    assert settings.eng_ray_converter_actor_memory_request == "10Gi"


def test_prefixed_env_var_converter_num_cpus(monkeypatch):
    monkeypatch.setenv("DOCLING_SERVE_ENG_RAY_CONVERTER_ACTOR_NUM_CPUS", "4")
    settings = DoclingServeSettings()
    assert settings.eng_ray_converter_actor_num_cpus == 4.0


def test_prefixed_env_var_converter_memory_request(monkeypatch):
    monkeypatch.setenv("DOCLING_SERVE_ENG_RAY_CONVERTER_ACTOR_MEMORY_REQUEST", "6Gi")
    settings = DoclingServeSettings()
    assert settings.eng_ray_converter_actor_memory_request == "6Gi"


def test_prefixed_env_var_deprecated_aliases(monkeypatch):
    monkeypatch.setenv("DOCLING_SERVE_ENG_RAY_NUM_CPUS_PER_ACTOR", "3")
    monkeypatch.setenv("DOCLING_SERVE_ENG_RAY_MEMORY_LIMIT_PER_ACTOR", "8Gi")
    settings = DoclingServeSettings()
    assert settings.eng_ray_converter_actor_num_cpus == 3.0
    assert settings.eng_ray_converter_actor_memory_request == "8Gi"


def test_ray_metrics_defaults():
    settings = DoclingServeSettings()
    assert settings.eng_ray_generate_metrics is False
    assert settings.eng_ray_metrics_port == 8090


def test_ray_metrics_from_env(monkeypatch):
    monkeypatch.setenv("DOCLING_SERVE_ENG_RAY_GENERATE_METRICS", "true")
    monkeypatch.setenv("DOCLING_SERVE_ENG_RAY_METRICS_PORT", "9090")
    settings = DoclingServeSettings()
    assert settings.eng_ray_generate_metrics is True
    assert settings.eng_ray_metrics_port == 9090


def test_chart_extraction_list_from_json(monkeypatch):
    """Test allowed_chart_extraction_presets parses from JSON array."""
    import json as _json

    presets = ["granite_vision_v4", "granite_vision"]
    monkeypatch.setenv(
        "DOCLING_SERVE_ALLOWED_CHART_EXTRACTION_PRESETS", _json.dumps(presets)
    )
    settings = DoclingServeSettings()
    assert settings.allowed_chart_extraction_presets == presets


def test_chart_extraction_list_from_csv(monkeypatch):
    """Test allowed_chart_extraction_presets parses from comma-separated string."""
    monkeypatch.setenv(
        "DOCLING_SERVE_ALLOWED_CHART_EXTRACTION_PRESETS",
        "granite_vision_v4,granite_vision",
    )
    settings = DoclingServeSettings()
    assert settings.allowed_chart_extraction_presets == [
        "granite_vision_v4",
        "granite_vision",
    ]


def test_chart_extraction_engines_from_csv(monkeypatch):
    """Test allowed_chart_extraction_engines parses from comma-separated string."""
    monkeypatch.setenv(
        "DOCLING_SERVE_ALLOWED_CHART_EXTRACTION_ENGINES", "transformers,api_openai"
    )
    settings = DoclingServeSettings()
    assert settings.allowed_chart_extraction_engines == ["transformers", "api_openai"]


def test_custom_chart_extraction_presets_from_json(monkeypatch):
    """Test custom_chart_extraction_presets parses from JSON string."""
    import json as _json

    preset_config = {
        "my_chart_preset": {"engine_options": {"engine_type": "api_openai"}}
    }
    monkeypatch.setenv(
        "DOCLING_SERVE_CUSTOM_CHART_EXTRACTION_PRESETS", _json.dumps(preset_config)
    )
    settings = DoclingServeSettings()
    assert settings.custom_chart_extraction_presets == preset_config

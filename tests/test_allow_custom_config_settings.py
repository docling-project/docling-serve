"""Tests for allow_custom_*_config settings in docling-serve."""

from docling_serve.settings import DoclingServeSettings


class TestAllowCustomConfigSettings:
    def test_allow_custom_vlm_config_defaults_false(self):
        settings = DoclingServeSettings()
        assert settings.allow_custom_vlm_config is False

    def test_allow_custom_picture_description_config_defaults_false(self):
        settings = DoclingServeSettings()
        assert settings.allow_custom_picture_description_config is False

    def test_allow_custom_code_formula_config_defaults_false(self):
        settings = DoclingServeSettings()
        assert settings.allow_custom_code_formula_config is False

    def test_allow_custom_vlm_config_is_configurable(self):
        settings = DoclingServeSettings(allow_custom_vlm_config=True)
        assert settings.allow_custom_vlm_config is True

    def test_allow_custom_picture_description_config_is_configurable(self):
        settings = DoclingServeSettings(allow_custom_picture_description_config=True)
        assert settings.allow_custom_picture_description_config is True

    def test_allow_custom_code_formula_config_is_configurable(self):
        settings = DoclingServeSettings(allow_custom_code_formula_config=True)
        assert settings.allow_custom_code_formula_config is True

import pytest

from docling.datamodel.layout_model_specs import LayoutModelType

from docling_serve.datamodel.convert import (
    LAYOUT_MODEL_SPECS,
    ConvertDocumentsRequestOptions,
)


class TestLayoutModelExpansion:
    """Test that the layout_model field correctly expands into layout_custom_config."""

    def test_layout_model_expands_to_custom_config(self):
        opts = ConvertDocumentsRequestOptions(
            layout_model=LayoutModelType.DOCLING_LAYOUT_EGRET_LARGE,
        )
        assert opts.layout_custom_config is not None
        assert opts.layout_custom_config["kind"] == "docling_layout_default"
        spec = opts.layout_custom_config["model_spec"]
        assert spec["name"] == "docling_layout_egret_large"
        assert "docling-project" in spec["repo_id"]

    def test_layout_model_all_types_expand(self):
        for model_type in LayoutModelType:
            opts = ConvertDocumentsRequestOptions(layout_model=model_type)
            assert opts.layout_custom_config is not None
            expected_spec = LAYOUT_MODEL_SPECS[model_type].model_dump(mode="json")
            assert opts.layout_custom_config["model_spec"] == expected_spec

    def test_layout_custom_config_takes_precedence(self):
        custom_config = {
            "kind": "custom_layout_model",
            "model_path": "/my/custom/model",
        }
        opts = ConvertDocumentsRequestOptions(
            layout_model=LayoutModelType.DOCLING_LAYOUT_EGRET_LARGE,
            layout_custom_config=custom_config,
        )
        assert opts.layout_custom_config == custom_config

    def test_layout_model_none_leaves_config_unset(self):
        opts = ConvertDocumentsRequestOptions(layout_model=None)
        assert opts.layout_custom_config is None

    def test_layout_model_string_value_accepted(self):
        opts = ConvertDocumentsRequestOptions(
            **{"layout_model": "docling_layout_heron"}
        )
        assert opts.layout_custom_config is not None
        assert opts.layout_custom_config["model_spec"]["name"] == "docling_layout_heron"

    def test_invalid_layout_model_rejected(self):
        with pytest.raises(ValueError):
            ConvertDocumentsRequestOptions(
                **{"layout_model": "nonexistent_model"}
            )

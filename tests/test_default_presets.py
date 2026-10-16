import pytest

from docling_jobkit.convert.manager import DoclingConverterManager
from docling_jobkit.datamodel.convert import ConvertDocumentsOptions

from docling_serve.orchestrator_factory import _build_cm_config


@pytest.mark.parametrize(
    "request_options, parser_name",
    [
        ({"vlm_pipeline_preset": "default"}, "_parse_vlm_options"),
        (
            {"picture_description_preset": "default"},
            "_parse_picture_description_options",
        ),
        ({"code_formula_preset": "default"}, "_parse_code_formula_options"),
        ({"do_formula_enrichment": True}, "_parse_code_formula_options"),
        ({"do_code_enrichment": True}, "_parse_code_formula_options"),
        ({"table_structure_preset": "default"}, "_parse_table_structure_options"),
        ({"layout_preset": "default"}, "_parse_layout_options"),
        ({"ocr_preset": "default"}, "_parse_ocr_options"),
    ],
)
def test_default_presets_resolve_with_stock_settings(request_options, parser_name):
    """Every default_*_preset setting must name a real Docling preset.

    The converter manager maps the alias "default" onto the configured
    default_<stage>_preset, and code/formula enrichment resolves "default"
    whenever it is enabled. A setting left at the alias itself cannot be
    resolved, so every such request fails on a stock deployment.
    """
    manager = DoclingConverterManager(_build_cm_config())

    request = ConvertDocumentsOptions(**request_options)

    assert getattr(manager, parser_name)(request) is not None

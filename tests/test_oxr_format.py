"""Contract tests for the OXR input format shared with Docling."""

from docling.datamodel.base_models import InputFormat
from docling.datamodel.service.options import ConvertDocumentsOptions


def test_convert_options_accept_the_oxr_format() -> None:
    options = ConvertDocumentsOptions(from_formats=["oxr"])

    assert options.from_formats == [InputFormat.OXR]

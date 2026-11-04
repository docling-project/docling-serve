"""Tests for the version banner built in `docling_serve.helper_functions`."""

import importlib
import importlib.metadata
import sys


def test_version_banner_survives_a_missing_optional_distribution(monkeypatch):
    """A distribution docling-serve does not declare must not stop the import.

    `docling-ibm-models` and `docling-parse` are not in the project
    dependencies: they reach docling-serve through optional extras of
    docling-slim, and the extra that carries `docling-ibm-models` carries
    torch, torchvision and transformers with it. The banner is diagnostics and
    `/version` can be switched off entirely, so an install without one of them
    has to keep starting.
    """
    optional = ("docling-ibm-models", "docling-parse")

    def version(name: str) -> str:
        if name in optional:
            raise importlib.metadata.PackageNotFoundError(name)
        return "1.2.3"

    monkeypatch.setattr(importlib.metadata, "version", version)
    monkeypatch.delitem(sys.modules, "docling_serve.helper_functions", raising=False)

    helper_functions = importlib.import_module("docling_serve.helper_functions")

    versions = helper_functions.DOCLING_VERSIONS
    assert [versions[name] for name in optional] == ["not installed"] * 2
    # A declared dependency is still reported as it is found.
    assert versions["docling-serve"] == "1.2.3"
    assert versions["docling"] == "1.2.3"

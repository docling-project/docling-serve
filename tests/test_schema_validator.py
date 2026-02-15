"""Tests for the gRPC schema validator."""

import logging
from unittest.mock import patch

import pytest

from docling_serve.grpc.schema_validator import (
    _collect_pydantic_fields,
    _collect_proto_fields,
    _is_coercion_allowed,
    _types_compatible,
    validate_docling_document_schema,
)


def test_validate_passes_on_current_schemas():
    """The validator must pass without exception on the real schemas."""
    validate_docling_document_schema()


def test_no_warnings_on_current_schemas(caplog):
    """Current schemas should validate without missing-field warnings."""
    with caplog.at_level(logging.WARNING):
        validate_docling_document_schema()
    assert "Fields in Pydantic but not in proto" not in caplog.text
    assert "Fields in proto but not in Pydantic" not in caplog.text


def test_warns_on_missing_proto_field(caplog):
    """A Pydantic field not present in proto should produce a warning."""
    with patch(
        "docling_serve.grpc.schema_validator._collect_pydantic_fields",
        return_value={"name": "string"},
    ), patch(
        "docling_serve.grpc.schema_validator._collect_proto_fields",
        return_value={},
    ), patch.dict(
        "docling_serve.grpc.schema_validator._ONEOF_WRAPPER_MESSAGES",
        {},
        clear=True,
    ), caplog.at_level(logging.WARNING):
        validate_docling_document_schema()
    assert "Fields in Pydantic but not in proto" in caplog.text


def test_fails_on_type_mismatch():
    """An incompatible type mismatch (not in allowlist) must raise RuntimeError."""
    with patch(
        "docling_serve.grpc.schema_validator._collect_pydantic_fields",
        return_value={"name": "int"},
    ), patch(
        "docling_serve.grpc.schema_validator._collect_proto_fields",
        return_value={"name": "string"},
    ), patch.dict(
        "docling_serve.grpc.schema_validator._ONEOF_WRAPPER_MESSAGES",
        {},
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="type mismatch"):
            validate_docling_document_schema()


def test_allowlist_suppresses_known_coercions(caplog):
    """Known coercions (binary_hash, pages, label) must not fail."""
    with patch(
        "docling_serve.grpc.schema_validator._collect_pydantic_fields",
        return_value={"origin.binary_hash": "int"},
    ), patch(
        "docling_serve.grpc.schema_validator._collect_proto_fields",
        return_value={"origin.binary_hash": "string"},
    ), patch.dict(
        "docling_serve.grpc.schema_validator._ONEOF_WRAPPER_MESSAGES",
        {},
        clear=True,
    ), caplog.at_level(logging.INFO):
        validate_docling_document_schema()
    assert "Allowed coercions" in caplog.text
    assert "binary_hash" in caplog.text


def test_cardinality_mismatch_fails():
    """Proto repeated ↔ Pydantic non-list must fail."""
    with patch(
        "docling_serve.grpc.schema_validator._collect_pydantic_fields",
        return_value={"items": "string"},
    ), patch(
        "docling_serve.grpc.schema_validator._collect_proto_fields",
        return_value={"items": "list<string>"},
    ), patch.dict(
        "docling_serve.grpc.schema_validator._ONEOF_WRAPPER_MESSAGES",
        {},
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="Cardinality mismatch"):
            validate_docling_document_schema()


def test_oneof_union_compatibility():
    """Proto oneof (union) ↔ Pydantic union should be compatible."""
    assert _types_compatible(
        "union<message:TitleItem,message:TextItem>",
        "union<message:TitleItem,message:TextItem>",
    )


class TestTypesCompatible:
    def test_same_type(self):
        assert _types_compatible("string", "string")

    def test_int_int32(self):
        assert _types_compatible("int", "int32")

    def test_int_int64(self):
        assert _types_compatible("int", "int64")

    def test_optional_unwrap(self):
        assert _types_compatible("optional<string>", "string")
        assert _types_compatible("string", "optional<string>")

    def test_message_match(self):
        assert _types_compatible("message:Foo", "message:Foo")

    def test_message_mismatch(self):
        assert not _types_compatible("message:Foo", "message:Bar")

    def test_list_union_vs_message(self):
        assert _types_compatible(
            "list<union<message:A,message:B>>", "list<message:Wrapper>"
        )

    def test_incompatible(self):
        assert not _types_compatible("int", "string")


class TestStructuralEquivalences:
    """Tests for structural type equivalences (not allowlisted, but structurally matched)."""

    def test_tuple_intspan_equivalence(self):
        """tuple<int,int> ↔ message:IntSpan should be compatible."""
        assert _types_compatible("tuple<int,int>", "message:IntSpan")

    def test_optional_tuple_intspan(self):
        """optional<tuple<int,int>> ↔ optional<message:IntSpan> should be compatible."""
        assert _types_compatible("optional<tuple<int,int>>", "optional<message:IntSpan>")

    def test_oneof_wrapper_sourcetype(self):
        """union<message:TrackSource> ↔ message:SourceType (oneof wrapper)."""
        assert _types_compatible("message:TrackSource", "message:SourceType")

    def test_string_path_union_vs_string(self):
        """union<string,Path> ↔ string should be compatible (Path is string-like)."""
        assert _types_compatible("union<string,Path>", "string")

    def test_list_of_oneof_wrapper(self):
        """list<union<message:TrackSource>> ↔ list<message:SourceType> should work."""
        assert _types_compatible(
            "list<union<message:TrackSource>>", "list<message:SourceType>"
        )


class TestCoercionAllowlist:
    def test_binary_hash(self):
        assert _is_coercion_allowed("origin.binary_hash", "int", "string")
        assert _is_coercion_allowed("foo.bar.binary_hash", "int", "string")

    def test_pages_map_key(self):
        assert _is_coercion_allowed(
            "pages", "map<int,message:PageItem>", "map<string,message:PageItem>"
        )

    def test_label(self):
        assert _is_coercion_allowed("foo.label", "enum:FooLabel", "string")

    def test_not_allowed(self):
        assert not _is_coercion_allowed("foo.bar", "int", "string")

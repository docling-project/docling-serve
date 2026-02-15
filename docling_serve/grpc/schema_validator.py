"""Startup schema validator for DoclingDocument.

Compares the Pydantic DoclingDocument model against the protobuf descriptor
at startup. Raises RuntimeError on incompatible type mismatches (not in
allowlist). Logs warnings for missing fields. Logs info for allowed coercions.

See docs/grpc/schema_validation.md for the full specification.
"""

import enum
import logging
import types
import typing
from typing import Any, Optional, Union, get_args, get_origin

from google.protobuf import descriptor as descriptor_mod

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed coercions (spec §6)
# ---------------------------------------------------------------------------
ALLOWED_COERCIONS: dict[str, tuple[str, str]] = {
    "**.binary_hash": ("int", "string"),
    "pages": ("map<int,*>", "map<string,*>"),
    "**.label": ("enum", "string"),
}

# Proto messages that are oneof wrappers around Pydantic-side types.
# Key = proto message name, Value = set of Pydantic message names it wraps.
_ONEOF_WRAPPER_MESSAGES: dict[str, set[str]] = {
    "SourceType": {"TrackSource"},
    "PictureAnnotation": {
        "DescriptionAnnotation",
        "MiscAnnotation",
        "PictureClassificationData",
        "PictureMoleculeData",
        "PictureTabularChartData",
        "PictureLineChartData",
        "PictureBarChartData",
        "PictureStackedBarChartData",
        "PicturePieChartData",
        "PictureScatterChartData",
    },
    "TableAnnotation": {"DescriptionAnnotation", "MiscAnnotation"},
    "BaseTextItem": {
        "TitleItem",
        "SectionHeaderItem",
        "ListItem",
        "CodeItem",
        "FormulaItem",
        "TextItem",
    },
}

# Pydantic tuple types that map to a named proto message with matching fields.
_TUPLE_MESSAGE_EQUIVALENCES: dict[str, str] = {
    "tuple<int,int>": "IntSpan",
    "tuple<float,float>": "FloatPair",
    "tuple<string,int>": "StringIntPair",
}

# Types that are string-serializable and compatible with proto string.
_STRING_COMPATIBLE_TYPES: set[str] = {"Path"}

# ---------------------------------------------------------------------------
# Suppression rulesets
# ---------------------------------------------------------------------------
# Each ruleset below documents a structural divergence between the Pydantic
# model and the proto definition that is *intentional* and *understood*.
# Adding an entry here requires a comment explaining WHY the suppression
# exists.  When either schema changes, the validator will surface any new
# paths that don't fall into a known ruleset — forcing an explicit decision.
#
# See docs/grpc/schema_validation.md for the full specification.
# ---------------------------------------------------------------------------

# Field name aliases between Pydantic and proto.
# Pydantic's RefItem/FineRef use "cref" (aliased from "$ref" in JSON);
# the proto field is simply "ref".  These are the same data.
_FIELD_NAME_ALIASES: dict[str, str] = {
    "cref": "ref",
    "ref": "cref",
}

# Messages that wrap a base message field (flatten base fields for comparison).
# Proto text-item variants (TitleItem, SectionHeaderItem, …) contain a
# "base" sub-message (TextItemBase) that holds the common fields.  Pydantic
# uses class inheritance instead.  We flatten through the "base" field so
# paths align: proto "texts.title.base.text" → compared as "texts.text".
_BASE_FIELD_WRAPPERS: dict[str, str] = {
    "TitleItem": "base",
    "SectionHeaderItem": "base",
    "ListItem": "base",
    "CodeItem": "base",
    "FormulaItem": "base",
    "TextItem": "base",
}

# Proto messages that should be treated as leaf nodes (no recursive descent).
# google.protobuf well-known types (Struct/Value/ListValue) model dynamic
# JSON-like data — Pydantic uses Dict[str, Any] / get_custom_part() instead.
# Tuple-equivalent messages (IntSpan, FloatPair, StringIntPair) are matched
# structurally via _TUPLE_MESSAGE_EQUIVALENCES.
_PROTO_LEAF_MESSAGES: set[str] = {
    "Struct",
    "Value",
    "ListValue",
    "IntSpan",
    "FloatPair",
    "StringIntPair",
}

# Proto-only paths that exist because of structural divergences.
# Each entry documents a proto path prefix whose sub-fields have no
# Pydantic counterpart — because the converter builds them from different
# Pydantic structures.
#
# "*.data.grid" / "*.chart_data.grid":
#   Proto uses `repeated TableRow grid` as a row-major accessor.
#   Pydantic's TableData has no `grid` field — the converter builds
#   grid rows from `table_cells`.  All grid sub-paths are proto-only.
_PROTO_ONLY_PREFIXES: set[str] = {
    "tables.data.grid",
    "pictures.meta.tabular_chart.chart_data.grid",
    # Same grid path surfaced during oneof wrapper member validation
    # (PictureTabularChartData is validated independently with its own prefix).
    "chart_data.grid",
}

# Proto-only field name suffixes for enum fallback fields.
# When a proto enum field (e.g., coord_origin, code_language) encounters
# an unknown value, the raw string is stored in a companion *_raw field.
# These have no Pydantic counterpart by design.
_RAW_FALLBACK_SUFFIXES: set[str] = {
    "coord_origin_raw",
    "code_language_raw",
}

_WRAPPER_MEMBER_NAMES: set[str] = {
    name for members in _ONEOF_WRAPPER_MESSAGES.values() for name in members
}


def _match_pattern(path: str, pattern: str) -> bool:
    """Check if a dotted path matches an allowlist pattern.

    Supports "**" as a multi-segment wildcard and exact segment matches.
    """
    if pattern.startswith("**."):
        suffix = pattern[3:]
        return path == suffix or path.endswith("." + suffix)
    return path == pattern


def _is_coercion_allowed(
    path: str, pydantic_canonical: str, proto_canonical: str
) -> bool:
    """Return True if the (pydantic, proto) mismatch at *path* is allowlisted."""
    for pattern, (allowed_py, allowed_pr) in ALLOWED_COERCIONS.items():
        if _match_pattern(path, pattern):
            # Map key coercion: "map<int,*>" matches "map<int,...>"
            if allowed_py.startswith("map<") and "*>" in allowed_py:
                py_prefix = allowed_py.split(",")[0]  # "map<int"
                pr_prefix = allowed_pr.split(",")[0]  # "map<string"
                if pydantic_canonical.startswith(
                    py_prefix + ","
                ) and proto_canonical.startswith(pr_prefix + ","):
                    return True
                continue

            py_match = (
                pydantic_canonical == allowed_py
                or (allowed_py == "enum" and pydantic_canonical.startswith("enum:"))
                or (
                    allowed_py == "tuple<int,int>"
                    and pydantic_canonical == "tuple<int,int>"
                )
                or (allowed_py == "int" and pydantic_canonical == "int")
            )
            pr_match = (
                proto_canonical == allowed_pr
                or (allowed_pr == "list<int>" and proto_canonical.startswith("list<"))
                or (
                    allowed_pr == "string"
                    and proto_canonical in ("string", "optional<string>")
                )
            )
            if py_match and pr_match:
                return True
    return False


# ---------------------------------------------------------------------------
# Pydantic type normalization (spec §3)
# ---------------------------------------------------------------------------

# Types that should be treated as "string" even though they're not `str`
_STRING_LIKE_TYPES: set[str] = {
    "AnyUrl",
    "HttpUrl",
    "AnyHttpUrl",
    "FileUrl",
    "PostgresDsn",
    "RedisDsn",
    "MongoDsn",
    "KafkaDsn",
    "Url",
    "MultiHostUrl",
}


def _unwrap_annotated(tp: Any) -> Any:
    """Strip Annotated[...] wrapper, returning the inner type."""
    origin = get_origin(tp)
    if origin is typing.Annotated:
        return get_args(tp)[0]
    return tp


def _resolve_forward_ref(tp: Any) -> Any:
    if isinstance(tp, typing.ForwardRef):
        ref_name = tp.__forward_arg__
        try:
            from docling_core.types.doc import document as doc_module

            resolved = getattr(doc_module, ref_name, None)
            if resolved is not None:
                return resolved
        except Exception:
            pass
    return tp


def _normalize_pydantic_type(tp: Any) -> str:
    """Return a canonical string for a Pydantic type annotation."""
    tp = _unwrap_annotated(tp)
    tp = _resolve_forward_ref(tp)

    if tp is type(None):
        return "none"

    # Primitive types
    if tp is str:
        return "string"
    if tp is int:
        return "int"
    if tp is float:
        return "float"
    if tp is bool:
        return "bool"
    if tp is bytes:
        return "bytes"

    # Enum subclass
    if isinstance(tp, type) and issubclass(tp, enum.Enum):
        return f"enum:{tp.__name__}"

    # URL-like types → string
    if isinstance(tp, type) and tp.__name__ in _STRING_LIKE_TYPES:
        return "string"

    # BaseModel subclass
    try:
        from pydantic import BaseModel

        if isinstance(tp, type) and issubclass(tp, BaseModel):
            return f"message:{tp.__name__}"
    except ImportError:
        pass

    origin = get_origin(tp)
    args = get_args(tp)

    # Optional[T] → "optional<T>"
    if origin is Union or origin is types.UnionType:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1 and len(args) == 2:
            return f"optional<{_normalize_pydantic_type(non_none[0])}>"
        inner = ",".join(_normalize_pydantic_type(a) for a in non_none)
        return f"union<{inner}>"

    # List[T]
    if origin is list:
        if args:
            inner = _normalize_pydantic_type(args[0])
            return f"list<{inner}>"
        return "list<any>"

    # Dict[K, V]
    if origin is dict:
        if args and len(args) == 2:
            k = _normalize_pydantic_type(args[0])
            v = _normalize_pydantic_type(args[1])
            return f"map<{k},{v}>"
        return "map<any,any>"

    # Tuple[T, T] → keep as tuple for allowlist matching
    if origin is tuple:
        if args:
            inner = ",".join(_normalize_pydantic_type(a) for a in args)
            return f"tuple<{inner}>"
        return "tuple<any>"

    # Literal["x"] → string
    if origin is typing.Literal:
        if args:
            enum_args = [a for a in args if isinstance(a, enum.Enum)]
            enum_types = {type(a) for a in enum_args}
            if len(enum_args) == len(args) and len(enum_types) == 1:
                enum_type = next(iter(enum_types))
                return f"enum:{enum_type.__name__}"
        return "string"

    # Fallback: use class name
    if isinstance(tp, type):
        return tp.__name__
    return str(tp)


def _collect_pydantic_fields(
    model_cls: Any,
    prefix: str = "",
    max_depth: Optional[int] = None,
    _depth: int = 0,
    _path_stack: Optional[set[type]] = None,
    _skip_wrapper_members: bool = True,
) -> dict[str, str]:
    """Collect Pydantic model fields, returning {dotted.path: canonical_type}.

    Only recurses into BaseModel subfields up to *max_depth* levels.
    """
    from pydantic import BaseModel

    result: dict[str, str] = {}
    if _path_stack is None:
        _path_stack = set()
    if isinstance(model_cls, type):
        if model_cls in _path_stack:
            return result
        _path_stack.add(model_cls)
    for name, field in model_cls.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        tp = field.annotation
        canonical = _normalize_pydantic_type(tp)
        result[path] = canonical

        if max_depth is not None and _depth >= max_depth:
            continue

        # Recurse into BaseModel subclasses
        inner_tp = _unwrap_annotated(tp)
        inner_tp = _resolve_forward_ref(inner_tp)
        origin = get_origin(inner_tp)
        if origin is Union or (
            hasattr(types, "UnionType") and origin is types.UnionType
        ):
            args = get_args(inner_tp)
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                inner_tp = non_none[0]

        if isinstance(inner_tp, type) and issubclass(inner_tp, BaseModel):
            if _skip_wrapper_members and inner_tp.__name__ in _WRAPPER_MEMBER_NAMES:
                continue
            result.update(
                _collect_pydantic_fields(
                    inner_tp,
                    path,
                    max_depth,
                    _depth + 1,
                    _path_stack,
                    _skip_wrapper_members,
                )
            )
            continue

        # List/Dict/Union containing BaseModel types
        origin = get_origin(inner_tp)
        args = get_args(inner_tp)
        if origin is list and args:
            item = _unwrap_annotated(args[0])
            item = _resolve_forward_ref(item)
            if isinstance(item, type) and issubclass(item, BaseModel):
                if _skip_wrapper_members and item.__name__ in _WRAPPER_MEMBER_NAMES:
                    continue
                result.update(
                    _collect_pydantic_fields(
                        item,
                        path,
                        max_depth,
                        _depth + 1,
                        _path_stack,
                        _skip_wrapper_members,
                    )
                )
            else:
                nested_origin = get_origin(item)
                nested_args = get_args(item)
                if nested_origin is list and nested_args:
                    nested_item = _unwrap_annotated(nested_args[0])
                    nested_item = _resolve_forward_ref(nested_item)
                    if isinstance(nested_item, type) and issubclass(
                        nested_item, BaseModel
                    ):
                        if (
                            _skip_wrapper_members
                            and nested_item.__name__ in _WRAPPER_MEMBER_NAMES
                        ):
                            continue
                        result.update(
                            _collect_pydantic_fields(
                                nested_item,
                                path,
                                max_depth,
                                _depth + 1,
                                _path_stack,
                                _skip_wrapper_members,
                            )
                        )
                elif nested_origin is Union or nested_origin is types.UnionType:
                    for union_item in nested_args:
                        union_item = _unwrap_annotated(union_item)
                        union_item = _resolve_forward_ref(union_item)
                        if isinstance(union_item, type) and issubclass(
                            union_item, BaseModel
                        ):
                            if (
                                _skip_wrapper_members
                                and union_item.__name__ in _WRAPPER_MEMBER_NAMES
                            ):
                                continue
                            result.update(
                                _collect_pydantic_fields(
                                    union_item,
                                    path,
                                    max_depth,
                                    _depth + 1,
                                    _path_stack,
                                    _skip_wrapper_members,
                                )
                            )
        elif origin is dict and args and len(args) == 2:
            val = _unwrap_annotated(args[1])
            val = _resolve_forward_ref(val)
            if isinstance(val, type) and issubclass(val, BaseModel):
                if _skip_wrapper_members and val.__name__ in _WRAPPER_MEMBER_NAMES:
                    continue
                result.update(
                    _collect_pydantic_fields(
                        val,
                        path,
                        max_depth,
                        _depth + 1,
                        _path_stack,
                        _skip_wrapper_members,
                    )
                )
        elif origin is Union or origin is types.UnionType:
            # Don't recurse into union member fields.  Union variants are
            # matched at the type level (_types_compatible handles oneof
            # wrappers).  Recursing would emit "missing in proto" warnings
            # for every sub-field of every variant since proto represents
            # them through a oneof wrapper with different paths.
            pass

    if isinstance(model_cls, type):
        _path_stack.remove(model_cls)

    return result


# ---------------------------------------------------------------------------
# Proto type normalization (spec §4)
# ---------------------------------------------------------------------------
_PROTO_TYPE_MAP = {
    descriptor_mod.FieldDescriptor.TYPE_STRING: "string",
    descriptor_mod.FieldDescriptor.TYPE_BOOL: "bool",
    descriptor_mod.FieldDescriptor.TYPE_BYTES: "bytes",
    descriptor_mod.FieldDescriptor.TYPE_DOUBLE: "float",
    descriptor_mod.FieldDescriptor.TYPE_FLOAT: "float",
    descriptor_mod.FieldDescriptor.TYPE_INT32: "int32",
    descriptor_mod.FieldDescriptor.TYPE_INT64: "int64",
    descriptor_mod.FieldDescriptor.TYPE_SINT32: "int32",
    descriptor_mod.FieldDescriptor.TYPE_SINT64: "int64",
    descriptor_mod.FieldDescriptor.TYPE_SFIXED32: "int32",
    descriptor_mod.FieldDescriptor.TYPE_SFIXED64: "int64",
    descriptor_mod.FieldDescriptor.TYPE_FIXED32: "int32",
    descriptor_mod.FieldDescriptor.TYPE_FIXED64: "int64",
    descriptor_mod.FieldDescriptor.TYPE_UINT32: "int32",
    descriptor_mod.FieldDescriptor.TYPE_UINT64: "int64",
}


def _normalize_proto_field(field: descriptor_mod.FieldDescriptor) -> str:
    """Return a canonical string for a single proto field descriptor."""
    if field.type == descriptor_mod.FieldDescriptor.TYPE_ENUM:
        base = f"enum:{field.enum_type.name}"
    elif field.type == descriptor_mod.FieldDescriptor.TYPE_MESSAGE:
        msg = field.message_type
        if msg.GetOptions().map_entry:
            key_f = msg.fields_by_name["key"]
            val_f = msg.fields_by_name["value"]
            return (
                f"map<{_normalize_proto_field(key_f)},{_normalize_proto_field(val_f)}>"
            )
        base = f"message:{msg.name}"
    else:
        base = _PROTO_TYPE_MAP.get(field.type, f"unknown:{field.type}")

    # Repeated (but not map)
    if field.label == descriptor_mod.FieldDescriptor.LABEL_REPEATED and not (
        field.type == descriptor_mod.FieldDescriptor.TYPE_MESSAGE
        and field.message_type.GetOptions().map_entry
    ):
        return f"list<{base}>"

    # Optional presence (scalars only; messages always have presence in proto3)
    if field.has_presence and field.type != descriptor_mod.FieldDescriptor.TYPE_MESSAGE:
        return f"optional<{base}>"

    return base


def _collect_proto_fields(
    descriptor: descriptor_mod.Descriptor,
    prefix: str = "",
    max_depth: Optional[int] = None,
    _depth: int = 0,
    _path_stack: Optional[set[str]] = None,
) -> dict[str, str]:
    """Collect proto fields, returning {dotted.path: canonical_type}.

    Only recurses into sub-messages up to *max_depth* levels.
    """
    result: dict[str, str] = {}
    if _path_stack is None:
        _path_stack = set()
    if descriptor.full_name in _path_stack:
        return result
    _path_stack.add(descriptor.full_name)

    if descriptor.name in _ONEOF_WRAPPER_MESSAGES:
        _path_stack.remove(descriptor.full_name)
        return result

    # Handle real oneof groups (not synthetic proto3 optional presence)
    oneofs_handled: set[str] = set()
    for oneof in descriptor.oneofs:
        if oneof.name.startswith("_"):
            continue
        if descriptor.name in _ONEOF_WRAPPER_MESSAGES:
            continue
        path = f"{prefix}.{oneof.name}" if prefix else oneof.name
        members = [_normalize_proto_field(f) for f in oneof.fields]
        if len(members) > 1:
            result[path] = f"union<{','.join(members)}>"
            for f in oneof.fields:
                oneofs_handled.add(f.name)

    for field in descriptor.fields:
        if field.name in oneofs_handled:
            continue
        path = f"{prefix}.{field.name}" if prefix else field.name
        if (
            descriptor.name in _BASE_FIELD_WRAPPERS
            and field.name == _BASE_FIELD_WRAPPERS[descriptor.name]
        ):
            if (
                field.type == descriptor_mod.FieldDescriptor.TYPE_MESSAGE
                and not field.message_type.GetOptions().map_entry
            ):
                result.update(
                    _collect_proto_fields(
                        field.message_type,
                        prefix,
                        max_depth,
                        _depth + 1,
                        _path_stack,
                    )
                )
            continue

        canonical = _normalize_proto_field(field)
        result[path] = canonical

        # Recurse into messages (handle maps separately)
        if field.type == descriptor_mod.FieldDescriptor.TYPE_MESSAGE:
            if field.message_type.GetOptions().map_entry:
                if max_depth is None or _depth < max_depth:
                    val_f = field.message_type.fields_by_name["value"]
                    if val_f.type == descriptor_mod.FieldDescriptor.TYPE_MESSAGE:
                        result.update(
                            _collect_proto_fields(
                                val_f.message_type,
                                path,
                                max_depth,
                                _depth + 1,
                                _path_stack,
                            )
                        )
            elif field.message_type.name in _PROTO_LEAF_MESSAGES:
                pass
            elif max_depth is None or _depth < max_depth:
                result.update(
                    _collect_proto_fields(
                        field.message_type,
                        path,
                        max_depth,
                        _depth + 1,
                        _path_stack,
                    )
                )

    _path_stack.remove(descriptor.full_name)
    return result


# ---------------------------------------------------------------------------
# Type compatibility (spec §5)
# ---------------------------------------------------------------------------
def _types_compatible(pydantic_canonical: str, proto_canonical: str) -> bool:
    """Return True if the two canonical types are compatible."""
    if pydantic_canonical == proto_canonical:
        return True

    # int ↔ any int32/int64
    if pydantic_canonical == "int" and proto_canonical in ("int32", "int64"):
        return True

    # float ↔ float/double (proto normalizes both to "float")
    if pydantic_canonical == "float" and proto_canonical == "float":
        return True

    # string ↔ string
    if pydantic_canonical == "string" and proto_canonical in (
        "string",
        "optional<string>",
    ):
        return True

    # optional<T> ↔ T or optional<T>
    if pydantic_canonical.startswith("optional<") and pydantic_canonical.endswith(">"):
        inner = pydantic_canonical[9:-1]
        if _types_compatible(inner, proto_canonical):
            return True
    if proto_canonical.startswith("optional<") and proto_canonical.endswith(">"):
        inner = proto_canonical[9:-1]
        if _types_compatible(pydantic_canonical, inner):
            return True

    # Tuple ↔ named message (e.g. tuple<int,int> ↔ message:IntSpan)
    if pydantic_canonical.startswith("tuple<") and proto_canonical.startswith(
        "message:"
    ):
        proto_msg_name = proto_canonical[8:]
        expected_msg = _TUPLE_MESSAGE_EQUIVALENCES.get(pydantic_canonical)
        if expected_msg == proto_msg_name:
            return True

    # Union containing string-compatible types ↔ string
    # e.g. union<string,Path> ↔ string (Path serializes to string on the wire)
    if pydantic_canonical.startswith("union<") and proto_canonical == "string":
        inner = pydantic_canonical[6:-1]
        parts = [p.strip() for p in inner.split(",")]
        if all(p == "string" or p in _STRING_COMPATIBLE_TYPES for p in parts):
            return True

    # message:Foo ↔ message:Foo, or Foo is a oneof wrapper for Bar
    if pydantic_canonical.startswith("message:") and proto_canonical.startswith(
        "message:"
    ):
        if pydantic_canonical == proto_canonical:
            return True
        py_name = pydantic_canonical[8:]
        pr_name = proto_canonical[8:]
        wrapped = _ONEOF_WRAPPER_MESSAGES.get(pr_name)
        if wrapped and py_name in wrapped:
            return True
        return False

    # map<string,Any> ↔ Struct
    if pydantic_canonical == "map<string,Any>" and proto_canonical == "message:Struct":
        return True

    # enum:Foo ↔ enum:Foo
    if pydantic_canonical.startswith("enum:") and proto_canonical.startswith("enum:"):
        return pydantic_canonical == proto_canonical

    # list<T> ↔ list<T>
    if pydantic_canonical.startswith("list<") and proto_canonical.startswith("list<"):
        py_inner = pydantic_canonical[5:-1]
        pr_inner = proto_canonical[5:-1]
        # Union list vs oneof wrapper message
        if py_inner.startswith("union<") and pr_inner.startswith("message:"):
            return True
        return _types_compatible(py_inner, pr_inner)

    # map<K,V> ↔ map<K,V>
    if pydantic_canonical.startswith("map<") and proto_canonical.startswith("map<"):
        py_inner = pydantic_canonical[4:-1]
        pr_inner = proto_canonical[4:-1]
        py_parts = py_inner.split(",", 1)
        pr_parts = pr_inner.split(",", 1)
        if len(py_parts) == 2 and len(pr_parts) == 2:
            return _types_compatible(py_parts[0], pr_parts[0]) and _types_compatible(
                py_parts[1], pr_parts[1]
            )

    # union ↔ union (loose)
    if pydantic_canonical.startswith("union<") and proto_canonical.startswith("union<"):
        return True

    return False


# ---------------------------------------------------------------------------
# Cardinality checks (spec §2)
# ---------------------------------------------------------------------------
def _check_cardinality(
    path: str, pydantic_canonical: str, proto_canonical: str
) -> Optional[str]:
    """Return an error message if cardinality mismatches, else None."""
    proto_is_list = proto_canonical.startswith("list<")
    proto_is_map = proto_canonical.startswith("map<")
    proto_is_union = proto_canonical.startswith("union<")

    py_is_list = pydantic_canonical.startswith("list<")
    py_is_map = pydantic_canonical.startswith("map<")
    py_is_union = pydantic_canonical.startswith("union<")

    if proto_is_list and not py_is_list and not pydantic_canonical.startswith("tuple<"):
        return (
            f"Cardinality mismatch at '{path}': proto is repeated ({proto_canonical}) "
            f"but Pydantic is not list-like ({pydantic_canonical})"
        )
    if proto_is_map and not py_is_map:
        return (
            f"Cardinality mismatch at '{path}': proto is map ({proto_canonical}) "
            f"but Pydantic is not dict-like ({pydantic_canonical})"
        )
    if proto_is_union and not py_is_union:
        return (
            f"Cardinality mismatch at '{path}': proto is oneof ({proto_canonical}) "
            f"but Pydantic is not union-like ({pydantic_canonical})"
        )
    return None


# ---------------------------------------------------------------------------
# Public API (spec §10)
# ---------------------------------------------------------------------------
def _resolve_alias(path: str, fields: dict[str, str]) -> Optional[str]:
    parts = path.split(".")
    if not parts:
        return None
    last = parts[-1]
    alias = _FIELD_NAME_ALIASES.get(last)
    if not alias:
        return None
    candidate = ".".join(parts[:-1] + [alias])
    return candidate if candidate in fields else None


def _compare_fields(
    pydantic_fields: dict[str, str],
    proto_fields: dict[str, str],
    context: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    mismatches: list[str] = []
    allowed: list[str] = []
    missing_proto: list[str] = []
    missing_pydantic: list[str] = []

    all_paths = set(pydantic_fields.keys()) | set(proto_fields.keys())
    for path in sorted(all_paths):
        py_type = pydantic_fields.get(path)
        pr_type = proto_fields.get(path)

        if py_type is None and pr_type is not None:
            # --- Suppression rulesets for proto-only paths ---
            # custom_fields: Pydantic uses get_custom_part() method, not a
            # declared model field.  Proto uses map<string, Value>.
            if ".custom_fields" in path:
                continue
            # Proto-only structural prefixes (e.g., TableRow grid).
            if any(
                path == pfx or path.startswith(pfx + ".")
                for pfx in _PROTO_ONLY_PREFIXES
            ):
                continue
            # Enum fallback *_raw companion fields.
            parts = path.rsplit(".", 1)
            if (parts[-1] if len(parts) > 1 else path) in _RAW_FALLBACK_SUFFIXES:
                continue
            alias = _resolve_alias(path, pydantic_fields)
            if alias is not None:
                py_type = pydantic_fields.get(alias)
            else:
                missing_pydantic.append(f"{context}{path}")
                continue
        if pr_type is None and py_type is not None:
            alias = _resolve_alias(path, proto_fields)
            if alias is not None:
                pr_type = proto_fields.get(alias)
            else:
                missing_proto.append(f"{context}{path}")
                continue

        assert py_type is not None and pr_type is not None

        card_err = _check_cardinality(path, py_type, pr_type)
        if card_err is not None:
            if _is_coercion_allowed(path, py_type, pr_type):
                allowed.append(f"{context}{path}: {py_type} ↔ {pr_type}")
            else:
                mismatches.append(f"{context}{card_err}")
            continue

        if _types_compatible(py_type, pr_type):
            continue

        if _is_coercion_allowed(path, py_type, pr_type):
            allowed.append(f"{context}{path}: {py_type} ↔ {pr_type}")
            continue

        mismatches.append(
            f"{context}Type mismatch at '{path}': Pydantic={py_type}, Proto={pr_type}"
        )

    return mismatches, allowed, missing_proto, missing_pydantic


def validate_docling_document_schema() -> None:
    """Compare Pydantic DoclingDocument against proto descriptor at startup.

    Raises RuntimeError on incompatible type mismatches (not in allowlist).
    Logs warnings for missing fields.
    Logs info for allowed coercions.
    """
    from docling_core.types.doc.document import DoclingDocument

    from .gen.ai.docling.core.v1 import docling_document_pb2 as pb2

    pydantic_fields = _collect_pydantic_fields(DoclingDocument)
    proto_fields = _collect_proto_fields(pb2.DoclingDocument.DESCRIPTOR)

    mismatches, allowed, missing_proto, missing_pydantic = _compare_fields(
        pydantic_fields, proto_fields, context=""
    )

    # Validate each oneof wrapper member against its concrete proto message.
    from docling_core.types.doc import document as doc_module

    for members in _ONEOF_WRAPPER_MESSAGES.values():
        for member_name in members:
            model_cls = getattr(doc_module, member_name, None)
            if model_cls is None:
                continue
            descriptor = pb2.DESCRIPTOR.message_types_by_name.get(member_name)
            if descriptor is None:
                continue
            py_fields = _collect_pydantic_fields(model_cls)
            pr_fields = _collect_proto_fields(descriptor)
            ctx = f"{member_name}."
            m, a, mp, md = _compare_fields(py_fields, pr_fields, context=ctx)
            mismatches.extend(m)
            allowed.extend(a)
            missing_proto.extend(mp)
            missing_pydantic.extend(md)

    # Report
    if missing_proto:
        _log.warning(
            "Fields in Pydantic but not in proto (%d): %s",
            len(missing_proto),
            ", ".join(missing_proto),
        )
    if missing_pydantic:
        _log.warning(
            "Fields in proto but not in Pydantic (%d): %s",
            len(missing_pydantic),
            ", ".join(missing_pydantic),
        )
    if allowed:
        _log.info(
            "Allowed coercions (%d): %s",
            len(allowed),
            "; ".join(allowed),
        )
    if mismatches:
        detail = "\n  ".join(mismatches)
        raise RuntimeError(
            f"DoclingDocument schema validation failed with {len(mismatches)} "
            f"type mismatch(es):\n  {detail}"
        )

    _log.info(
        "DoclingDocument schema validation passed: %d Pydantic fields, %d proto fields",
        len(pydantic_fields),
        len(proto_fields),
    )

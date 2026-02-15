"""Startup schema validator for DoclingDocument.

Compares the Pydantic DoclingDocument model against the protobuf descriptor
at startup. Raises RuntimeError on incompatible type mismatches (not in
allowlist). Logs warnings for missing fields. Logs info for allowed coercions.

See docs/grpc_schema_validation.md for the full specification.
"""

import enum
import logging
import types
import typing
from typing import Any, Dict, List, Optional, Set, Tuple, Union, get_args, get_origin

from google.protobuf import descriptor as descriptor_mod

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Allowed coercions (spec §6)
# ---------------------------------------------------------------------------
ALLOWED_COERCIONS: Dict[str, Tuple[str, str]] = {
    "**.binary_hash": ("int", "string"),
    "pages": ("map<int,*>", "map<string,*>"),
    "**.label": ("enum", "string"),
}

# Proto messages that are oneof wrappers around a single Pydantic-side type.
# Key = proto message name, Value = set of Pydantic message names it wraps.
_ONEOF_WRAPPER_MESSAGES: Dict[str, Set[str]] = {
    "SourceType": {"TrackSource"},
    "PictureAnnotation": {
        "DescriptionAnnotation", "MiscAnnotation",
        "PictureClassificationData", "PictureMoleculeData",
        "PictureTabularChartData", "PictureLineChartData",
        "PictureBarChartData", "PictureStackedBarChartData",
        "PicturePieChartData", "PictureScatterChartData",
    },
    "TableAnnotation": {"DescriptionAnnotation", "MiscAnnotation"},
    "BaseTextItem": {
        "TitleItem", "SectionHeaderItem", "ListItem",
        "CodeItem", "FormulaItem", "TextItem",
    },
}

# Pydantic tuple types that map to a named proto message with matching fields.
_TUPLE_MESSAGE_EQUIVALENCES: Dict[str, str] = {
    "tuple<int,int>": "IntSpan",
    "tuple<float,float>": "FloatPair",
    "tuple<string,int>": "StringIntPair",
}

# Types that are string-serializable and compatible with proto string.
_STRING_COMPATIBLE_TYPES: Set[str] = {"Path"}


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
                if (
                    pydantic_canonical.startswith(py_prefix + ",")
                    and proto_canonical.startswith(pr_prefix + ",")
                ):
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
                or (allowed_pr == "string" and proto_canonical == "string")
            )
            if py_match and pr_match:
                return True
    return False


# ---------------------------------------------------------------------------
# Pydantic type normalization (spec §3)
# ---------------------------------------------------------------------------

# Types that should be treated as "string" even though they're not `str`
_STRING_LIKE_TYPES: Set[str] = {
    "AnyUrl", "HttpUrl", "AnyHttpUrl", "FileUrl", "PostgresDsn",
    "RedisDsn", "MongoDsn", "KafkaDsn", "Url", "MultiHostUrl",
}


def _unwrap_annotated(tp: Any) -> Any:
    """Strip Annotated[...] wrapper, returning the inner type."""
    origin = get_origin(tp)
    if origin is typing.Annotated:
        return get_args(tp)[0]
    return tp


def _normalize_pydantic_type(tp: Any) -> str:
    """Return a canonical string for a Pydantic type annotation."""
    tp = _unwrap_annotated(tp)

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
    _visited: Optional[Set[type]] = None,
) -> Dict[str, str]:
    """Collect Pydantic model fields, returning {dotted.path: canonical_type}.

    Only recurses into BaseModel subfields up to *max_depth* levels.
    """
    from pydantic import BaseModel

    result: Dict[str, str] = {}
    if _visited is None:
        _visited = set()
    if isinstance(model_cls, type):
        if model_cls in _visited:
            return result
        _visited.add(model_cls)
    for name, field in model_cls.model_fields.items():
        path = f"{prefix}.{name}" if prefix else name
        tp = field.annotation
        canonical = _normalize_pydantic_type(tp)
        result[path] = canonical

        if max_depth is not None and _depth >= max_depth:
            continue

        # Recurse into BaseModel subclasses
        inner_tp = _unwrap_annotated(tp)
        origin = get_origin(inner_tp)
        if origin is Union or (hasattr(types, "UnionType") and origin is types.UnionType):
            args = get_args(inner_tp)
            non_none = [a for a in args if a is not type(None)]
            if len(non_none) == 1:
                inner_tp = non_none[0]

        if isinstance(inner_tp, type) and issubclass(inner_tp, BaseModel):
            result.update(
                _collect_pydantic_fields(
                    inner_tp,
                    path,
                    max_depth,
                    _depth + 1,
                    _visited,
                )
            )
            continue

        # List/Dict/Union containing BaseModel types
        origin = get_origin(inner_tp)
        args = get_args(inner_tp)
        if origin is list and args:
            item = _unwrap_annotated(args[0])
            if isinstance(item, type) and issubclass(item, BaseModel):
                result.update(
                    _collect_pydantic_fields(
                        item,
                        path,
                        max_depth,
                        _depth + 1,
                        _visited,
                    )
                )
        elif origin is dict and args and len(args) == 2:
            val = _unwrap_annotated(args[1])
            if isinstance(val, type) and issubclass(val, BaseModel):
                result.update(
                    _collect_pydantic_fields(
                        val,
                        path,
                        max_depth,
                        _depth + 1,
                        _visited,
                    )
                )
        elif origin is Union or origin is types.UnionType:
            # Don't recurse into union member fields.  Union variants are
            # matched at the type level (_types_compatible handles oneof
            # wrappers).  Recursing would emit "missing in proto" warnings
            # for every sub-field of every variant since proto represents
            # them through a oneof wrapper with different paths.
            pass

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
            return f"map<{_normalize_proto_field(key_f)},{_normalize_proto_field(val_f)}>"
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
    _visited: Optional[Set[str]] = None,
) -> Dict[str, str]:
    """Collect proto fields, returning {dotted.path: canonical_type}.

    Only recurses into sub-messages up to *max_depth* levels.
    """
    result: Dict[str, str] = {}
    if _visited is None:
        _visited = set()
    if descriptor.full_name in _visited:
        return result
    _visited.add(descriptor.full_name)

    # Handle real oneof groups (not synthetic proto3 optional presence)
    oneofs_handled: Set[str] = set()
    for oneof in descriptor.oneofs:
        if oneof.name.startswith("_"):
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
        canonical = _normalize_proto_field(field)
        result[path] = canonical

        # Recurse into messages (not maps)
        if (
            field.type == descriptor_mod.FieldDescriptor.TYPE_MESSAGE
            and not field.message_type.GetOptions().map_entry
            and (max_depth is None or _depth < max_depth)
        ):
            result.update(
                _collect_proto_fields(
                    field.message_type,
                    path,
                    max_depth,
                    _depth + 1,
                    _visited,
                )
            )

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
    if pydantic_canonical.startswith("tuple<") and proto_canonical.startswith("message:"):
        proto_msg_name = proto_canonical[8:]
        expected_msg = _TUPLE_MESSAGE_EQUIVALENCES.get(pydantic_canonical)
        if expected_msg == proto_msg_name:
            return True

    # Union containing string-compatible types ↔ string
    # e.g. union<string,Path> ↔ string (Path serializes to string on the wire)
    if pydantic_canonical.startswith("union<") and proto_canonical == "string":
        inner = pydantic_canonical[6:-1]
        parts = [p.strip() for p in inner.split(",")]
        if all(
            p == "string" or p in _STRING_COMPATIBLE_TYPES for p in parts
        ):
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
            return _types_compatible(
                py_parts[0], pr_parts[0]
            ) and _types_compatible(py_parts[1], pr_parts[1])

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

    all_paths = set(pydantic_fields.keys()) | set(proto_fields.keys())

    mismatches: List[str] = []
    allowed: List[str] = []
    missing_proto: List[str] = []
    missing_pydantic: List[str] = []

    for path in sorted(all_paths):
        py_type = pydantic_fields.get(path)
        pr_type = proto_fields.get(path)

        if py_type is not None and pr_type is None:
            missing_proto.append(path)
            continue
        if py_type is None and pr_type is not None:
            missing_pydantic.append(path)
            continue

        assert py_type is not None and pr_type is not None

        # Cardinality check
        card_err = _check_cardinality(path, py_type, pr_type)
        if card_err is not None:
            if _is_coercion_allowed(path, py_type, pr_type):
                allowed.append(f"{path}: {py_type} ↔ {pr_type}")
            else:
                mismatches.append(card_err)
            continue

        # Type compatibility
        if _types_compatible(py_type, pr_type):
            continue

        # Check allowlist
        if _is_coercion_allowed(path, py_type, pr_type):
            allowed.append(f"{path}: {py_type} ↔ {pr_type}")
            continue

        mismatches.append(
            f"Type mismatch at '{path}': Pydantic={py_type}, Proto={pr_type}"
        )

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

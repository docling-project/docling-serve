# Protobuf Descriptor API Guide for Schema Validation

This guide documents how to inspect protobuf descriptors at runtime and compare
them against Pydantic models. It is intended for validating the Docling gRPC
schema and for building compatibility checks.

## Project Context

- Proto source: `proto/ai/docling/core/v1/docling_document.proto`
- Generated code: `docling_serve/grpc/gen/ai/docling/core/v1/docling_document_pb2.py`
- Root message: `DoclingDocument` (highly nested structure)

## 1. Accessing Descriptors

Descriptors expose the runtime schema:

```python
from docling_serve.grpc.gen.ai.docling.core.v1 import docling_document_pb2
from google.protobuf import descriptor as desc_module

msg_descriptor = docling_document_pb2.DoclingDocument.DESCRIPTOR
```

## 2. Descriptor Attribute Reference

Message Descriptor (`.DESCRIPTOR`)

- `name` (str): Simple name (e.g., `DoclingDocument`)
- `full_name` (str): Qualified name (e.g., `ai.docling.core.v1.DoclingDocument`)
- `fields` (List): Ordered FieldDescriptor objects
- `fields_by_name` (Dict): `{field_name: FieldDescriptor}`
- `nested_types` (List): Nested message descriptors
- `nested_types_by_name` (Dict): `{name: MessageDescriptor}`
- `enum_types` (List): Enum descriptors defined in this message
- `enum_types_by_name` (Dict): `{enum_name: EnumDescriptor}`
- `oneofs` (List): Oneof group descriptors
- `oneofs_by_name` (Dict): `{oneof_name: OneofDescriptor}`
- `extensions` (List): Extension field descriptors
- `containing_type` (Descriptor | None): Parent message descriptor

Field Descriptor (from `.fields` or `.fields_by_name["name"]`)

- `name` (str): Field name
- `number` (int): Field number
- `type` (int): Field type (use `TYPE_*` constants)
- `label` (int): Field label (use `LABEL_*` constants)
- `message_type` (Descriptor): For `TYPE_MESSAGE` fields
- `enum_type` (EnumDescriptor): For `TYPE_ENUM` fields
- `default_value` (Any): Default value for the field
- `has_presence` (bool): Presence tracking for proto3 optional
- `is_extension` (bool): Extension field
- `cpp_type` (int): C++ field type constant
- `containing_type` (Descriptor): Parent message descriptor
- `is_required()` (bool): Required (proto2 only)
- `is_repeated()` (bool): Repeated (arrays)

Enum Descriptor (from `.enum_type`)

- `name` (str): Enum name
- `full_name` (str): Qualified enum name
- `values` (List): EnumValueDescriptor objects
- `values_by_name` (Dict): `{value_name: EnumValueDescriptor}`
- `values_by_number` (Dict): `{number: EnumValueDescriptor}`

Enum Value Descriptor (from `.enum_type.values`)

- `name` (str): Value name (e.g., `CONTENT_LAYER_BODY`)
- `number` (int): Numeric value
- `type` (EnumDescriptor): Parent enum descriptor

Oneof Descriptor (from `.oneofs`)

- `name` (str): Oneof group name
- `fields` (List): FieldDescriptor objects in this group
- `containing_type` (Descriptor): Parent message descriptor

## 3. Key Constants and Enumerations

FieldDescriptor `TYPE_*` constants:

- `TYPE_DOUBLE` = 1
- `TYPE_FLOAT` = 2
- `TYPE_INT64` = 3
- `TYPE_UINT64` = 4
- `TYPE_INT32` = 5
- `TYPE_FIXED64` = 6
- `TYPE_FIXED32` = 7
- `TYPE_BOOL` = 8
- `TYPE_STRING` = 9
- `TYPE_GROUP` = 10
- `TYPE_MESSAGE` = 11
- `TYPE_BYTES` = 12
- `TYPE_UINT32` = 13
- `TYPE_ENUM` = 14
- `TYPE_SFIXED32` = 15
- `TYPE_SFIXED64` = 16
- `TYPE_SINT32` = 17
- `TYPE_SINT64` = 18

FieldDescriptor `LABEL_*` constants:

- `LABEL_OPTIONAL` = 1
- `LABEL_REQUIRED` = 2
- `LABEL_REPEATED` = 3

Cardinality detection:

- `field.label == FieldDescriptor.LABEL_REPEATED` -> list/array
- `field.label == FieldDescriptor.LABEL_OPTIONAL` -> optional
- `field.has_presence == True` -> proto3 optional (presence tracked)

Type detection:

- `field.type == FieldDescriptor.TYPE_MESSAGE` -> nested message
- `field.type == FieldDescriptor.TYPE_ENUM` -> enum
- `field.type == FieldDescriptor.TYPE_STRING` -> string
- `field.type in (TYPE_INT32, TYPE_INT64, ...)` -> integer
- `field.type == FieldDescriptor.TYPE_BOOL` -> boolean

## 4. Detecting Special Field Types

Repeated fields (arrays):

```python
field.label == FieldDescriptor.LABEL_REPEATED
```

Example: `repeated GroupItem groups`

```python
groups_field = msg_descriptor.fields_by_name["groups"]
groups_field.label == FieldDescriptor.LABEL_REPEATED
groups_field.message_type.name == "GroupItem"
```

Optional fields (proto3 optional):

```python
field.has_presence == True
field.label == FieldDescriptor.LABEL_OPTIONAL
```

Map fields (dictionaries):

```python
field.label == FieldDescriptor.LABEL_REPEATED and field.message_type.GetOptions().map_entry
```

Example: `map<string, PageItem> pages`

```python
pages_field = msg_descriptor.fields_by_name["pages"]
pages_field.message_type.GetOptions().map_entry == True
key_field = pages_field.message_type.fields_by_name["key"]
value_field = pages_field.message_type.fields_by_name["value"]
```

Oneof fields (tagged union):

```python
field.containing_oneof is not None
```

Example: `oneof item { ... }` in `BaseTextItem`

```python
base_item_desc = docling_document_pb2.BaseTextItem.DESCRIPTOR
item_oneof = base_item_desc.oneofs_by_name["item"]
for field in item_oneof.fields:
    print(field.name)
```

Nested messages:

```python
field.type == FieldDescriptor.TYPE_MESSAGE
```

## 5. Recursive Walking Pattern

```python
def walk_message(msg_desc, visited=None, max_depth=3, depth=0):
    if visited is None:
        visited = set()
    if depth >= max_depth or msg_desc.full_name in visited:
        return

    visited.add(msg_desc.full_name)
    indent = "  " * depth
    print(f"{indent}{msg_desc.name}:")

    for field in msg_desc.fields:
        print(f"{indent}  - {field.name} ({field.type})")
        if field.type == FieldDescriptor.TYPE_MESSAGE:
            if not is_map_field(field):
                walk_message(field.message_type, visited, max_depth, depth + 1)

def is_map_field(field):
    if field.label == FieldDescriptor.LABEL_REPEATED and field.message_type:
        return field.message_type.GetOptions().map_entry
    return False
```

## 6. Type Mapping for Schema Validation

Proto type to canonical type:

- `TYPE_BOOL` -> `bool`
- `TYPE_BYTES` -> `bytes`
- `TYPE_DOUBLE` -> `float`
- `TYPE_ENUM` -> `enum`
- `TYPE_FIXED32` -> `int32`
- `TYPE_FIXED64` -> `int64`
- `TYPE_FLOAT` -> `float`
- `TYPE_INT32` -> `int32`
- `TYPE_INT64` -> `int64`
- `TYPE_MESSAGE` -> `Message[ClassName]`
- `TYPE_SFIXED32` -> `int32`
- `TYPE_SFIXED64` -> `int64`
- `TYPE_SINT32` -> `int32`
- `TYPE_SINT64` -> `int64`
- `TYPE_STRING` -> `str`
- `TYPE_UINT32` -> `int`
- `TYPE_UINT64` -> `int`

Cardinality to Python types:

- `LABEL_OPTIONAL` -> `Optional[T]`
- `LABEL_REPEATED` -> `List[T]`
- `map<K,V>` -> `Dict[K,V]`
- `oneof` -> `Union[...]`

Pydantic mapping:

- proto optional string -> `Optional[str]`
- proto string -> `str`
- proto repeated message -> `List[Model]`
- proto map -> `Dict[K, Model]`
- proto message -> Pydantic `BaseModel`
- proto enum -> Pydantic `Enum` or `int`

## 7. Practical Code Examples

Extract all field names and types:

```python
descriptor = DoclingDocument.DESCRIPTOR
for field in descriptor.fields:
    print(f"{field.name}: {field.type}")
```

Find nested messages:

```python
def find_nested_messages(msg_desc, results=None):
    if results is None:
        results = {}
    for field in msg_desc.fields:
        if field.type == FieldDescriptor.TYPE_MESSAGE:
            results[field.name] = field.message_type.name
            find_nested_messages(field.message_type, results)
    return results
```

Extract dotted field paths:

```python
def build_paths(msg_desc, prefix="", max_depth=2, depth=0):
    if depth >= max_depth:
        return []
    paths = []
    for field in msg_desc.fields:
        full_path = f"{prefix}.{field.name}" if prefix else field.name
        paths.append(full_path)
        if field.type == FieldDescriptor.TYPE_MESSAGE:
            paths.extend(build_paths(field.message_type, full_path, max_depth, depth + 1))
    return paths
```

Compare Pydantic and proto schemas:

```python
def compare_schemas(proto_msg_desc, pydantic_model):
    proto_fields = {f.name for f in proto_msg_desc.fields}
    pydantic_fields = pydantic_model.model_fields.keys()
    return {
        "missing": proto_fields - set(pydantic_fields),
        "extra": set(pydantic_fields) - proto_fields,
    }
```

Build a schema metadata dict:

```python
def extract_schema(msg_desc):
    schema = {}
    for field in msg_desc.fields:
        schema[field.name] = {
            "type": field.type,
            "label": field.label,
            "is_repeated": field.label == FieldDescriptor.LABEL_REPEATED,
            "is_optional": field.has_presence,
            "message": field.message_type.full_name if field.message_type else None,
            "enum": field.enum_type.name if field.enum_type else None,
        }
    return schema
```

## 8. Important Gotchas and Tips

1. Avoid `field.label` for logic; prefer `is_repeated()` and `has_presence`.
2. Maps are repeated message fields with `map_entry = True`.
3. Proto3 optional fields create implicit oneofs (names like `_field`).
4. Avoid infinite recursion by tracking visited message names.
5. Enum values have `.name` and `.number`.
6. This codebase uses proto3.

## 9. Files and Locations in This Project

Source proto definition:

- `proto/ai/docling/core/v1/docling_document.proto`

Generated Python bindings:

- `docling_serve/grpc/gen/ai/docling/core/v1/docling_document_pb2.py`

Import path:

```python
from docling_serve.grpc.gen.ai.docling.core.v1 import docling_document_pb2
descriptor = docling_document_pb2.DoclingDocument.DESCRIPTOR
```

Proto package:

- `ai.docling.core.v1`

Top-level messages (selection):

- `DoclingDocument`
- `DocumentOrigin`
- `GroupItem`
- `RefItem`
- `FineRef`
- `TrackSource`
- `SourceType`
- `BaseMeta`
- `SummaryMetaField`
- `Formatting`
- `BaseTextItem`
- `TextItemBase`
- `TitleItem`
- `SectionHeaderItem`
- `ListItem`
- `CodeItem`
- `FormulaItem`
- `TextItem`
- `ProvenanceItem`
- `BoundingBox`
- `ImageRef`
- `Size`
- `PictureItem`
- `PictureMeta`

Key enums (selection):

- `ContentLayer`
- `GroupLabel`
- `DocItemLabel`
- `Script`
- `GraphCellLabel`
- `GraphLinkLabel`

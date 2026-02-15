# gRPC Schema Validation Matrix

This document defines how to validate the Docling Pydantic schema against protobuf descriptors at startup. The goal is to prevent data loss and hard-fail on breaking type mismatches, while tolerating missing fields with warnings.

## 1) Core Rules

- **Type mismatch**: fail hard.
- **Missing field**: warn only.
- **Known coercions**: allowed explicitly via an allowlist.

The validator should compare **Pydantic model fields** against **protobuf descriptors**. JSON exports must use the canonical Pydantic serializer and must not be derived from protobuf.

---

## 2) Cardinality Rules

### Proto -> Pydantic

| Proto Field | Expected Pydantic |
|------------|-------------------|
| singular (non-repeated) | `T` or `Optional[T]` |
| `optional` (proto3 presence) | `Optional[T]` |
| `repeated T` | `List[T]` |
| `map<K, V>` | `Dict[K, V]` |
| `oneof {A,B}` | `Union[A,B]` or discriminated union |

**Hard fail** if:
- proto `repeated` ↔ Pydantic not list-like
- proto `map` ↔ Pydantic not dict-like
- proto `oneof` ↔ Pydantic not union-like

---

## 3) Pydantic Canonical Type Mapping

Normalize Pydantic types into canonical forms before comparison:

| Pydantic Type | Canonical |
|-------------|-----------|
| `str` | `string` |
| `int` | `int` |
| `float` | `float` |
| `bool` | `bool` |
| `bytes` | `bytes` |
| `Enum` | `enum` |
| `BaseModel` subclass | `message:<ModelName>` |
| `List[T]` | `list<T>` |
| `Dict[K,V]` | `map<K,V>` |
| `Optional[T]` | `optional<T>` |
| `Union[A,B]` | `union<A,B>` |
| `Literal["x"]` | treat as `string` with constraint |

**Notes**
- `Annotated[...]`: strip and use inner type.
- `Tuple[int,int]`: treat as `list<int>` if proto uses repeated int (e.g., `charspan`).
- Discriminated unions: treat as `union` with discriminator.

---

## 4) Proto Canonical Type Mapping

| Proto FieldDescriptor | Canonical |
|----------------------|-----------|
| TYPE_STRING | `string` |
| TYPE_BOOL | `bool` |
| TYPE_BYTES | `bytes` |
| TYPE_DOUBLE / TYPE_FLOAT | `float` |
| TYPE_INT32 / SINT32 / SFIXED32 / FIXED32 / UINT32 | `int32` |
| TYPE_INT64 / SINT64 / SFIXED64 / FIXED64 / UINT64 | `int64` |
| TYPE_ENUM | `enum:<EnumName>` |
| TYPE_MESSAGE | `message:<MessageName>` |

**Cardinality**
- `label == LABEL_REPEATED` → `list<T>` unless `map_entry` → `map<K,V>`
- `has_presence == True` → `optional<T>`

---

## 5) Type Compatibility Matrix

### Primitive Types

| Pydantic | Proto | Result |
|---------|-------|--------|
| `string` | `string` | OK |
| `int` | any int32/int64 | OK (subject to allowlist) |
| `float` | `float` | OK |
| `bool` | `bool` | OK |
| `bytes` | `bytes` | OK |

### Messages

| Pydantic | Proto | Result |
|---------|-------|--------|
| `message:Foo` | `message:Foo` | OK |
| `message:Foo` | `message:Bar` | FAIL |

### Enums

| Pydantic | Proto | Result |
|---------|-------|--------|
| `enum:Foo` | `enum:Foo` | OK |
| `enum:Foo` | `enum:Bar` | FAIL |
| `enum:Foo` | `string` | FAIL unless allowlisted |

### Lists / Maps

| Pydantic | Proto | Result |
|---------|-------|--------|
| `list<T>` | repeated `T` | OK |
| `map<K,V>` | map `K,V` | OK |
| `tuple[T,T]` | repeated `T` | OK if allowlisted |

---

## 6) Known / Allowed Coercions (Allowlist)

These must be explicitly configured. Otherwise they are **FAIL**:

1) **binary_hash**
- Pydantic: `int`
- Proto: `string`
- **Allowed** (int -> string)

2) **pages map key**
- Pydantic: `Dict[int, PageItem]`
- Proto: `map<string, PageItem>`
- **Allowed** (int -> string)

3) **label fields stored as strings in proto**
- Pydantic: Enum
- Proto: string
- **Allowed** only if explicitly listed

4) **charspan**
- Pydantic: `Tuple[int, int]`
- Proto: repeated int
- **Allowed**

---

## 7) Oneof / Union Rules

Proto `oneof` must map to a Pydantic union.

Example:
- Proto `BaseTextItem` (oneof title/section_header/...) 
  ↔ Pydantic `Union[TitleItem, SectionHeaderItem, ...]`

**Fail** if:
- oneof maps to a single type
- Pydantic uses an untyped dict or Any

---

## 8) Optional vs Required

Proto3 does not enforce required fields, so strictness is relaxed.

- Pydantic required but proto optional: **warn only**
- Proto required (proto2) but Pydantic optional: **warn only**

---

## 9) Missing Field Policy

- Field exists in Pydantic but not proto → **WARN**
- Field exists in proto but not Pydantic → **WARN**
- Only **type mismatch** → **FAIL**

---

## 10) Suggested Validator Outputs

- **Missing fields**: list + warning
- **Type mismatches**: list + fail
- **Allowed coercions**: list + info

---

## 11) Descriptor API Quick Reference

- Proto descriptor: `DoclingDocument.DESCRIPTOR`
- Field access: `.fields_by_name['field']`
- Map fields: `field.message_type.GetOptions().map_entry == True`
- Oneof: `descriptor.oneofs_by_name['name']`
- Optional (proto3 presence): `field.has_presence == True`

---

## 12) Notes on JSON Exports

- JSON export must always use the canonical Pydantic serializer.
- JSON must **not** be derived from protobuf conversion.
- Protobuf conversion is separate and should never drive JSON output.

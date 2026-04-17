# Keeping the gRPC Branch in Sync With Upstream

This document is the procedure for keeping the gRPC branches in sync with
upstream `main` while the gRPC PRs are open. The two PRs evolve together:

- `docling-core` — adds the proto IDL and the Pydantic↔proto converter.
- `docling-serve` — adds the gRPC server, mapping layer, and startup
schema validator that enforces parity between Pydantic and proto.

Run this end-to-end every time `main` advances on either repo. The whole
loop is designed to surface upstream drift mechanically; you should not
have to inspect upstream commits by hand to know whether the proto needs
updating.

## Design Contract (Read This First)

The contract that makes this sync mechanical:

1. **Pydantic is the source of truth.** The proto mirrors it 1:1 in
  semantics, never the other way around.
2. **Proto uses proto-native idioms.** Closed enums (not strings), `int32`
  / `uint64` (not stringified ints), message-typed configs (not opaque
   blobs), `oneof` for unions. This is feature parity, not field-by-field
   REST mirroring.
3. **Forward-compat companions are proto-only.** Fields like `label_raw`,
  `code_language_raw`, `language_raw`, `coord_origin_raw` exist in proto
   to carry unknown enum values across version skew. They are explicitly
   allowlisted in the schema validator and never appear in Pydantic.
4. **The startup schema validator is the enforcement.** It walks the
  Pydantic `DoclingDocument` model and asserts the proto descriptor
   covers every field, with allowlisted exceptions documented inline.

When this loop fails, the contract is the design rubric to apply.

## Prerequisites

- A working dev environment for both repos (the standard `uv sync`
workflow described in each repo's contributor docs).
- Both repos checked out as siblings, with the gRPC feature branch
checked out and the upstream remote configured. The serve repo's
`scripts/gen_grpc.py` looks for the core proto either in the installed
`docling_core` package or in a sibling `../docling-core/proto`
directory, so a sibling clone is the simplest setup.

## The Sync Loop

### 1. Pull upstream and merge into both feature branches

In each repo, on the gRPC feature branch:

```sh
git fetch upstream
git merge upstream/main
```

Resolve any conflicts. The recurring ones are:

- `**pyproject.toml**` — keep both sides: the upstream dependency changes
*and* any local `[tool.uv.sources]` entries that point at a sibling
`docling-core` working copy.
- `**uv.lock*`* — take upstream's version, then re-run `uv sync` (next
step) to reconcile against any local source overrides.

### 2. Re-sync dependencies

In the serve repo:

```sh
uv sync --group cpu --no-group pypi
```

(Use whichever dependency group matches your local hardware; the point
is to pull in the upstream-bumped versions of `docling`, `docling-core`,
`docling-jobkit`, etc.)

### 3. Regenerate the proto stubs

This is non-negotiable; proto changes from `main` (rare, but possible)
or from your own edits below must be reflected in the committed
generated files.

```sh
# in docling-core
uv run python scripts/gen_proto.py

# in docling-serve
uv run python scripts/gen_grpc.py
```

### 4. Run the schema validator and the gRPC test suites

This is where upstream drift surfaces.

```sh
# docling-core: proto + Pydantic round-trip
uv run pytest test/test_proto_conversion.py -q

# docling-serve: schema validator + mapping + converter
uv run pytest \
  tests/test_schema_validator.py \
  tests/test_grpc_mapping.py \
  tests/test_docling_document_converter.py \
  tests/test_grpc_service_fake.py \
  tests/test_field_items_conversion.py \
  -q
```

The signals to watch for:

- `test_no_warnings_on_current_schemas` failing with
`Fields in Pydantic but not in proto (...)` — upstream Pydantic added
a field to `DoclingDocument` (or one of its members). Add the
equivalent proto field and a converter helper. See
[Adding a New Pydantic Field](#adding-a-new-pydantic-field-to-the-proto)
below.
- `test_no_warnings_on_current_schemas` failing with
`Fields in proto but not in Pydantic (...)` — the proto has a field
upstream Pydantic doesn't. Either upstream removed something (delete
the proto field, or document an intentional divergence) or the new
field is a forward-compat `*_raw` companion (add its suffix to
`_RAW_FALLBACK_SUFFIXES` in `schema_validator.py`).
- `test_grpc_mapping.py` import-time failure such as
`AttributeError: type object '...' has no attribute '...'` — upstream
renamed or removed an enum value the mapping references. Update the
mapping; for renamed-but-equivalent values, keep the old proto enum
name and map it to the new Pydantic value to preserve wire
compatibility for existing clients.
- `test_enum_mappings` failure — a new enum value exists in upstream
Pydantic. Add it to the proto enum, regenerate, and add the mapping.

### 4b. Drift-guard tests are the authoritative check

The `test_*_proto_covers_pydantic` tests in `tests/test_grpc_mapping.py`
assert that every Pydantic enum member is reachable from at least one
proto tag via the mapping, regardless of name spelling. These are the
authoritative drift checks for any enum where the proto and Pydantic
names might diverge. Add a similar guard for every new enum mapping
you introduce.

Under the pre-release rename policy (see "When Upstream Renames or
Removes an Enum Value" below), the manual proto-vs-Pydantic name diff
should be zero. If it is not zero, either align the proto names or add
a drift-guard test that explains the asymmetry.

### 5. Inspect Pydantic options for additive fields the validator can't see

The schema validator only walks `DoclingDocument`. It does not compare
`ConvertDocumentsRequestOptions` against `ConvertDocumentOptions` proto.
For the request options, do a manual diff each cycle:

```sh
uv run python - <<'PY'
from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions
for name, info in ConvertDocumentsRequestOptions.model_fields.items():
    print(f"{name}: {info.annotation}")
PY
```

Cross-reference the output against `ConvertDocumentOptions` in
`proto/ai/docling/serve/v1/docling_serve_types.proto`. Add any new
fields with the next available field number, regenerate stubs, wire
them into `to_convert_options` in `docling_serve/grpc/mapping.py`, and
add a focused test in `tests/test_grpc_mapping.py`.

### 6. Re-run all tests, then commit

Re-run step 4 to confirm green, then commit each logical change as its
own commit (proto change, converter change, mapping change, tests). Do
not squash the upstream merge with the proto changes — reviewers should
be able to read the merge separately from the parity work.

## Adding a New Pydantic Field to the Proto

When the validator surfaces a missing field, the workflow is:

1. **Inspect the Pydantic field.** Look up its type, optionality, and
  any nested model.
2. **Add the proto field** in the corresponding message in
  `proto/ai/docling/core/v1/docling_document.proto` (or
   `docling_serve_types.proto` for serve options). Pick the next
   available field number on that message. Use `optional` for nullable
   scalars, message types for nested models, `repeated` for lists,
   `map<K, V>` for dicts. For enums, define a closed proto enum mirror
   and add a companion `<field>_raw` `optional string` for forward
   compatibility, then register the suffix in `_RAW_FALLBACK_SUFFIXES`.
3. **Add a converter helper** in `docling_core/utils/conversion.py`
  following the existing patterns (e.g. `_to_code_meta`,
   `_to_doc_item_label_enum_and_raw`). Wire it from the parent
   converter (e.g. `_to_picture_meta`).
4. **Regenerate** with `scripts/gen_proto.py` then `scripts/gen_grpc.py`.
5. **Add tests** in `test/test_proto_conversion.py` (core) covering the
  new field and the unknown-enum fallback if applicable. The serve
   schema validator test will then automatically pass.

If the field is a deliberate divergence (proto has it, Pydantic does
not, or the types cannot be made equivalent), document it in
`proto/ai/docling/core/v1/PARITY.md` and add the suppression to the
appropriate ruleset in `docling_serve/grpc/schema_validator.py` with a
comment explaining why.

## Adding a New Enum Value

Enum additions are non-breaking on the wire. The procedure:

1. Add the new value to the proto enum with the next numeric tag.
2. Add the mapping entry in `docling_core/utils/conversion.py` (for
  document enums) or `docling_serve/grpc/mapping.py` (for serve
   enums).
3. Regenerate stubs.
4. Add an assertion in the relevant `test_enum_mappings` test.

For enums the proto already has a `*_raw` fallback companion for, the
old value will continue to round-trip through that field on older
clients without breaking — that is the design intent.

## When Upstream Renames or Removes an Enum Value

The right action depends on whether the gRPC PR has been **released**.

### Pre-release (gRPC PR not merged yet)

There are no wire consumers, so align the proto names directly with
the Pydantic names. Concretely:

- **Rename**: rename the proto enum value to match the new Pydantic
  name. Reuse the existing numeric tag if you like — wire stability is
  irrelevant here. Update the mapping entry's key, regenerate stubs,
  and update any test references to the old name.
- **Removal**: delete the proto enum value entirely and remove the
  corresponding mapping entry. Renumber siblings to keep the tag
  sequence tidy if you prefer; this is the right time to do it.

This is the policy in effect today. Keep doing this until the gRPC
PR ships in a tagged release.

### Post-release (gRPC PR merged and published)

Proto enums become append-only on the wire; you cannot remove or
renumber a tag without breaking deployed clients.

- **Rename to a semantically equivalent value** (e.g.
  `AUTOMODEL_VISION2SEQ` → `AUTOMODEL_IMAGETEXTTOTEXT`): keep the old
  proto enum tag, but update the mapping to translate it to the new
  Pydantic value. Add a comment on the mapping entry explaining the
  rename so future readers know why.
- **Pure removal**: leave the proto tag in place but map it to `None`
  (treated as unknown) in the mapping function. Document the removal
  in `PARITY.md`.

The drift-guard tests (`test_*_proto_covers_pydantic` in
`tests/test_grpc_mapping.py`) will catch any Pydantic value that
becomes unreachable from the mapping, regardless of the policy in
effect.

## Pushing the Update

After everything is green and committed, push the feature branches and
let CI run on the PRs. The PRs themselves should be flagged as drafts
or kept in their existing state — pushing the merge keeps them clean
relative to `main` so the diff stays focused on the gRPC additions.

## Failure Modes Checklist


| Symptom                                              | Likely cause                                         | Where to fix                                                        |
| ---------------------------------------------------- | ---------------------------------------------------- | ------------------------------------------------------------------- |
| `tree_sitter` import error in core tests             | New upstream chunker dep not in your venv            | Re-run `uv sync` with the appropriate group; not a PR concern       |
| Validator: "Fields in Pydantic but not in proto"     | Upstream added a model field                         | Add proto field + converter                                         |
| Validator: "Fields in proto but not in Pydantic"     | Upstream removed a field, or a new `*_raw` was added | Remove proto field, document divergence, or register the raw suffix |
| Mapping import fails on enum attribute               | Upstream renamed/removed an enum value               | Update `mapping.py` and translate the old proto tag                 |
| Type mismatch: `int` vs `string`, `enum` vs `string` | Pydantic type tightened (or proto loosened)          | Update proto to the proto-native equivalent; never relax the proto  |
| `uv.lock` merge conflict                             | Upstream and local both bumped versions              | Take upstream's version, re-run `uv sync`                           |


## Why This Works

The whole loop hinges on the schema validator running at startup *and*
in tests. Every Pydantic field has to be accounted for in the proto, or
explicitly suppressed with a documented reason. There is no quiet
divergence — drift becomes a test failure, and the failure tells you
exactly which field changed.
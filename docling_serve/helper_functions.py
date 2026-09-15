import importlib.metadata
import inspect
import json
import platform
import re
import sys
import types
from collections.abc import Callable
from typing import Any, Union, get_args, get_origin

from fastapi import Depends, Form
from fastapi.exceptions import RequestValidationError
from pydantic import AnyUrl, BaseModel, TypeAdapter, ValidationError

DOCLING_VERSIONS = {
    "docling-serve": importlib.metadata.version("docling-serve"),
    "docling-jobkit": importlib.metadata.version("docling-jobkit"),
    "docling": importlib.metadata.version("docling-slim"),
    "docling-core": importlib.metadata.version("docling-core"),
    "docling-ibm-models": importlib.metadata.version("docling-ibm-models"),
    "docling-parse": importlib.metadata.version("docling-parse"),
    "python": f"{sys.implementation.cache_tag} ({platform.python_version()})",
    "plaform": platform.platform(),
}


def is_union(type_) -> bool:
    """Match both spellings of a union: ``Optional[X]``/``Union[X, Y]`` and ``X | Y``.

    They do not share an origin: `get_origin` returns `typing.Union` for the former
    and `types.UnionType` for the latter.
    """
    return get_origin(type_) in (Union, types.UnionType)


def is_pydantic_model(type_):
    try:
        if inspect.isclass(type_) and issubclass(type_, BaseModel):
            return True

        if is_union(type_):
            args = get_args(type_)
            return any(
                inspect.isclass(arg) and issubclass(arg, BaseModel)
                for arg in args
                if arg is not type(None)
            )

    except Exception:
        pass

    return False


def is_json_field(type_):
    """Return True for dict fields (including Optional[dict]) that
    must be accepted as JSON strings from multipart form data."""
    try:
        if get_origin(type_) is dict:
            return True
        if is_union(type_):
            for arg in get_args(type_):
                if arg is type(None):
                    continue
                if get_origin(arg) is dict:
                    return True
    except Exception:
        pass
    return False


def _jsonable(value: Any) -> Any:
    """Reduce a pydantic error payload to something the 422 response can carry.

    Pydantic puts the offending value in ``input`` and validator internals in
    ``ctx``; either can be a model instance or an exception object, which would
    either blow up or bloat the error response.
    """
    if isinstance(value, str | int | float | bool | type(None)):
        return value
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return str(value)


def _as_validation_errors(
    exc: ValidationError, loc_for: Callable[[tuple[Any, ...]], tuple[Any, ...]]
) -> list[dict[str, Any]]:
    """Re-anchor pydantic errors onto the multipart form field that carried them."""
    errors: list[dict[str, Any]] = []
    for error in exc.errors(include_url=False):
        loc = ("body", *loc_for(tuple(error.get("loc", ()))))
        new_error: dict[str, Any] = {
            "type": error.get("type", "value_error"),
            "loc": loc,
            "msg": error.get("msg", str(exc)),
        }
        # Model-level errors carry the whole options object as their input, which on
        # the form path is every field including the defaults the caller never sent.
        if "input" in error and loc != ("body",):
            new_error["input"] = _jsonable(error["input"])
        if error.get("ctx"):
            new_error["ctx"] = _jsonable(error["ctx"])
        errors.append(new_error)
    return errors


def _build_form_parameter(
    field_name: str,
    model_field: Any,
    prefix: str,
    form_defaults: dict[str, Any],
) -> inspect.Parameter:
    """Build a single :class:`inspect.Parameter` for *field_name* and record its
    default in *form_defaults* (mutated in place)."""
    annotation = model_field.annotation
    description = model_field.description

    default = (
        Form(..., description=description, examples=model_field.examples)
        if model_field.is_required()
        else Form(
            model_field.default,
            examples=model_field.examples,
            description=description,
        )
    )

    if not model_field.is_required():
        form_defaults[field_name] = model_field.default

    # Flatten nested Pydantic models by accepting them as JSON strings
    if is_pydantic_model(annotation):
        annotation = str
        form_default = (
            None
            if model_field.default is None
            else json.dumps(model_field.default.model_dump(mode="json"))
        )
        form_defaults[field_name] = form_default
        default = Form(
            form_default,
            description=description,
            examples=None
            if not model_field.examples
            else [
                json.dumps(ex.model_dump(mode="json")) for ex in model_field.examples
            ],
        )
    elif is_json_field(annotation):
        annotation = str
        form_default = (
            None if model_field.default is None else json.dumps(model_field.default)
        )
        form_defaults[field_name] = form_default
        default = Form(
            form_default,
            description=description,
            examples=None
            if not model_field.examples
            else [json.dumps(ex) for ex in model_field.examples],
        )

    return inspect.Parameter(
        name=f"{prefix}{field_name}",
        kind=inspect.Parameter.POSITIONAL_ONLY,
        default=default,
        annotation=annotation,
    )


# Adapted from
# https://github.com/fastapi/fastapi/discussions/8971#discussioncomment-7892972
def FormDepends(
    cls: type[BaseModel], prefix: str = "", excluded_fields: list[str] = []
):
    new_parameters = []
    # Value FastAPI substitutes for each field when the client omits it. Used
    # below to tell an omitted field from one the client actually sent.
    form_defaults: dict[str, Any] = {}

    for field_name, model_field in cls.model_fields.items():
        if field_name in excluded_fields:
            continue
        new_parameters.append(
            _build_form_parameter(field_name, model_field, prefix, form_defaults)
        )

    async def as_form_func(**data):
        newdata = {}
        errors: list[dict[str, Any]] = []
        for field_name, model_field in cls.model_fields.items():
            if field_name in excluded_fields:
                continue
            form_field = f"{prefix}{field_name}"
            value = data.get(form_field)
            if field_name in form_defaults and value == form_defaults[field_name]:
                # The client did not send this field: leave it out so the model
                # applies its own default and model_fields_set stays truthful.
                # Validators that key on which fields were set (e.g. syncing a
                # deprecated option onto its replacement) depend on this.
                continue
            newdata[field_name] = value
            annotation = model_field.annotation

            # Parse nested models and dict/list fields from JSON string
            if value is not None and is_pydantic_model(annotation):
                try:
                    validator = TypeAdapter(annotation)
                    newdata[field_name] = validator.validate_json(value)
                except ValidationError as e:
                    errors.extend(
                        _as_validation_errors(
                            e, lambda loc, name=form_field: (name, *loc)
                        )
                    )
            elif value is not None and is_json_field(annotation):
                try:
                    newdata[field_name] = json.loads(value)
                except ValueError as e:
                    errors.append(
                        {
                            "type": "json_invalid",
                            "loc": ("body", form_field),
                            "msg": f"Invalid JSON: {e}",
                            "input": value,
                        }
                    )

        if errors:
            raise RequestValidationError(errors)

        try:
            return cls(**newdata)
        except ValidationError as e:
            # Field, cross-field and model validators all land here; their locations
            # are model field names, which must be mapped back to form field names.
            raise RequestValidationError(
                _as_validation_errors(
                    e,
                    lambda loc: (f"{prefix}{loc[0]}", *loc[1:]) if loc else (),
                )
            ) from e

    sig = inspect.signature(as_form_func)
    sig = sig.replace(parameters=new_parameters)
    as_form_func.__signature__ = sig  # type: ignore

    return Depends(as_form_func)


def parse_callback_item(value: str):
    """Decode one ``callbacks`` multipart form field value into a ``CallbackSpec``.

    Two accepted formats:

    * **Full JSON object** - ``{"url": "https://...", "headers": {...}, "ca_cert": "..."}``
    * **Bare URL** - ``https://hook.example.com/done``  (shortcut; headers and ca_cert
      default to their ``CallbackSpec`` defaults)

    The full-JSON path is tried first; a parse failure falls through to the bare-URL
    interpretation so callers never need to JSON-encode a plain URL.
    """
    # Import here to avoid a hard dependency at module level when callbacks are unused.
    from docling.datamodel.service.callbacks import CallbackSpec

    value = value.strip()
    try:
        return CallbackSpec.model_validate_json(value)
    except (ValueError, ValidationError):
        # Treat the raw string as the callback URL.
        try:
            return CallbackSpec(url=AnyUrl(value))
        except ValidationError as e:
            raise RequestValidationError(
                _as_validation_errors(e, lambda loc: ("callbacks", *loc))
            ) from e


def _to_list_of_strings(input_value: Union[str, list[str]]) -> list[str]:
    def split_and_strip(value: str) -> list[str]:
        if re.search(r"[;,]", value):
            return [item.strip() for item in re.split(r"[;,]", value)]
        else:
            return [value.strip()]

    if isinstance(input_value, str):
        return split_and_strip(input_value)
    elif isinstance(input_value, list):
        result = []
        for item in input_value:
            result.extend(split_and_strip(str(item)))
        return result
    else:
        raise ValueError("Invalid input: must be a string or a list of strings.")


# Helper functions to parse inputs coming as Form objects
def _str_to_bool(value: Union[str, bool]) -> bool:
    if isinstance(value, bool):
        return value  # Already a boolean, return as-is
    if isinstance(value, str):
        value = value.strip().lower()  # Normalize input
        return value in ("true", "1", "yes")
    return False  # Default to False if none of the above matches

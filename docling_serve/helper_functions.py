import inspect
import json
import re
from typing import Union, get_args, get_origin

from fastapi import Depends, Form
from pydantic import BaseModel, TypeAdapter


def is_pydantic_model(type_):
    try:
        if inspect.isclass(type_) and issubclass(type_, BaseModel):
            return True

        origin = get_origin(type_)
        if origin is Union:
            args = get_args(type_)
            return any(
                inspect.isclass(arg) and issubclass(arg, BaseModel)
                for arg in args
                if arg is not type(None)
            )

    except Exception:
        pass

    return False


# Adapted from
# https://github.com/fastapi/fastapi/discussions/8971#discussioncomment-7892972
def FormDepends(cls: type[BaseModel]):
    new_parameters = []

    for field_name, model_field in cls.model_fields.items():
        annotation = model_field.annotation
        description = model_field.description
        default = (
            Form(..., description=description)
            if model_field.is_required()
            else Form(
                model_field.default,
                examples=model_field.examples,
                description=description,
            )
        )

        # Flatten nested Pydantic models by accepting them as JSON strings
        if is_pydantic_model(annotation):
            annotation = str
            default = Form(
                None
                if model_field.default is None
                else json.dumps(model_field.default.model_dump(mode="json")),
                description=description,
                examples=None
                if not model_field.examples
                else [
                    json.dumps(ex.model_dump(mode="json"))
                    for ex in model_field.examples
                ],
            )

        new_parameters.append(
            inspect.Parameter(
                name=field_name,
                kind=inspect.Parameter.POSITIONAL_ONLY,
                default=default,
                annotation=annotation,
            )
        )

    async def as_form_func(**data):
        for field_name, model_field in cls.model_fields.items():
            value = data.get(field_name)
            annotation = model_field.annotation

            # Parse nested models from JSON string
            if value is not None and is_pydantic_model(annotation):
                try:
                    validator = TypeAdapter(annotation)
                    data[field_name] = validator.validate_json(value)
                except Exception as e:
                    raise ValueError(f"Invalid JSON for field '{field_name}': {e}")

        return cls(**data)

    sig = inspect.signature(as_form_func)
    sig = sig.replace(parameters=new_parameters)
    as_form_func.__signature__ = sig  # type: ignore

    return Depends(as_form_func)


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

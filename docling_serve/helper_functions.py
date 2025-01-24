import inspect
import re
from typing import List, Type, Union

from fastapi import Depends, Form
from pydantic import BaseModel


# Adapted from
# https://github.com/fastapi/fastapi/discussions/8971#discussioncomment-7892972
def FormDepends(cls: Type[BaseModel]):
    new_parameters = []

    for field_name, model_field in cls.model_fields.items():
        new_parameters.append(
            inspect.Parameter(
                name=field_name,
                kind=inspect.Parameter.POSITIONAL_ONLY,
                default=(
                    Form(...)
                    if model_field.is_required()
                    else Form(model_field.default)
                ),
                annotation=model_field.annotation,
            )
        )

    async def as_form_func(**data):
        return cls(**data)

    sig = inspect.signature(as_form_func)
    sig = sig.replace(parameters=new_parameters)
    as_form_func.__signature__ = sig  # type: ignore
    return Depends(as_form_func)


def _to_list_of_strings(input_value: Union[str, List[str]]) -> List[str]:
    def split_and_strip(value: str) -> List[str]:
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

import re
from typing import List, Union


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

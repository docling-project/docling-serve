import inspect
import re
from typing import Annotated, Any, Union, get_args, get_origin

from pydantic import BaseModel

from docling_serve.datamodel.convert import ConvertDocumentsRequestOptions

DOCS_FILE = "docs/usage.md"

VARIABLE_WORDS: list[str] = [
    "picture_description_local",
    "vlm_pipeline_model",
    "vlm",
    "vlm_pipeline_model_api",
    "ocr_engines_enum",
    "easyocr",
    "dlparse_v4",
    "docling_parse",
    "fast",
    "picture_description_api",
    "vlm_pipeline_model_local",
    "picture_description_preset",
    "picture_description_custom_config",
    "vlm_pipeline_preset",
    "vlm_pipeline_custom_config",
    "granite_docling",
    "model_spec",
    "engine_options",
]


def format_variable_names(text: str) -> str:
    """Format specific words in description to be code-formatted."""
    sorted_words = sorted(VARIABLE_WORDS, key=len, reverse=True)

    escaped_words = [re.escape(word) for word in sorted_words]

    for word in escaped_words:
        pattern = rf"(?<!`)\b{word}\b(?!`)"
        text = re.sub(pattern, f"`{word}`", text)

    return text


def format_allowed_values_description(description: str) -> str:
    """Format description to code-format allowed values."""
    # Regex pattern to find text after "Allowed values:"
    match = re.search(r"Allowed values:(.+?)(?:\.|$)", description, re.DOTALL)

    if match:
        # Extract the allowed values
        values_str = match.group(1).strip()

        # Split values, handling both comma and 'and' separators
        values = re.split(r"\s*(?:,\s*|\s+and\s+)", values_str)

        # Remove any remaining punctuation and whitespace
        values = [value.strip("., ") for value in values]

        # Create code-formatted values
        formatted_values = ", ".join(f"`{value}`" for value in values)

        # Replace the original allowed values with formatted version
        formatted_description = re.sub(
            r"(Allowed values:)(.+?)(?:\.|$)",
            f"\\1 {formatted_values}.",
            description,
            flags=re.DOTALL,
        )

        return formatted_description

    return description


def _format_type(type_hint: Any) -> str:
    """Format type ccrrectly, like Annotation or Union."""
    if get_origin(type_hint) is Annotated:
        base_type = get_args(type_hint)[0]
        return _format_type(base_type)

    if hasattr(type_hint, "__origin__"):
        origin = type_hint.__origin__
        args = get_args(type_hint)

        if origin is list:
            return f"List[{_format_type(args[0])}]"
        elif origin is dict:
            return f"Dict[{_format_type(args[0])}, {_format_type(args[1])}]"
        elif str(origin).__contains__("Union") or str(origin).__contains__("Optional"):
            return " or ".join(_format_type(arg) for arg in args)
        elif origin is None:
            return "null"

    if hasattr(type_hint, "__name__"):
        return type_hint.__name__

    return str(type_hint)


def _unroll_types(tp) -> list[type]:
    """
    Unrolls typing.Union and typing.Optional types into a flat list of types.
    """
    origin = get_origin(tp)
    if origin is Union:
        # Recursively unroll each type inside the Union
        types = []
        for arg in get_args(tp):
            types.extend(_unroll_types(arg))
        # Remove duplicates while preserving order
        return list(dict.fromkeys(types))
    else:
        # If it's not a Union, just return it as a single-element list
        return [tp]


def generate_model_doc(model: type[BaseModel]) -> str:
    """Generate documentation for a Pydantic model."""

    models_stack = [model]
    models_done = set()

    doc = ""
    while models_stack:
        current_model = models_stack.pop()
        models_done.add(current_model)

        doc += f"<h4>{current_model.__name__}</h4>\n"

        doc += "\n| Field Name | Type | Description |\n"
        doc += "|------------|------|-------------|\n"

        base_models = []
        if hasattr(current_model, "__mro__"):
            base_models = current_model.__mro__
        else:
            base_models = [current_model]

        for base_model in base_models:
            # Check if this is a Pydantic model
            if hasattr(base_model, "model_fields"):
                # Iterate through fields of this model
                for field_name, field in base_model.model_fields.items():
                    # Extract description from Annotated field if possible
                    description = field.description or "No description provided."
                    description = format_allowed_values_description(description)
                    description = format_variable_names(description)

                    # Handle Annotated types
                    original_type = field.annotation
                    if get_origin(original_type) is Annotated:
                        # Extract base type and additional metadata
                        type_args = get_args(original_type)
                        base_type = type_args[0]
                    else:
                        base_type = original_type

                    field_type = _format_type(base_type)
                    field_type = format_variable_names(field_type)

                    doc += f"| `{field_name}` | {field_type} | {description} |\n"

                    for field_type in _unroll_types(base_type):
                        if (
                            inspect.isclass(field_type)
                            and issubclass(field_type, BaseModel)
                            and field_type not in models_done
                        ):
                            models_stack.append(field_type)

                # stop iterating the base classes
                break

        doc += "\n"
    return doc


def update_documentation():
    """Update the documentation file with model information."""
    doc_request = generate_model_doc(ConvertDocumentsRequestOptions)

    with open(DOCS_FILE) as f:
        content = f.readlines()

    # Prepare to update the content
    new_content = []
    in_cp_section = False

    for line in content:
        if line.startswith("<!-- begin: parameters-docs -->"):
            in_cp_section = True
            new_content.append(line)
            new_content.append(doc_request)
            continue

        if in_cp_section and line.strip() == "<!-- end: parameters-docs -->":
            in_cp_section = False

        if not in_cp_section:
            new_content.append(line)

    # Only write to the file if new_content is different from content
    if "".join(new_content) != "".join(content):
        with open(DOCS_FILE, "w") as f:
            f.writelines(new_content)
        print(f"Documentation updated in {DOCS_FILE}")
    else:
        print("No changes detected. Documentation file remains unchanged.")


if __name__ == "__main__":
    update_documentation()

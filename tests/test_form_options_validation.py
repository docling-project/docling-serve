"""Invalid form options must be reported as 422, not crash with a 500.

The `/v1/convert/file` and `/v1/chunk/file` endpoints take their options as
multipart form fields, so `FormDepends` has to decode nested models and dict
fields from JSON strings itself. Every validation failure on that path has to
surface as a `RequestValidationError`, otherwise FastAPI never sees it as a
validation problem and the request fails with an unhandled-exception 500 —
unlike the JSON-body endpoints, which reject the same payload with a 422.
"""

from typing import Annotated, Optional, Union

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

from docling_serve.helper_functions import (
    FormDepends,
    is_json_field,
    is_pydantic_model,
    parse_callback_item,
)


class NestedOptions(BaseModel):
    enabled: bool = False
    max_level: int = 6


class Options(BaseModel):
    name: str = "default"
    # Field constraints are dropped when the field is flattened into a form
    # parameter, so they are only enforced once the model is rebuilt.
    threads: int = Field(default=1, ge=1, le=8)
    nested: NestedOptions = NestedOptions()
    other: NestedOptions | None = None
    custom_config: dict[str, str] | None = None

    @model_validator(mode="after")
    def nested_exclusivity(self) -> Self:
        if self.nested.enabled and self.other is not None:
            raise ValueError("nested and other are mutually exclusive")
        return self


@pytest.fixture(scope="module")
def form_app() -> FastAPI:
    app = FastAPI()

    @app.post("/options")
    async def read_options(
        options: Annotated[Options, FormDepends(Options)],
    ):
        return options.model_dump()

    @app.post("/prefixed")
    async def read_prefixed_options(
        options: Annotated[Options, FormDepends(Options, prefix="convert_")],
    ):
        return options.model_dump()

    return app


@pytest.fixture(scope="module")
def client(form_app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=form_app), base_url="http://app.io")


async def test_valid_options_still_pass(client: AsyncClient):
    response = await client.post(
        "/options",
        data={
            "nested": '{"enabled": true, "max_level": 3}',
            "custom_config": '{"key": "value"}',
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["nested"] == {"enabled": True, "max_level": 3}
    assert body["custom_config"] == {"key": "value"}


async def test_malformed_json_for_nested_model(client: AsyncClient):
    response = await client.post("/options", data={"nested": "{not json"})

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "nested"]
    assert error["type"] == "json_invalid"


async def test_invalid_value_inside_nested_model(client: AsyncClient):
    response = await client.post("/options", data={"nested": '{"max_level": "high"}'})

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "nested", "max_level"]
    assert error["input"] == "high"


async def test_malformed_json_for_dict_field(client: AsyncClient):
    response = await client.post("/options", data={"custom_config": "{oops"})

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "custom_config"]
    assert error["type"] == "json_invalid"


async def test_model_validator_failure(client: AsyncClient):
    """Cross-field checks run after the form fields are assembled, and fail there."""
    response = await client.post(
        "/options",
        data={"nested": '{"enabled": true}', "other": '{"enabled": false}'},
    )

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body"]
    assert "mutually exclusive" in error["msg"]
    # The whole options object, defaults included, is not echoed back.
    assert "input" not in error


async def test_field_constraint_failure_maps_to_its_form_field(client: AsyncClient):
    response = await client.post("/prefixed", data={"convert_threads": "99"})

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "convert_threads"]
    assert error["type"] == "less_than_equal"


async def test_all_invalid_fields_are_reported_together(client: AsyncClient):
    response = await client.post(
        "/options",
        data={"nested": "{nope", "custom_config": "{also nope"},
    )

    assert response.status_code == 422
    locations = [error["loc"] for error in response.json()["detail"]]
    assert ["body", "nested"] in locations
    assert ["body", "custom_config"] in locations


async def test_prefixed_form_fields_keep_their_prefix_in_the_error(client: AsyncClient):
    response = await client.post("/prefixed", data={"convert_nested": "{nope"})

    assert response.status_code == 422
    (error,) = response.json()["detail"]
    assert error["loc"] == ["body", "convert_nested"]


@pytest.mark.parametrize(
    "annotation",
    [
        Optional[NestedOptions],
        Union[NestedOptions, None],
        NestedOptions | None,
    ],
)
def test_optional_nested_models_are_detected_in_both_union_spellings(annotation):
    assert is_pydantic_model(annotation)


@pytest.mark.parametrize(
    "annotation",
    [
        Optional[dict[str, str]],
        Union[dict[str, str], None],
        dict[str, str] | None,
    ],
)
def test_optional_dicts_are_detected_in_both_union_spellings(annotation):
    assert is_json_field(annotation)


def test_unparsable_callback_raises_a_validation_error():
    """`parse_callback_item` falls back to a bare URL, which can itself be invalid."""
    from fastapi.exceptions import RequestValidationError

    with pytest.raises(RequestValidationError) as excinfo:
        parse_callback_item("not a url")

    (error,) = excinfo.value.errors()
    assert error["loc"] == ("body", "callbacks")

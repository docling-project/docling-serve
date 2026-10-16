"""Tests that FormDepends only reports the fields a client actually sent.

Regression coverage for #674: on the multipart endpoints every option used to be
passed to the model constructor, so `model_fields_set` claimed the client had set
every field. Validators that key on which fields were set - such as the one that
forwards the deprecated `ocr_engine` onto `ocr_preset` - therefore never fired,
and `ocr_engine` was silently ignored (and never validated) on those endpoints.
"""

from typing import Annotated, Any, Optional

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field, model_validator
from typing_extensions import Self

from docling_serve.helper_functions import FormDepends


class _NestedOptions(BaseModel):
    value: int = 1


class _Options(BaseModel):
    """Mirrors the deprecated-option shape of ConvertDocumentsOptions."""

    old_name: Annotated[str, Field(description="DEPRECATED: use new_name")] = "auto"
    new_name: Annotated[str, Field(description="Replacement option")] = "auto"
    do_ocr: bool = True
    ocr_lang: Optional[list[str]] = None
    nested: Optional[_NestedOptions] = None
    custom_config: Optional[dict[str, Any]] = None

    @model_validator(mode="after")
    def sync_deprecated_option(self) -> Self:
        if (
            "old_name" in self.model_fields_set
            and "new_name" not in self.model_fields_set
        ):
            object.__setattr__(self, "new_name", self.old_name)
        return self


def _client() -> TestClient:
    app = FastAPI()

    @app.post("/options")
    async def read_options(  # type: ignore[no-untyped-def]
        options: Annotated[_Options, FormDepends(_Options)],
    ):
        return {
            **options.model_dump(),
            "fields_set": sorted(options.model_fields_set),
        }

    return TestClient(app)


def test_deprecated_option_is_forwarded_to_its_replacement():
    response = _client().post("/options", data={"old_name": "tesseract"})
    assert response.status_code == 200
    body = response.json()
    assert body["fields_set"] == ["old_name"]
    assert body["new_name"] == "tesseract"


def test_explicit_replacement_wins_over_the_deprecated_option():
    response = _client().post(
        "/options", data={"old_name": "tesseract", "new_name": "easyocr"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["new_name"] == "easyocr"


def test_omitted_fields_keep_their_model_defaults():
    response = _client().post("/options", data={"do_ocr": "false"})
    assert response.status_code == 200
    body = response.json()
    assert body["fields_set"] == ["do_ocr"]
    assert body["do_ocr"] is False
    assert body["old_name"] == "auto"
    assert body["new_name"] == "auto"
    assert body["ocr_lang"] is None
    assert body["nested"] is None
    assert body["custom_config"] is None


def test_json_encoded_fields_are_still_parsed():
    response = _client().post(
        "/options",
        data={"nested": '{"value": 7}', "custom_config": '{"key": "value"}'},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["nested"] == {"value": 7}
    assert body["custom_config"] == {"key": "value"}
    assert body["fields_set"] == ["custom_config", "nested"]

"""Heading-hierarchy options must survive the multipart/form-data request path.

The `/v1/convert/file` endpoints take their options as form fields, which cannot
carry objects. `FormDepends` works around that by accepting nested models as JSON
strings, so a nested option that is never exercised through that path can silently
degrade to its default while the JSON-body path keeps working.
"""

from typing import Annotated

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from docling.datamodel.service.options import ConvertDocumentsOptions

from docling_serve.helper_functions import FormDepends


@pytest.fixture(scope="module")
def form_app() -> FastAPI:
    app = FastAPI()

    @app.post("/options")
    async def read_options(
        options: Annotated[
            ConvertDocumentsOptions, FormDepends(ConvertDocumentsOptions)
        ],
    ):
        return options.heading_hierarchy_options.model_dump()

    return app


@pytest.fixture(scope="module")
def client(form_app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=form_app), base_url="http://app.io")


@pytest.mark.asyncio
async def test_defaults_to_disabled(client: AsyncClient):
    response = await client.post("/options", data={"to_formats": ["md"]})

    assert response.status_code == 200
    assert response.json()["enabled"] is False


@pytest.mark.asyncio
async def test_nested_options_decoded_from_form_field(client: AsyncClient):
    response = await client.post(
        "/options",
        data={
            "to_formats": ["md"],
            "heading_hierarchy_options": (
                '{"enabled": true, "use_style": false, "max_level": 3,'
                ' "numbering_schemes": ["part", "arabic"]}'
            ),
        },
    )

    assert response.status_code == 200
    heading_options = response.json()
    assert heading_options["enabled"] is True
    assert heading_options["use_style"] is False
    assert heading_options["max_level"] == 3
    assert heading_options["numbering_schemes"] == ["part", "arabic"]
    # Unset keys keep their model defaults rather than being blanked out.
    assert heading_options["use_bookmarks"] is True

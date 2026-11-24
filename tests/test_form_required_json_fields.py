# Copyright IBM Inc. All rights reserved.
# SPDX-License-Identifier: MIT

import json
from typing import Annotated

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, create_model

from docling_serve.helper_functions import FormDepends


class Nested(BaseModel):
    value: int


@pytest.mark.parametrize(
    "annotation, value",
    [(Nested, '{"value": 7}'), (dict[str, int], '{"threads": 2}')],
)
def test_required_json_form_fields(annotation, value):
    options_model = create_model("RequiredOptions", option=(annotation, ...))
    app = FastAPI()

    @app.post("/options")
    async def options(form: Annotated[options_model, FormDepends(options_model)]):
        return form.model_dump()

    client = TestClient(app)
    assert client.post("/options").status_code == 422
    response = client.post("/options", data={"option": value})
    assert response.status_code == 200
    assert response.json() == {"option": json.loads(value)}

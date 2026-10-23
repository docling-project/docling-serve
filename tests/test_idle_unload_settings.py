# SPDX-License-Identifier: MIT

import pytest
from hypothesis import given, settings, strategies as st
from pydantic import ValidationError

from docling_serve.settings import AsyncEngine, DoclingServeSettings

ENGINE_CONFIG = {
    "eng_rq_redis_url": "redis://localhost",
    "eng_ray_redis_url": "redis://localhost",
    "eng_ray_address": "auto",
}


@settings(max_examples=1000, deadline=None)
@given(st.floats(min_value=0, allow_infinity=False, allow_nan=False))
def test_nonnegative_finite_timeout(value):
    assert DoclingServeSettings(idle_unload_seconds=value).idle_unload_seconds == value


@settings(max_examples=1000, deadline=None)
@given(st.floats().filter(lambda value: not value >= 0 or value == float("inf")))
def test_invalid_timeout_rejected(value):
    with pytest.raises(ValidationError):
        DoclingServeSettings(idle_unload_seconds=value)


@pytest.mark.parametrize("engine", list(AsyncEngine))
def test_default_and_zero(engine):
    assert (
        DoclingServeSettings(eng_kind=engine, **ENGINE_CONFIG).idle_unload_seconds == 0
    )
    assert (
        DoclingServeSettings(
            eng_kind=engine, idle_unload_seconds=0, **ENGINE_CONFIG
        ).idle_unload_seconds
        == 0
    )


@pytest.mark.parametrize("engine", [AsyncEngine.RQ, AsyncEngine.RAY])
def test_positive_timeout_requires_local(engine):
    with pytest.raises(ValidationError, match="local"):
        DoclingServeSettings(eng_kind=engine, idle_unload_seconds=1, **ENGINE_CONFIG)


def test_environment_and_config(monkeypatch, tmp_path):
    config = tmp_path / "settings.yaml"
    config.write_text("idle_unload_seconds: 12.5\n")
    monkeypatch.setenv("DOCLING_SERVE_CONFIG_FILE", str(config))
    assert DoclingServeSettings().idle_unload_seconds == 12.5
    monkeypatch.setenv("DOCLING_SERVE_IDLE_UNLOAD_SECONDS", "3.5")
    assert DoclingServeSettings().idle_unload_seconds == 3.5

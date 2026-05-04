"""Tests for RQ Redis Sentinel configuration in docling-serve."""

import pytest
from pydantic import ValidationError

from docling_serve.settings import AsyncEngine, DoclingServeSettings


class TestRedisSentinelSettings:
    def test_url_only_config_is_valid(self):
        settings = DoclingServeSettings(
            eng_kind=AsyncEngine.RQ,
            eng_rq_redis_url="redis://localhost:6379/",
        )
        assert settings.eng_rq_redis_sentinel_hosts is None
        assert settings.eng_rq_redis_sentinel_service_name is None

    def test_sentinel_only_config_is_valid(self):
        settings = DoclingServeSettings(
            eng_kind=AsyncEngine.RQ,
            eng_rq_redis_sentinel_hosts=["s1:26379", "s2:26379"],
            eng_rq_redis_sentinel_service_name="mymaster",
            eng_rq_redis_sentinel_password="secret",
            eng_rq_redis_sentinel_db=2,
        )
        assert settings.eng_rq_redis_url == ""
        assert settings.eng_rq_redis_sentinel_hosts == ["s1:26379", "s2:26379"]
        assert settings.eng_rq_redis_sentinel_service_name == "mymaster"
        assert settings.eng_rq_redis_sentinel_db == 2

    def test_neither_url_nor_sentinel_rejected(self):
        with pytest.raises(ValidationError, match="ENG_RQ_REDIS_URL"):
            DoclingServeSettings(eng_kind=AsyncEngine.RQ)

    def test_partial_sentinel_config_rejected(self):
        with pytest.raises(ValidationError, match="must be set together"):
            DoclingServeSettings(
                eng_kind=AsyncEngine.RQ,
                eng_rq_redis_url="redis://localhost:6379/",
                eng_rq_redis_sentinel_hosts=["s1:26379"],
            )

        with pytest.raises(ValidationError, match="must be set together"):
            DoclingServeSettings(
                eng_kind=AsyncEngine.RQ,
                eng_rq_redis_url="redis://localhost:6379/",
                eng_rq_redis_sentinel_service_name="mymaster",
            )

    def test_both_url_and_sentinel_accepted(self):
        # The Sentinel config wins at the orchestrator layer; we still allow
        # both fields so users can flip between them via env vars without
        # rewriting their settings file.
        settings = DoclingServeSettings(
            eng_kind=AsyncEngine.RQ,
            eng_rq_redis_url="redis://localhost:6379/",
            eng_rq_redis_sentinel_hosts=["s1:26379"],
            eng_rq_redis_sentinel_service_name="mymaster",
        )
        assert settings.eng_rq_redis_sentinel_hosts == ["s1:26379"]

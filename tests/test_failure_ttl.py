"""Tests for RQ failure_ttl configuration in docling-serve."""

from docling_serve.settings import DoclingServeSettings


class TestFailureTTLSettings:
    def test_default_failure_ttl_matches_results_ttl(self):
        settings = DoclingServeSettings(
            eng_rq_redis_url="redis://localhost:6379/",
        )
        assert settings.eng_rq_failure_ttl == settings.eng_rq_results_ttl
        assert settings.eng_rq_failure_ttl == 3_600 * 4

    def test_failure_ttl_is_configurable(self):
        settings = DoclingServeSettings(
            eng_rq_redis_url="redis://localhost:6379/",
            eng_rq_failure_ttl=7200,
        )
        assert settings.eng_rq_failure_ttl == 7200
        assert settings.eng_rq_results_ttl == 3_600 * 4

"""Tests for OpenTelemetry trace filtering of health and metrics endpoints."""

from unittest.mock import MagicMock, patch

import pytest
from opentelemetry.sdk.trace.sampling import Decision
from opentelemetry.trace import SpanKind
from opentelemetry.util.http import ExcludeList

from docling_serve.otel_instrumentation import (
    FILTERED_PATHS,
    HealthMetricsFilterSampler,
    setup_otel_instrumentation,
)


@pytest.fixture
def sampler():
    """Create a HealthMetricsFilterSampler instance."""
    return HealthMetricsFilterSampler()


class TestHealthMetricsFilterSampler:
    """Test the HealthMetricsFilterSampler."""

    @pytest.mark.parametrize(
        "path",
        [
            "/metrics",
            "/health",
            "/healthz",
            "/readyz",
            "/livez",
        ],
    )
    def test_filtered_paths_are_dropped(self, sampler, path):
        """Test that health and metrics endpoints are filtered out."""
        parent_context = MagicMock()
        trace_id = 12345
        name = f"GET {path}"
        attributes = {"http.target": path}

        result = sampler.should_sample(
            parent_context=parent_context,
            trace_id=trace_id,
            name=name,
            kind=SpanKind.SERVER,
            attributes=attributes,
        )

        assert result.decision == Decision.DROP

    @pytest.mark.parametrize(
        "path",
        [
            "/metrics?verbose=true",
            "/health?check=all",
            "/healthz?detailed=1",
            "/readyz?wait=5",
            "/livez?format=json",
        ],
    )
    def test_filtered_paths_with_query_params_are_dropped(self, sampler, path):
        """Test that filtered endpoints with query params are still dropped."""
        parent_context = MagicMock()
        trace_id = 12345
        name = f"GET {path.split('?')[0]}"
        attributes = {"http.target": path}

        result = sampler.should_sample(
            parent_context=parent_context,
            trace_id=trace_id,
            name=name,
            kind=SpanKind.SERVER,
            attributes=attributes,
        )

        assert result.decision == Decision.DROP

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/v1/documents",
            "/v1/convert",
            "/api/health",  # Different path
            "/healthcheck",  # Different path
            "/docs",
        ],
    )
    def test_other_paths_are_sampled(self, sampler, path):
        """Test that other endpoints are sampled normally."""
        parent_context = MagicMock()
        trace_id = 12345
        name = f"GET {path}"
        attributes = {"http.target": path}

        result = sampler.should_sample(
            parent_context=parent_context,
            trace_id=trace_id,
            name=name,
            kind=SpanKind.SERVER,
            attributes=attributes,
        )

        assert result.decision == Decision.RECORD_AND_SAMPLE

    def test_missing_http_target_attribute_is_sampled(self, sampler):
        """Test that spans without http.target are sampled."""
        parent_context = MagicMock()
        trace_id = 12345
        name = "some_operation"
        attributes = {"other.attribute": "value"}

        result = sampler.should_sample(
            parent_context=parent_context,
            trace_id=trace_id,
            name=name,
            kind=SpanKind.INTERNAL,
            attributes=attributes,
        )

        assert result.decision == Decision.RECORD_AND_SAMPLE

    def test_no_attributes_is_sampled(self, sampler):
        """Test that spans without attributes are sampled."""
        parent_context = MagicMock()
        trace_id = 12345
        name = "some_operation"

        result = sampler.should_sample(
            parent_context=parent_context,
            trace_id=trace_id,
            name=name,
            kind=SpanKind.INTERNAL,
            attributes=None,
        )

        assert result.decision == Decision.RECORD_AND_SAMPLE

    def test_filtered_paths_constant(self):
        """Test that FILTERED_PATHS contains expected endpoints."""
        expected_paths = {"/metrics", "/health", "/healthz", "/readyz", "/livez"}
        assert FILTERED_PATHS == expected_paths


class TestExcludedUrlsIntegration:
    """Test that setup_otel_instrumentation passes excluded_urls to FastAPIInstrumentor."""

    @patch("docling_serve.otel_instrumentation.FastAPIInstrumentor")
    def test_excluded_urls_passed_to_instrumentor(self, mock_instrumentor_cls):
        """Verify that FILTERED_PATHS are passed as excluded_urls to instrument_app."""
        app = MagicMock()

        setup_otel_instrumentation(
            app,
            enable_metrics=False,
            enable_traces=False,
        )

        mock_instrumentor_cls.instrument_app.assert_called_once()
        call_kwargs = mock_instrumentor_cls.instrument_app.call_args
        assert call_kwargs[0][0] is app
        excluded = call_kwargs[1]["excluded_urls"]
        for path in FILTERED_PATHS:
            assert f"{path}$" in excluded

    @patch("docling_serve.otel_instrumentation.FastAPIInstrumentor")
    def test_excluded_urls_is_comma_separated_anchored(self, mock_instrumentor_cls):
        """Verify excluded_urls is comma-separated, $-anchored FILTERED_PATHS."""
        app = MagicMock()

        setup_otel_instrumentation(
            app,
            enable_metrics=False,
            enable_traces=False,
        )

        call_kwargs = mock_instrumentor_cls.instrument_app.call_args
        excluded = call_kwargs[1]["excluded_urls"]
        parts = {p.strip() for p in excluded.split(",")}
        assert parts == {f"{p}$" for p in FILTERED_PATHS}

    @pytest.mark.parametrize(
        "path,should_exclude",
        [
            ("/health", True),
            ("/metrics", True),
            ("/healthz", True),
            ("/readyz", True),
            ("/livez", True),
            ("/v1/convert", False),
            ("/v1/documents", False),
            ("/docs", False),
            ("/healthcheck", False),
        ],
    )
    def test_excluded_urls_regex_matching(self, path, should_exclude):
        """Verify the ExcludeList built from FILTERED_PATHS matches expected URLs."""
        excluded_urls = ",".join(f"{p}$" for p in FILTERED_PATHS)
        exclude_list = ExcludeList(excluded_urls.split(","))
        url = f"http://localhost:5001{path}"
        assert exclude_list.url_disabled(url) == should_exclude

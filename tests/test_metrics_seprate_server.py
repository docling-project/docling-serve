"""Tests for serving Prometheus metrics on separate port"""

import socket
import urllib.request
from unittest.mock import MagicMock, patch

import pytest


def _free_port():
    """ Find a free TCP port"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


class TestMetricServer:
    """Test the separate Prometheus metrics HTTP server"""

    def test_metrics_server_starts_and_serve(self):
        """When metrics_port is set, a separate HTTP server serves /metrics"""
        port = _free_port()
        app = MagicMock()

        with patch("docling_serve.otel_instrumentation.FastAPIInstrumentor"):
            from docling_serve.otel_instrumentation import setup_otel_instrumentation

            setup_otel_instrumentation(
                app,
                enable_metrics=True,
                enable_traces=False,
                enable_prometheus=True,
                metrics_port=port,
            )

        resp = urllib.request.urlopen(f"http://localhost:{port}/metrics")
        assert resp.status == 200
        body = resp.read().decode()
        # Prometheus text format always contains a HELP or TYPE line
        assert "# HELP" in body or "# TYPE" in body

    def test_metrics_server_not_started_when_port_is_none(self):
        """When metrics_port is None, no separate server is started."""
        app = MagicMock()

        with patch("docling_serve.otel_instrumentation.FastAPIInstrumentor"):
            with patch("docling_serve.otel_instrumentation.start_http_server") as mock_start:
                from docling_serve.otel_instrumentation import (
                    setup_otel_instrumentation,
                )

                setup_otel_instrumentation(
                    app,
                    enable_metrics=True,
                    enable_traces=False,
                    enable_prometheus=True,
                    metrics_port=None,
                )

                mock_start.assert_not_called()

    def test_metrics_server_raises_on_port_bind_failure(self):
        """When metrics_port is None, no separate server is started."""
        port = _free_port()
        # Bind the port so start_http_server will fail
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("", port))
        blocker.listen(1)

        try:
            app = MagicMock()
            with patch("docling_serve.otel_instrumentation.FastAPIInstrumentor"):
                from docling_serve.otel_instrumentation import (
                    setup_otel_instrumentation,
                )

                with pytest.raises(RuntimeError, match="Failed to start metrics server"):
                    setup_otel_instrumentation(
                        app,
                        enable_metrics=True,
                        enable_traces=False,
                        enable_prometheus=True,
                        metrics_port=port,
                    )
        finally:
            blocker.close()

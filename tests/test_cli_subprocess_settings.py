"""The CLI's docling options must survive uvicorn's reload/worker subprocess.

`uvicorn.run(reload=True)` (and `workers > 1`) starts the server through
multiprocessing "spawn", so the child re-imports `docling_serve.settings` and
rebuilds `DoclingServeSettings` from the environment. Assigning to the settings
singleton in the parent therefore never reaches the server. These tests assert
on that hand-over channel: the environment `_run` leaves behind, read back
through a fresh `DoclingServeSettings()` exactly as the child builds it.
"""

import pytest
import uvicorn
from typer.testing import CliRunner

import docling_serve.__main__ as cli
from docling_serve.settings import DoclingServeSettings, docling_serve_settings

DOCLING_ENV = ("DOCLING_SERVE_ENABLE_UI", "DOCLING_SERVE_ARTIFACTS_PATH")


@pytest.fixture
def run_cli(monkeypatch):
    """Invoke the real CLI with the server stubbed out, and isolate globals."""
    for name in DOCLING_ENV:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        docling_serve_settings, "enable_ui", DoclingServeSettings().enable_ui
    )
    monkeypatch.setattr(
        docling_serve_settings, "artifacts_path", DoclingServeSettings().artifacts_path
    )

    captured: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **kw: captured.update(kw))

    def _invoke(*args: str):
        result = CliRunner().invoke(cli.app, list(args))
        if result.exception is not None and not isinstance(
            result.exception, SystemExit
        ):
            raise result.exception
        assert result.exit_code == 0, result.output
        return captured

    return _invoke


def test_dev_enables_the_ui_in_the_reload_subprocess(run_cli):
    """`docling-serve dev` reloads by default; its --enable-ui default is True."""
    captured = run_cli("dev")

    assert captured["reload"] is True, "dev is expected to run under the reloader"
    # What the spawned child rebuilds from the environment:
    assert DoclingServeSettings().enable_ui is True


def test_dev_no_enable_ui_is_propagated_too(run_cli):
    run_cli("dev", "--no-enable-ui")

    assert DoclingServeSettings().enable_ui is False


def test_workers_propagate_artifacts_path(run_cli, tmp_path):
    run_cli("run", "--workers", "2", "--artifacts-path", str(tmp_path))

    assert DoclingServeSettings().artifacts_path == tmp_path


def test_single_process_run_leaves_the_environment_alone(run_cli, monkeypatch):
    """Without reload/workers the app runs in-process, so the settings object
    is the channel and the environment must not be rewritten."""
    captured = run_cli("run", "--no-reload", "--enable-ui")

    assert captured["reload"] is False and captured["workers"] is None
    assert docling_serve_settings.enable_ui is True
    assert DoclingServeSettings().enable_ui is False

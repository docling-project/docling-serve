"""The CLI's docling options must survive uvicorn's reload/worker subprocess.

`uvicorn.run(reload=True)` (and `workers > 1`) starts the server through
multiprocessing "spawn", so the child re-imports `docling_serve.settings` and
rebuilds `DoclingServeSettings` from the environment. Assigning to the settings
singleton in the parent therefore never reaches the server. These tests assert
on that hand-over channel: the environment `_run` leaves behind, read back
through a fresh `DoclingServeSettings()` exactly as the child builds it.

The log level is the third such option. The CLI resolves it (`-v`/`-vv`, then
`DOCLING_SERVE_LOG_LEVEL`, then WARNING) into the settings; `docling_serve.app`
configures logging again from those settings when uvicorn imports it, so the
settings object is what the app module will find.
"""

import logging
import os

import pytest
import uvicorn
from typer.testing import CliRunner

import docling_serve.__main__ as cli
from docling_serve.settings import (
    DoclingServeSettings,
    LogLevel,
    docling_serve_settings,
)

DOCLING_ENV = (
    "DOCLING_SERVE_ENABLE_UI",
    "DOCLING_SERVE_ARTIFACTS_PATH",
    "DOCLING_SERVE_LOG_LEVEL",
)


@pytest.fixture
def run_cli(monkeypatch):
    """Invoke the real CLI with the server stubbed out, and isolate globals."""
    # `_run` writes the hand-over variables straight into os.environ, which
    # monkeypatch cannot undo; give the test its own copy of the environment.
    # The copy is a plain dict, so assignments no longer reach os.putenv; that
    # is fine here because uvicorn.run is stubbed and nothing is spawned.
    monkeypatch.setattr(os, "environ", os.environ.copy())
    for name in DOCLING_ENV:
        os.environ.pop(name, None)
    defaults = DoclingServeSettings()
    for name in ("enable_ui", "artifacts_path", "log_level"):
        monkeypatch.setattr(docling_serve_settings, name, getattr(defaults, name))

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


def test_run_without_verbose_logs_at_the_documented_warning_level(run_cli):
    """No `-v`, no DOCLING_SERVE_LOG_LEVEL: the configuration docs promise
    WARNING. The settings carry that level to the app module, and the root and
    uvicorn loggers already sit at it when uvicorn imports the app (the module
    used to reset them to INFO)."""
    run_cli("run", "--no-reload")

    assert docling_serve_settings.log_level is LogLevel.WARNING
    assert logging.getLogger().level == logging.WARNING
    assert logging.getLogger("uvicorn.access").level == logging.WARNING


def test_verbose_flag_raises_the_level_in_the_settings_and_the_loggers(run_cli):
    run_cli("-v", "run", "--no-reload")

    assert docling_serve_settings.log_level is LogLevel.INFO
    assert logging.getLogger().level == logging.INFO
    assert logging.getLogger("uvicorn.access").level == logging.INFO


def test_verbose_flag_reaches_the_reload_subprocess(run_cli):
    """`-v` is a global option; the resolved level must survive the spawn."""
    run_cli("-vv", "dev")

    assert DoclingServeSettings().log_level is LogLevel.DEBUG


def test_default_log_level_is_handed_to_the_subprocess_explicitly(run_cli):
    """Without `-v` the documented default is exported too, so the child cannot
    end up with a different level than the parent."""
    run_cli("dev")

    assert os.environ["DOCLING_SERVE_LOG_LEVEL"] == "WARNING"
    assert DoclingServeSettings().log_level is LogLevel.WARNING


def test_empty_env_log_level_means_the_default(run_cli):
    """Container templates often render DOCLING_SERVE_LOG_LEVEL="" for "not set";
    that must keep selecting the default instead of failing validation."""
    os.environ["DOCLING_SERVE_LOG_LEVEL"] = ""

    assert DoclingServeSettings().log_level is LogLevel.WARNING


def test_env_log_level_is_kept_unless_verbose_overrides_it(run_cli):
    os.environ["DOCLING_SERVE_LOG_LEVEL"] = "debug"
    # The singleton was built at import time; rebuild the field from the
    # environment the way a fresh process would see it.
    docling_serve_settings.log_level = DoclingServeSettings().log_level

    run_cli("run", "--no-reload")

    assert docling_serve_settings.log_level is LogLevel.DEBUG


def test_single_process_run_leaves_the_environment_alone(run_cli):
    """Without reload/workers the app runs in-process, so the settings object
    is the channel and the environment must not be rewritten."""
    captured = run_cli("-v", "run", "--no-reload", "--enable-ui")

    assert captured["reload"] is False and captured["workers"] is None
    assert docling_serve_settings.enable_ui is True
    assert docling_serve_settings.log_level is LogLevel.INFO
    assert DoclingServeSettings().enable_ui is False
    assert DoclingServeSettings().log_level is LogLevel.WARNING

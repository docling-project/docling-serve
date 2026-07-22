from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from docling.datamodel.service.tasks import TaskType
from docling_jobkit.datamodel.task import Task

from docling_serve import orchestrator_factory, rq_job_wrapper


class _CapturedConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def test_rq_config_propagates_external_plugin_policy(monkeypatch):
    monkeypatch.setattr(
        orchestrator_factory.docling_serve_settings,
        "allow_external_plugins",
        True,
    )
    with patch(
        "docling_jobkit.orchestrators.rq.orchestrator.RQOrchestratorConfig",
        _CapturedConfig,
    ):
        config = orchestrator_factory._build_rq_config()

    assert config.allow_external_plugins is True


def test_instrumented_rq_job_uses_worker_plugin_policy(monkeypatch):
    seen = {}

    def validate_task(task_data, *, allow_external_plugins):
        del task_data
        seen["allow_external_plugins"] = allow_external_plugins
        return Task.model_construct(
            task_id="task-plugin",
            task_type=TaskType.CONVERT,
            sources=[],
        )

    monkeypatch.setattr(
        rq_job_wrapper,
        "get_current_job",
        lambda: SimpleNamespace(id="job", func_name="convert", origin="convert"),
    )
    monkeypatch.setattr(rq_job_wrapper, "validate_task", validate_task)
    monkeypatch.setattr(
        rq_job_wrapper,
        "_run_docling_task",
        lambda *args, **kwargs: "result-key",
    )

    result = rq_job_wrapper.instrumented_docling_task(
        {},
        conversion_manager=object(),
        orchestrator_config=SimpleNamespace(allow_external_plugins=True),
        scratch_dir=Path("/tmp"),
    )

    assert result == "result-key"
    assert seen == {"allow_external_plugins": True}

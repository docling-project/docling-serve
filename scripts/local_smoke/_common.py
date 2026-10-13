from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

import httpx

TERMINAL_TASK_STATUSES = {"success", "failure", "partial_success"}
_T = TypeVar("_T")


@dataclass(frozen=True)
class Config:
    service_url: str
    api_key: str
    minio_access_key: str
    minio_secret_key: str
    minio_docker_endpoint: str
    minio_mount_path: Path
    source_bucket: str
    target_bucket: str
    artifacts_bucket: str
    source_prefix: str
    target_prefix: str
    pdf_a: Path
    pdf_b: Path


def load_config() -> Config:
    cwd = Path.cwd()
    return Config(
        service_url=os.environ.get("DOCLING_SERVICE_URL", "http://127.0.0.1:5001"),
        api_key=os.environ.get("DOCLING_SERVICE_API_KEY", ""),
        minio_access_key=os.environ.get("MINIO_ROOT_USER", "minioadmin"),
        minio_secret_key=os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin"),
        minio_docker_endpoint=os.environ.get(
            "MINIO_DOCKER_ENDPOINT", "http://host.docker.internal:9000"
        ),
        minio_mount_path=Path(
            os.environ.get(
                "MINIO_MOUNT_PATH",
                str(cwd / ".tmp_docling_serve_local_stack" / "minio" / "data"),
            )
        ),
        source_bucket=os.environ.get("MINIO_SOURCE_BUCKET", "source"),
        target_bucket=os.environ.get("MINIO_TARGET_BUCKET", "target"),
        artifacts_bucket=os.environ.get("MINIO_ARTIFACTS_BUCKET", "artifacts"),
        source_prefix=os.environ.get("MINIO_SOURCE_PREFIX", "inbox"),
        target_prefix=os.environ.get("MINIO_TARGET_PREFIX", "batch-out"),
        pdf_a=Path(
            os.environ.get("SMOKE_PDF_A", str(cwd / "tests" / "2206.01062v1.pdf"))
        ),
        pdf_b=Path(
            os.environ.get("SMOKE_PDF_B", str(cwd / "tests" / "2408.09869v5.pdf"))
        ),
    )


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_extraction_item(item: dict[str, Any]) -> None:
    """Assert one durable extraction item matches the reshaped result contract.

    Telemetry moved under ``inference_metadata`` and ``errors`` became structured
    ``ErrorItem``s (see docling PR #4218); per-token output is not carried on
    the durable result.
    """
    require(
        item["validation_status"] == "passed", "Extraction schema validation failed."
    )
    extracted = item.get("extracted_data") or {}
    require(bool(extracted.get("title")), "Extraction result has no title.")
    require("generated_tokens" not in item, "generated_tokens must not be persisted.")
    for flat in ("num_tokens", "usage", "stop_reason", "generation_time"):
        require(
            flat not in item,
            f"telemetry {flat!r} must be nested under 'inference_metadata'.",
        )
    require(
        isinstance(item.get("inference_metadata"), dict), "Missing inference metadata."
    )
    errors = item.get("errors", [])
    require(isinstance(errors, list), "errors must be a structured list.")
    require(
        all(isinstance(error, dict) and "error_message" in error for error in errors),
        "errors must be structured ErrorItems.",
    )


def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, sort_keys=True))


def auth_headers(cfg: Config) -> dict[str, str]:
    if not cfg.api_key:
        return {}
    return {"X-Api-Key": cfg.api_key}


def http_client(cfg: Config) -> httpx.Client:
    return httpx.Client(
        base_url=cfg.service_url.rstrip("/"),
        headers=auth_headers(cfg),
        timeout=httpx.Timeout(connect=10.0, read=120.0, write=120.0, pool=120.0),
    )


def wait_for_task(
    client: httpx.Client, task_id: str, *, timeout: float = 300.0
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        response = client.get(f"/v1/status/poll/{task_id}", params={"wait": 1.0})
        response.raise_for_status()
        payload = response.json()
        status = payload["task_status"]
        print(f"task={task_id} status={status}")
        if status in TERMINAL_TASK_STATUSES:
            return payload
        require(
            time.monotonic() < deadline,
            f"Task {task_id} did not reach terminal status within {timeout} seconds.",
        )
        time.sleep(1.0)


def fetch_result_json(client: httpx.Client, task_id: str) -> dict[str, Any]:
    response = client.get(f"/v1/result/{task_id}")
    response.raise_for_status()
    return response.json()


def model_validate_response(model_type: type[_T], payload: dict[str, Any]) -> _T:
    validator = getattr(model_type, "model_validate")
    return validator(payload)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=True, text=True, capture_output=True)


def _mc_shell(script: str, *, mount_dir: Path | None = None) -> str:
    cmd = ["docker", "run", "--rm"]
    if mount_dir is not None:
        cmd.extend(["-v", f"{mount_dir}:/mnt:ro"])
    cmd.extend(
        [
            "--entrypoint",
            "/bin/sh",
            "minio/mc:latest",
            "-lc",
            script,
        ]
    )
    completed = _run(cmd)
    return completed.stdout


def _mc_alias(cfg: Config) -> str:
    endpoint = shlex.quote(cfg.minio_docker_endpoint)
    user = shlex.quote(cfg.minio_access_key)
    password = shlex.quote(cfg.minio_secret_key)
    return f"mc alias set local {endpoint} {user} {password} >/dev/null"


def ensure_bucket(cfg: Config, bucket: str) -> None:
    bucket_q = shlex.quote(f"local/{bucket}")
    _mc_shell(f"{_mc_alias(cfg)} && mc mb -p {bucket_q} >/dev/null")


def upload_file(cfg: Config, source: Path, bucket: str, key: str) -> None:
    source_q = shlex.quote(f"/mnt/{source.name}")
    target_q = shlex.quote(f"local/{bucket}/{key}")
    script = f"{_mc_alias(cfg)} && mc cp {source_q} {target_q} >/dev/null"
    _mc_shell(script, mount_dir=source.parent)


def mc_find(
    cfg: Config, bucket: str, prefix: str = "", name: str | None = None
) -> list[str]:
    target = f"local/{bucket}"
    if prefix:
        target = f"{target}/{prefix.strip('/')}"
    target_q = shlex.quote(target)
    cmd = f"{_mc_alias(cfg)} && mc find {target_q}"
    if name is not None:
        cmd += f" --name {shlex.quote(name)}"
    output = _mc_shell(cmd)
    return [line.strip() for line in output.splitlines() if line.strip()]


def snapshot_tree(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {
        str(path.relative_to(root))
        for path in root.rglob("*")
        if path.is_file() or path.is_dir()
    }


def new_tree_entries(root: Path, before: set[str]) -> list[str]:
    after = snapshot_tree(root)
    return sorted(after - before)


def unique_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

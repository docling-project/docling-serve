"""Run the Ruff linter and formatter on the Python files changed by a PR.

This runs from a `pull_request_target` workflow, so it must never execute code
from the PR. The worktree and the tooling stay on the trusted base commit; the
changed files are read from the PR merge tree with `git show` and written over
the worktree, where Ruff only parses them.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

RUFF_DIRECTORIES = ("docling_serve", "tests", "examples", "scripts", ".github/scripts")
RUFF_SUFFIXES = {".py", ".ipynb"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Ruff lint and format checks on the files changed by a PR."
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", required=True)
    return parser.parse_args()


def run_git(repo_root: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=repo_root, capture_output=True, check=True
    ).stdout


def get_changed_paths(repo_root: Path, base_ref: str, head_ref: str) -> list[str]:
    output = run_git(
        repo_root, "diff", "--name-only", "--diff-filter=ACMR", base_ref, head_ref
    )
    return [line for line in output.decode().splitlines() if line]


def is_ruff_target(path: str) -> bool:
    if Path(path).suffix not in RUFF_SUFFIXES:
        return False
    return any(path.startswith(f"{directory}/") for directory in RUFF_DIRECTORIES)


def overlay_head_files(repo_root: Path, head_ref: str, paths: list[str]) -> None:
    for relative_path in paths:
        output_path = repo_root / relative_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(
            run_git(repo_root, "show", f"{head_ref}:{relative_path}")
        )


def resolve_ruff(repo_root: Path) -> str:
    venv_ruff = repo_root / ".venv/bin/ruff"
    if venv_ruff.exists():
        return str(venv_ruff)
    system_ruff = shutil.which("ruff")
    if system_ruff is None:
        raise FileNotFoundError("Could not find `ruff` in .venv or on PATH.")
    return system_ruff


def append_summary(text: str) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write(text if text.endswith("\n") else f"{text}\n")


def main() -> int:
    args = parse_args()
    repo_root = args.repo_root.resolve()

    changed_paths = get_changed_paths(repo_root, args.base_ref, args.head_ref)
    targets = [path for path in changed_paths if is_ruff_target(path)]

    append_summary("## PR Fast Checks\n")
    if not targets:
        append_summary("No Python or notebook files to check.\n")
        print("No Python or notebook files to check.")
        return 0
    append_summary("### Checked files\n")
    append_summary("\n".join(f"- `{path}`" for path in targets) + "\n")

    overlay_head_files(repo_root, args.head_ref, targets)

    ruff = resolve_ruff(repo_root)
    config = str(repo_root / "pyproject.toml")
    checks = {
        "ruff-format": [ruff, "format", "--check", "--diff", "--config", config],
        "ruff-lint": [ruff, "check", "--config", config],
    }

    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")

    failures: list[str] = []
    append_summary("\n### Results\n| Check | Result |\n| --- | --- |\n")
    for name, command in checks.items():
        print(f"::group::{name}", flush=True)
        completed = subprocess.run(
            [*command, *targets], cwd=repo_root, env=env, check=False
        )
        print("::endgroup::", flush=True)
        passed = completed.returncode == 0
        append_summary(f"| {name} | {'passed' if passed else 'failed'} |\n")
        if not passed:
            failures.append(name)
            print(f"::error title={name} failed::Run `make fix` locally and commit.")

    if failures:
        print(f"Checks failed: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

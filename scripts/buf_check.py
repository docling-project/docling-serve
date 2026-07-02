#!/usr/bin/env python3
"""Run buf lint and buf format checks against the serve protos.

The serve protos import ``ai/docling/core/v1/docling_document.proto``, which
lives in the docling-core repository, not here. A bare ``buf lint`` in this
repo therefore fails with "imported file does not exist". This script resolves
the core proto the same way ``scripts/gen_grpc.py`` does (installed
docling-core first, sibling ``../docling-core`` checkout as fallback),
assembles a combined proto tree in a temp directory, and runs:

- ``buf lint`` on the combined tree (so imports resolve), and
- ``buf format --diff --exit-code`` on this repo's own protos.

Usage:
    uv run python scripts/buf_check.py          # check only
    uv run python scripts/buf_check.py --write  # also apply buf format -w
"""

import pathlib
import shutil
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROTO_DIR = ROOT / "proto"

BUF_YAML = """version: v2

modules:
  - path: proto

lint:
  use:
    - STANDARD
"""


def get_core_proto_dir() -> pathlib.Path:
    # Prefer proto dir from installed docling-core (e.g. when docling-core ships proto).
    try:
        import docling_core

        core_proto = pathlib.Path(docling_core.__file__).resolve().parent / "proto"
        if (core_proto / "ai" / "docling" / "core" / "v1" / "docling_document.proto").exists():
            return core_proto
    except ImportError:
        pass
    # Fallback: sibling repo at ../docling-core (for development before docling-core releases proto).
    sibling = ROOT.parent / "docling-core" / "proto"
    if (sibling / "ai" / "docling" / "core" / "v1" / "docling_document.proto").exists():
        return sibling
    raise SystemExit(
        "docling-core with proto is required to lint serve protos. "
        "Install docling-core from a repo that includes proto/ (e.g. pip install -e /path/to/docling-core)."
    )


def run(cmd: list[str], cwd: pathlib.Path) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(cmd, cwd=cwd)


def main() -> None:
    write = "--write" in sys.argv[1:]
    buf = shutil.which("buf")
    if buf is None:
        raise SystemExit("buf is not installed or not on PATH. See https://buf.build/docs/installation")

    core_proto = get_core_proto_dir()
    failures = 0

    # Format: operate directly on this repo's protos so --write edits the real files.
    fmt_cmd = [buf, "format"]
    fmt_cmd += ["-w"] if write else ["--diff", "--exit-code"]
    fmt_cmd += [str(PROTO_DIR)]
    if run(fmt_cmd, cwd=ROOT) != 0:
        failures += 1

    # Lint: combine core + serve protos so cross-repo imports resolve.
    with tempfile.TemporaryDirectory(prefix="buf-check-") as tmp:
        workspace = pathlib.Path(tmp)
        combined = workspace / "proto"
        shutil.copytree(core_proto, combined)
        shutil.copytree(
            PROTO_DIR / "ai" / "docling" / "serve",
            combined / "ai" / "docling" / "serve",
        )
        (workspace / "buf.yaml").write_text(BUF_YAML, encoding="utf-8")
        if run([buf, "lint"], cwd=workspace) != 0:
            failures += 1

    if failures:
        raise SystemExit(f"buf checks failed ({failures} step(s) reported errors).")
    print("buf lint and buf format checks passed.")


if __name__ == "__main__":
    main()

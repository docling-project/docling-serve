#!/usr/bin/env python3
"""Generate gRPC stubs for serve protos only. Document proto lives in docling-core."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROTO_DIR = ROOT / "proto"
OUT_DIR = ROOT / "docling_serve" / "grpc" / "gen"


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
        "docling-core with proto is required to generate serve stubs. "
        "Install docling-core from a repo that includes proto/ (e.g. pip install -e /path/to/docling-core)."
    )


def ensure_init_files(path: pathlib.Path) -> None:
    for sub in [path] + [p for p in path.rglob("*") if p.is_dir()]:
        init = sub / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")


def main() -> None:
    serve_proto_dir = PROTO_DIR / "ai" / "docling" / "serve" / "v1"
    protos = [str(p) for p in serve_proto_dir.glob("*.proto")] if serve_proto_dir.exists() else []
    if not protos:
        print("No serve proto files found under proto/ai/docling/serve/v1/.")
        sys.exit(1)

    core_proto = get_core_proto_dir()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{PROTO_DIR}",
        f"-I{core_proto}",
        f"--python_out={OUT_DIR}",
        f"--grpc_python_out={OUT_DIR}",
        *protos,
    ]
    subprocess.check_call(cmd)
    ensure_init_files(OUT_DIR)
    # Shim so generated serve code can resolve "from ai.docling.core.v1 import docling_document_pb2"
    core_shim = OUT_DIR / "ai" / "docling" / "core"
    core_shim.mkdir(parents=True, exist_ok=True)
    (core_shim / "__init__.py").write_text(
        '# Shim so generated serve stubs resolve "from ai.docling.core.v1 import docling_document_pb2".\n'
        "from docling_core.proto.gen.ai.docling.core import v1  # noqa: F401\n\n"
        '__all__ = ["v1"]\n',
        encoding="utf-8",
    )
    (core_shim / "v1").mkdir(parents=True, exist_ok=True)
    (core_shim / "v1" / "__init__.py").write_text(
        'from docling_core.proto.gen.ai.docling.core.v1 import docling_document_pb2  # noqa: F401\n\n'
        '__all__ = ["docling_document_pb2"]\n',
        encoding="utf-8",
    )
    print("Generated gRPC stubs in", OUT_DIR)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
PROTO_DIR = ROOT / "proto"
OUT_DIR = ROOT / "docling_serve" / "grpc" / "gen"


def ensure_init_files(path: pathlib.Path) -> None:
    for sub in [path] + [p for p in path.rglob("*") if p.is_dir()]:
        init = sub / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")


def main() -> None:
    protos = [str(p) for p in PROTO_DIR.rglob("*.proto")]
    if not protos:
        print("No proto files found.")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "grpc_tools.protoc",
        f"-I{PROTO_DIR}",
        f"--python_out={OUT_DIR}",
        f"--grpc_python_out={OUT_DIR}",
        *protos,
    ]
    subprocess.check_call(cmd)
    ensure_init_files(OUT_DIR)
    print("Generated gRPC stubs in", OUT_DIR)


if __name__ == "__main__":
    main()

"""gRPC server support for docling-serve."""

from __future__ import annotations

import sys
from pathlib import Path

_GEN_PATH = Path(__file__).resolve().parent / "gen"
if _GEN_PATH.exists():
    sys.path.insert(0, str(_GEN_PATH))

#!/bin/bash
set -Eeuo pipefail

# Network settings
export PORT="${PORT:-5001}"
export HOST="${HOST:-"0.0.0.0"}"

# Performance settings
UVICORN_WORKERS="${UVICORN_WORKERS:-1}"

# Development settings
export WITH_UI="${WITH_UI:-"true"}"
export RELOAD=${RELOAD:-"false"}

# --------------------------------------
# Process env settings

EXTRA_ARGS=""
if [ "$RELOAD" == "true" ]; then
  EXTRA_ARGS="$EXTRA_ARGS --reload"
fi

# Launch
exec poetry run uvicorn \
    docling_serve.app:app \
    --host=${HOST} \
    --port=${PORT} \
    --timeout-keep-alive=600 \
    ${EXTRA_ARGS} \
    --workers=${UVICORN_WORKERS}

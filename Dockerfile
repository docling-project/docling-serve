FROM nexus.int.onebrief.tools/cgr.dev/onebrief.com/python-fips:3.13-dev AS build
ENV UV_COMPILE_BYTECODE=0 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY ./pyproject.toml ./pyproject.toml

RUN /usr/bin/python -m pip install --no-cache-dir uv

# Create a virtual environment
RUN /usr/bin/python -m uv venv /app/.venv

# Install dependencies into the virtual environment
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    /usr/bin/python -m uv pip install --python /app/.venv/bin/python ".[rapidocr]" --group cu126

# Download models in build stage (has shell available)
ARG MODELS_LIST="layout tableformer picture_classifier rapidocr"
ENV DOCLING_SERVE_ARTIFACTS_PATH=/app/.cache/docling/models
RUN HF_HUB_DOWNLOAD_TIMEOUT="90" \
    HF_HUB_ETAG_TIMEOUT="90" \
    /app/.venv/bin/docling-tools models download -o "${DOCLING_SERVE_ARTIFACTS_PATH}" ${MODELS_LIST}

# Multistage release build

FROM nexus.int.onebrief.tools/cgr.dev/onebrief.com/python-fips:3.13 AS release

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}"
# Copy downloaded models from build stage
COPY --from=build --chown=65532:65532 /app/ /app/
ENV \
    DOCLING_SERVE_ARTIFACTS_PATH=/app/.cache/docling/models

# Copy pre-downloaded models from host (run customization/download_models.sh first)
# COPY --chown=65532:65532 .cache/docling/models ${DOCLING_SERVE_ARTIFACTS_PATH}

COPY --chown=65532:65532 ./docling_serve ./docling_serve
COPY --chown=65532:65532 ./serve /usr/bin/serve
COPY --chmod=755 ./serve /usr/bin/serve

EXPOSE 8080

ENTRYPOINT ["/usr/bin/serve"]
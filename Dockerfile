FROM nexus.int.onebrief.tools/cgr.dev/onebrief.com/python-fips:3.13-dev AS build
ENV UV_COMPILE_BYTECODE=0 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0

WORKDIR /app

COPY ./pyproject.toml ./uv.lock ./

RUN /usr/bin/python -m pip install --no-cache-dir uv

# Create a virtual environment
RUN /usr/bin/python -m uv venv /app/.venv

# Install dependencies using lockfile for pinned versions
RUN --mount=type=cache,target=/root/.cache/uv \
    /usr/bin/python -m uv sync --frozen --python /app/.venv/bin/python --extra tesserocr --group cu126 --no-group dev --no-group pypi \
    && /usr/bin/python -m uv pip uninstall --python /app/.venv/bin/python opencv-python opencv-python-headless \
    && /usr/bin/python -m uv pip install --python /app/.venv/bin/python opencv-python-headless \
    && /usr/bin/python -m uv pip install --python /app/.venv/bin/python "cryptography>=46.0.5" "pillow>=12.1.1"

# Download models in build stage (has shell available)
ARG MODELS_LIST="layout tableformer"
ENV DOCLING_SERVE_ARTIFACTS_PATH=/app/.cache/docling/models
RUN HF_HUB_DOWNLOAD_TIMEOUT="90" \
    HF_HUB_ETAG_TIMEOUT="90" \
    /app/.venv/bin/docling-tools models download -o "${DOCLING_SERVE_ARTIFACTS_PATH}" ${MODELS_LIST}

# Download tessdata for tesserocr (default langs + osd for orientation detection)
RUN mkdir -p /app/tessdata \
    && wget -q -O /app/tessdata/eng.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata \
    && wget -q -O /app/tessdata/fra.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/fra.traineddata \
    && wget -q -O /app/tessdata/deu.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/deu.traineddata \
    && wget -q -O /app/tessdata/spa.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/spa.traineddata \
    && wget -q -O /app/tessdata/osd.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/osd.traineddata

# Multistage release build

FROM nexus.int.onebrief.tools/cgr.dev/onebrief.com/python-fips:3.13 AS release

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:${PATH}" \
    TESSDATA_PREFIX=/app/tessdata
# Copy downloaded models from build stage
COPY --from=build --chown=65532:65532 /app/ /app/
ENV \
    DOCLING_SERVE_ARTIFACTS_PATH=/app/.cache/docling/models

# Copy pre-downloaded models from host (run customization/download_models.sh first)
# COPY --chown=65532:65532 .cache/docling/models ${DOCLING_SERVE_ARTIFACTS_PATH}

COPY --chown=65532:65532 ./docling_serve ./docling_serve
COPY --chown=65532:65532 --chmod=755 ./serve /usr/bin/serve

EXPOSE 8080

ENTRYPOINT ["/usr/bin/serve"]

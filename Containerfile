FROM python:3.11-slim-bookworm

ARG CPU_ONLY=false
WORKDIR /docling-serve

RUN apt-get update \
    && apt-get install -y libgl1 libglib2.0-0 curl wget git \
    && apt-get clean

RUN pip install --no-cache-dir poetry

COPY pyproject.toml poetry.lock README.md /docling-serve/

RUN if [ "$CPU_ONLY" = "true" ]; then \
    poetry install --no-root --with cpu; \
    else \
        poetry install --no-root; \
    fi

ENV HF_HOME=/tmp/
ENV TORCH_HOME=/tmp/

RUN poetry run python -c 'from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline; artifacts_path = StandardPdfPipeline.download_models_hf(force=True);'

# On container environments, always set a thread budget to avoid undesired thread congestion.
ENV OMP_NUM_THREADS=4

COPY ./docling_serve /docling-serve/docling_serve

EXPOSE 5000

CMD ["poetry", "run", "uvicorn", "--port", "5000", "--host", "0.0.0.0", "docling_serve.app:app"]

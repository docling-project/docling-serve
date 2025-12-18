FROM harbor.onebrief.tools/cgr.dev/onebrief.com/conda:25.1.1-dev AS build

ARG PYTHON_VERSION=3.12
ARG CONDA_ENV_NAME=vllm-env

SHELL ["/bin/bash", "-c"]

WORKDIR /app

COPY ./pyproject.toml ./pyproject.toml

RUN apk add --no-cache gcc glibc-dev aws-cli && \
    /usr/bin/conda-wrapper config --add channels defaults && \
    /usr/bin/conda-wrapper create -y -n $CONDA_ENV_NAME python=$PYTHON_VERSION && \
    /root/conda/envs/vllm-env/bin/pip3 install . && \
    /root/conda/envs/vllm-env/bin/pip3 uninstall -y 'torch>=2.6.0' 'torchvision>=0.21.0' && \
    /root/conda/envs/vllm-env/bin/pip3 install --index-url https://download.pytorch.org/whl/cu126 torch torchvision

RUN /usr/bin/conda-wrapper clean -afy && \
    find /root/conda/envs/$CONDA_ENV_NAME/ -follow -type f -name '*.a' -delete && \
    find /root/conda/envs/$CONDA_ENV_NAME/ -follow -type f -name '*.a' -delete && \
    find /root/conda/envs/$CONDA_ENV_NAME/ -follow -type f -name '*.pyc' -delete && \
    find /root/conda/envs/$CONDA_ENV_NAME/ -follow -type d -name '__pycache__' -delete && \
    sed -i 's#/root/conda#/home/vllm/.conda#g' /root/conda/envs/$CONDA_ENV_NAME/bin/docling-tools

# Multistage release build

FROM harbor.onebrief.tools/cgr.dev/onebrief.com/conda:25.1.1 AS release

SHELL ["/bin/bash", "-c"]

ENV PYTHONUNBUFFERED=TRUE
ENV PYTHONDONTWRITEBYTECODE=TRUE

RUN addgroup -S vllm
RUN adduser -S vllm -G vllm

USER vllm

ARG CONDA_ENV_NAME=vllm-env
ARG BUILD_END_PATH="/root/conda/envs/$CONDA_ENV_NAME"
ARG RELEASE_ENV_PATH="/home/vllm/.conda/envs/$CONDA_ENV_NAME"

COPY --from=build $BUILD_END_PATH $RELEASE_ENV_PATH
COPY --from=build --chown=100:100 /app /app

# This is a fast and dirty fix to resolve VLLM Triton JIT compilation issues
# the exact dependencies should be determined and copied
# or seek VLLM fix for hardware specific precompiled binaries

COPY --from=build /usr/libexec/gcc /usr/libexec/gcc
COPY --from=build /usr/share /usr/share
COPY --from=build /usr/lib /usr/lib
COPY --from=build /usr/bin /usr/bin
COPY --from=build /usr/include /usr/include

ENV \
    DOCLING_SERVE_ARTIFACTS_PATH=/app/.cache/docling/models

ARG MODELS_LIST="layout tableformer picture_classifier rapidocr easyocr"

WORKDIR /app

RUN echo "Downloading models..." && \
    HF_HUB_DOWNLOAD_TIMEOUT="90" \
    HF_HUB_ETAG_TIMEOUT="90" \
    $RELEASE_ENV_PATH/bin/docling-tools models download -o "${DOCLING_SERVE_ARTIFACTS_PATH}" ${MODELS_LIST} && \
    chown -R 100:100 ${DOCLING_SERVE_ARTIFACTS_PATH} && \
    chmod -R g=u ${DOCLING_SERVE_ARTIFACTS_PATH}

COPY --chown=100:100 ./docling_serve ./docling_serve
COPY --chown=100:100 ./serve /usr/bin/serve
RUN chmod +x /usr/bin/serve

EXPOSE 8080

ENTRYPOINT ["/usr/bin/serve"]
ARG BASE_IMAGE=quay.io/sclorg/python-312-c9s:c9s

ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.19

ARG UV_SYNC_EXTRA_ARGS=""

ARG MIMALLOC_VERSION=v3.2.8


###################################################################################################
# Build mimalloc                                                                                  #
###################################################################################################

FROM ${BASE_IMAGE} AS mimalloc

ARG MIMALLOC_VERSION

USER 0

WORKDIR /opt/app-root/src

RUN dnf install -y --best --nodocs --setopt=install_weak_deps=False gcc gcc-c++ make cmake && \
    curl -L https://github.com/microsoft/mimalloc/archive/refs/tags/${MIMALLOC_VERSION}.tar.gz | \
    tar -xzf - --strip-components=1 && \
    mkdir -p out/release

WORKDIR /opt/app-root/src/out/release
RUN cmake ../.. && make


FROM ${BASE_IMAGE} AS docling-base

###################################################################################################
# OS Layer                                                                                        #
###################################################################################################

USER 0

RUN --mount=type=bind,source=os-packages.txt,target=/tmp/os-packages.txt \
    dnf -y install --best --nodocs --setopt=install_weak_deps=False dnf-plugins-core && \
    dnf config-manager --best --nodocs --setopt=install_weak_deps=False --save && \
    dnf config-manager --enable crb && \
    dnf -y update && \
    dnf install -y $(cat /tmp/os-packages.txt) && \
    dnf -y clean all && \
    rm -rf /var/cache/dnf

COPY --from=mimalloc /opt/app-root/src/out/release/libmimalloc.so /usr/local/lib/libmimalloc.so
RUN /usr/bin/fix-permissions /opt/app-root/src/.cache

ENV TESSDATA_PREFIX=/usr/share/tesseract/tessdata/

FROM ${UV_IMAGE} AS uv_stage

###################################################################################################
# Docling layer                                                                                   #
###################################################################################################

FROM docling-base

USER 1001

WORKDIR /opt/app-root/src

ENV \
    OMP_NUM_THREADS=4 \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/app-root \
    DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/.cache/docling/models

ARG UV_SYNC_EXTRA_ARGS

RUN --mount=from=uv_stage,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/opt/app-root/src/.cache/uv,uid=1001 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    umask 002 && \
    UV_SYNC_ARGS="--frozen --no-install-project --no-dev --all-extras" && \
    uv sync ${UV_SYNC_ARGS} ${UV_SYNC_EXTRA_ARGS} --no-extra flash-attn && \
    FLASH_ATTENTION_SKIP_CUDA_BUILD=TRUE uv sync ${UV_SYNC_ARGS} ${UV_SYNC_EXTRA_ARGS} --no-build-isolation-package=flash-attn

ARG MODELS_LIST="layout tableformer picture_classifier rapidocr easyocr"

RUN echo "Downloading models..." && \
    HF_HUB_DOWNLOAD_TIMEOUT="90" \
    HF_HUB_ETAG_TIMEOUT="90" \
    docling-tools models download -o "${DOCLING_SERVE_ARTIFACTS_PATH}" ${MODELS_LIST} && \
    chown -R 1001:0 ${DOCLING_SERVE_ARTIFACTS_PATH} && \
    chmod -R g=u ${DOCLING_SERVE_ARTIFACTS_PATH}

COPY --chown=1001:0 ./docling_serve ./docling_serve

RUN --mount=from=uv_stage,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/opt/app-root/src/.cache/uv,uid=1001 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    umask 002 && uv sync --frozen --no-dev --all-extras ${UV_SYNC_EXTRA_ARGS}

ENV LD_PRELOAD=/usr/local/lib/libmimalloc.so
EXPOSE 5001

CMD ["docling-serve", "run"]

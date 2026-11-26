ARG BASE_IMAGE=quay.io/sclorg/python-312-c9s:c9s

ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.13.4

ARG UV_SYNC_EXTRA_ARGS=""

ARG MIMALLOC_VERSION=v3.2.8

ARG NODE_IMAGE=docker.io/library/node:24-alpine


###################################################################################################
# Build mimalloc                                                                                  #
###################################################################################################

FROM ${BASE_IMAGE} AS mimalloc

ARG MIMALLOC_VERSION

USER 0

RUN dnf install -y --best --nodocs --setopt=install_weak_deps=False gcc gcc-c++ make cmake git

RUN git clone --depth 1 --branch ${MIMALLOC_VERSION} https://github.com/microsoft/mimalloc.git /opt/app-root/src/mimalloc

WORKDIR /opt/app-root/src/mimalloc

RUN mkdir -p out/release

WORKDIR /opt/app-root/src/mimalloc/out/release
RUN cmake ../.. && make


###################################################################################################
# Build the web UI                                                                                #
###################################################################################################

# The bundle is plain static files, so it is built once on the build platform.
FROM --platform=$BUILDPLATFORM ${NODE_IMAGE} AS ui

WORKDIR /ui

COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY ui/ ./
RUN npm run build -- --outDir /ui/dist


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

# `dnf update` may bump the system python3.12 patch version, leaving the base image's venv
# pyvenv.cfg stale. uv would then try to recreate /opt/app-root (which contains the WORKDIR
# and cache mounts) and fail with "Resource busy" on /opt/app-root/src.
#
# `--upgrade` refreshes `home` and `version`, but uv >=0.5 also checks `version_info` and
# `implementation`. If a previous build cached those fields at an older patch level, the
# mismatch still triggers a venv recreate. Stamp them explicitly after the upgrade.
RUN /usr/bin/python3.12 -m venv --upgrade /opt/app-root && \
    PY_VER=$(/usr/bin/python3.12 -c "import sys; print('{}.{}.{}'.format(*sys.version_info[:3]))") && \
    sed -i "s/^version = .*/version = ${PY_VER}/" /opt/app-root/pyvenv.cfg && \
    grep -q '^version_info' /opt/app-root/pyvenv.cfg \
        && sed -i "s/^version_info = .*/version_info = ${PY_VER}/" /opt/app-root/pyvenv.cfg \
        || echo "version_info = ${PY_VER}" >> /opt/app-root/pyvenv.cfg && \
    grep -q '^implementation' /opt/app-root/pyvenv.cfg \
        || echo "implementation = CPython" >> /opt/app-root/pyvenv.cfg && \
    mkdir -p /opt/app-root/src/.cache && \
    /usr/bin/fix-permissions /opt/app-root

COPY --from=mimalloc /opt/app-root/src/mimalloc/out/release/libmimalloc.so /usr/local/lib/libmimalloc.so

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
COPY --from=ui --chown=1001:0 /ui/dist ./docling_serve/ui_static

RUN --mount=from=uv_stage,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/opt/app-root/src/.cache/uv,uid=1001 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    umask 002 && uv sync --frozen --no-dev --all-extras ${UV_SYNC_EXTRA_ARGS}

ENV LD_PRELOAD=/usr/local/lib/libmimalloc.so
EXPOSE 5001

CMD ["docling-serve", "run"]

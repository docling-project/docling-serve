ARG BASE_IMAGE=registry.access.redhat.com/ubi9/python-312:9.5-1739191330

FROM ${BASE_IMAGE}

USER 0

###################################################################################################
# OS Layer                                                                                        #
###################################################################################################

RUN echo -e "[codeready-builder]\n\
name=CodeReady Builder repository for UBI9\n\
baseurl=https://mirror.stream.centos.org/9-stream/CRB/$(uname -m)/os/\n\
enabled=1\n\
gpgcheck=0\n" > /etc/yum.repos.d/ubi-codeready.repo && \
    dnf clean all && dnf makecache

ADD os-packages.txt /tmp/os-packages.txt

RUN dnf -y install --best --nodocs --setopt=install_weak_deps=False dnf-plugins-core && \
    dnf config-manager --best --nodocs --setopt=install_weak_deps=False --save && \
    dnf -y update && \
    dnf install -y $(cat /tmp/os-packages.txt) && \
    dnf -y clean all && \
    rm -rf /var/cache/dnf

ENV TESSDATA_PREFIX=/usr/share/tesseract/tessdata/

RUN chown -R 1001 /opt/app-root/src

###################################################################################################
# Docling layer                                                                                   #
###################################################################################################

USER 1001

WORKDIR /opt/app-root/src

ENV \
    # On container environments, always set a thread budget to avoid undesired thread congestion.
    OMP_NUM_THREADS=4 \
    LANG=en_US.UTF-8 \
    LC_ALL=en_US.UTF-8 \
    PYTHONIOENCODING=utf-8 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/app-root \
    DOCLING_SERVE_ARTIFACTS_PATH=/opt/app-root/src/.cache/docling/models

ARG UV_SYNC_EXTRA_ARGS=""

RUN --mount=from=ghcr.io/astral-sh/uv:0.6.1,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/opt/app-root/src/.cache/uv,uid=1001 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev --all-extras ${UV_SYNC_EXTRA_ARGS}

ARG MODELS_LIST="layout tableformer picture_classifier easyocr"

RUN echo "Downloading models..." && \
    HF_HUB_DOWNLOAD_TIMEOUT="90" \
    HF_HUB_ETAG_TIMEOUT="90" \
    docling-tools models download -o "${DOCLING_SERVE_ARTIFACTS_PATH}" ${MODELS_LIST} && \
    chown -R 1001:0 /opt/app-root/src/.cache && \
    chmod -R g=u /opt/app-root/src/.cache

COPY --chown=1001:0 ./docling_serve ./docling_serve
RUN --mount=from=ghcr.io/astral-sh/uv:0.6.1,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/opt/app-root/src/.cache/uv,uid=1001 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --all-extras ${UV_SYNC_EXTRA_ARGS}

EXPOSE 5001

CMD ["docling-serve", "run"]

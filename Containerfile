ARG BASE_IMAGE=quay.io/sclorg/python-312-c9s:c9s

FROM ${BASE_IMAGE}

USER 0

###################################################################################################
# OS Layer                                                                                        #
###################################################################################################

RUN --mount=type=bind,source=os-packages.txt,target=/tmp/os-packages.txt \
    dnf -y install --best --nodocs --setopt=install_weak_deps=False dnf-plugins-core && \
    dnf config-manager --best --nodocs --setopt=install_weak_deps=False --save && \
    dnf config-manager --enable crb && \
    dnf -y update && \
    dnf install -y --allowerasing $(cat /tmp/os-packages.txt) && \
    dnf -y clean all && \
    rm -rf /var/cache/dnf

RUN /usr/bin/fix-permissions /opt/app-root/src/.cache

ENV TESSDATA_PREFIX=/usr/share/tesseract/tessdata/

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
ARG FLASH_ATTN_WHEEL_URL="https://github.com/Zarrac/flashattention-blackwell-wheels-whl-ONLY-5090-5080-5070-5060-flash-attention-/releases/download/FlashAttention/flash_attn-2.7.4.post1-rtx5090-torch2.7.0cu128cxx11abiTRUE-cp312-linux_x86_64.whl"
ARG FLASH_ATTN_WHEEL_FILENAME="flash_attn-2.7.4.post1-rtx5090-torch2.7.0cu128cxx11abiTRUE-cp312-linux_x86_64.whl"

RUN --mount=from=ghcr.io/astral-sh/uv:0.6.1,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/opt/app-root/src/.cache/uv,uid=1001 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    umask 002 && \
    uv sync --frozen --no-install-project --no-dev --all-extras ${UV_SYNC_EXTRA_ARGS} --no-extra flash-attn && \
    # Download the custom flash-attn wheel
    curl -L -o "${FLASH_ATTN_WHEEL_FILENAME}" "${FLASH_ATTN_WHEEL_URL}" && \
    # Rename the wheel to have a valid build tag for pip/uv
    RENAMED_FLASH_ATTN_WHEEL_FILENAME="flash_attn-2.7.4.post1-0rtx5090torch270cu128cxx11abiTRUE-cp312-cp312-linux_x86_64.whl" && \
    mv "${FLASH_ATTN_WHEEL_FILENAME}" "${RENAMED_FLASH_ATTN_WHEEL_FILENAME}" && \
    uv pip install --no-deps "${RENAMED_FLASH_ATTN_WHEEL_FILENAME}" && \
    # Clean up the downloaded wheel
    rm "${RENAMED_FLASH_ATTN_WHEEL_FILENAME}"

ARG MODELS_LIST="layout tableformer picture_classifier easyocr"

RUN echo "Downloading models..." && \
    HF_HUB_DOWNLOAD_TIMEOUT="90" \
    HF_HUB_ETAG_TIMEOUT="90" \
    docling-tools models download -o "${DOCLING_SERVE_ARTIFACTS_PATH}" ${MODELS_LIST} && \
    chown -R 1001:0 ${DOCLING_SERVE_ARTIFACTS_PATH} && \
    chmod -R g=u ${DOCLING_SERVE_ARTIFACTS_PATH}

COPY --chown=1001:0 ./docling_serve ./docling_serve
RUN --mount=from=ghcr.io/astral-sh/uv:0.6.1,source=/uv,target=/bin/uv \
    --mount=type=cache,target=/opt/app-root/src/.cache/uv,uid=1001 \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    umask 002 && uv sync --frozen --no-dev --all-extras ${UV_SYNC_EXTRA_ARGS}

EXPOSE 5001

CMD ["docling-serve", "run"]

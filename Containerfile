ARG BASE_IMAGE=quay.io/sclorg/python-312-c9s:c9s

FROM ${BASE_IMAGE}

ARG CPU_ONLY=false

USER 0

###################################################################################################
# OS Layer                                                                                        #
###################################################################################################

RUN --mount=type=bind,source=os-packages.txt,target=/tmp/os-packages.txt \
    dnf -y install --best --nodocs --setopt=install_weak_deps=False dnf-plugins-core && \
    dnf config-manager --best --nodocs --setopt=install_weak_deps=False --save && \
    dnf config-manager --enable crb && \
    dnf -y update && \
    dnf install -y $(cat /tmp/os-packages.txt) && \
    dnf -y clean all && \
    rm -rf /var/cache/dnf

ENV TESSDATA_PREFIX=/usr/share/tesseract/tessdata/

###################################################################################################
# Docling layer                                                                                   #
###################################################################################################

USER 1001

WORKDIR /opt/app-root/src

# On container environments, always set a thread budget to avoid undesired thread congestion.
ENV OMP_NUM_THREADS=4

ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8
ENV PYTHONIOENCODING=utf-8

ENV WITH_UI=True

COPY --chown=1001:0 pyproject.toml poetry.lock models_download.py README.md ./

RUN pip install --no-cache-dir poetry && \
    # We already are in a virtual environment, so we don't need to create a new one, only activate it.
    poetry config virtualenvs.create false && \
    source /opt/app-root/bin/activate && \
    if [ "$CPU_ONLY" = "true" ]; then \
        poetry install --no-root --no-cache --no-interaction --all-extras --with cpu --without dev; \
    else \
        poetry install --no-root --no-cache --no-interaction --all-extras --without dev; \
    fi && \
    echo "Downloading models..." && \
    python models_download.py && \
    chown -R 1001:0 /opt/app-root/src && \
    chmod -R g=u /opt/app-root/src

COPY --chown=1001:0 --chmod=664 ./docling_serve ./docling_serve

EXPOSE 5001

CMD ["python", "docling_serve/app.py"]

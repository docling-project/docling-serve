ARG BASE_IMAGE=registry.access.redhat.com/ubi9/python-312:9.5-1739191330

FROM ${BASE_IMAGE}

ARG CPU_ONLY=false

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

CMD ["python", "-m", "docling_serve"]

.PHONY: help
help:
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

#
# If you want to see the full commands, run:
#   NOISY_BUILD=y make
#
ifeq ($(NOISY_BUILD),)
    ECHO_PREFIX=@
    CMD_PREFIX=@
    PIPE_DEV_NULL=> /dev/null 2> /dev/null
else
    ECHO_PREFIX=@\#
    CMD_PREFIX=
    PIPE_DEV_NULL=
endif

TAG=$(shell git rev-parse HEAD)
BRANCH_TAG=$(shell git rev-parse --abbrev-ref HEAD)

action-lint-file:
	$(CMD_PREFIX) touch .action-lint

md-lint-file:
	$(CMD_PREFIX) touch .markdown-lint

.PHONY: docling-serve-image
docling-serve-image: Containerfile ## Build docling-serve container image
	$(ECHO_PREFIX) printf "  %-12s Containerfile\n" "[docling-serve]"
	$(CMD_PREFIX) docker build --load -f Containerfile -t ghcr.io/docling-project/docling-serve:$(TAG) .
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve:$(TAG) ghcr.io/docling-project/docling-serve:$(BRANCH_TAG)
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve:$(TAG) quay.io/docling-project/docling-serve:$(BRANCH_TAG)

.PHONY: docling-serve-cpu-image
docling-serve-cpu-image: Containerfile ## Build docling-serve "cpu only" container image
	$(ECHO_PREFIX) printf "  %-12s Containerfile\n" "[docling-serve CPU]"
	$(CMD_PREFIX) docker build --load --build-arg "UV_SYNC_EXTRA_ARGS=--no-group pypi --group cpu --no-extra flash-attn" -f Containerfile -t ghcr.io/docling-project/docling-serve-cpu:$(TAG) .
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve-cpu:$(TAG) ghcr.io/docling-project/docling-serve-cpu:$(BRANCH_TAG)
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve-cpu:$(TAG) quay.io/docling-project/docling-serve-cpu:$(BRANCH_TAG)

.PHONY: docling-serve-cu124-image
docling-serve-cu124-image: Containerfile ## Build docling-serve container image with CUDA 12.4 support
	$(ECHO_PREFIX) printf "  %-12s Containerfile\n" "[docling-serve with Cuda 12.4]"
	$(CMD_PREFIX) docker build --load --build-arg "UV_SYNC_EXTRA_ARGS=--no-group pypi --group cu124" -f Containerfile --platform linux/amd64 -t ghcr.io/docling-project/docling-serve-cu124:$(TAG) .
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve-cu124:$(TAG) ghcr.io/docling-project/docling-serve-cu124:$(BRANCH_TAG)
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve-cu124:$(TAG) quay.io/docling-project/docling-serve-cu124:$(BRANCH_TAG)

.PHONY: docling-serve-cu126-image
docling-serve-cu126-image: Containerfile ## Build docling-serve container image with CUDA 12.6 support
	$(ECHO_PREFIX) printf "  %-12s Containerfile\n" "[docling-serve with Cuda 12.6]"
	$(CMD_PREFIX) docker build --load --build-arg "UV_SYNC_EXTRA_ARGS=--no-group pypi --group cu126" -f Containerfile --platform linux/amd64 -t ghcr.io/docling-project/docling-serve-cu126:$(TAG) .
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve-cu126:$(TAG) ghcr.io/docling-project/docling-serve-cu126:$(BRANCH_TAG)
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve-cu126:$(TAG) quay.io/docling-project/docling-serve-cu126:$(BRANCH_TAG)

.PHONY: docling-serve-cu128-image
docling-serve-cu128-image: Containerfile ## Build docling-serve container image with CUDA 12.8 support
	$(ECHO_PREFIX) printf "  %-12s Containerfile\n" "[docling-serve with Cuda 12.8]"
	$(CMD_PREFIX) docker build --load --build-arg "UV_SYNC_EXTRA_ARGS=--no-group pypi --group cu128" -f Containerfile --platform linux/amd64 -t ghcr.io/docling-project/docling-serve-cu128:$(TAG) .
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve-cu128:$(TAG) ghcr.io/docling-project/docling-serve-cu128:$(BRANCH_TAG)
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve-cu128:$(TAG) quay.io/docling-project/docling-serve-cu128:$(BRANCH_TAG)

.PHONY: docling-serve-rocm-image
docling-serve-rocm-image: Containerfile ## Build docling-serve container image with ROCm support
	$(ECHO_PREFIX) printf "  %-12s Containerfile\n" "[docling-serve with ROCm]"
	$(CMD_PREFIX) docker build --load --build-arg "UV_SYNC_EXTRA_ARGS=--no-group pypi --group rocm" -f Containerfile --platform linux/amd64 -t ghcr.io/docling-project/docling-serve-rocm:$(TAG) .
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve-rocm:$(TAG) ghcr.io/docling-project/docling-serve-rocm:$(BRANCH_TAG)
	$(CMD_PREFIX) docker tag ghcr.io/docling-project/docling-serve-rocm:$(TAG) quay.io/docling-project/docling-serve-rocm:$(BRANCH_TAG)

.PHONY: action-lint
action-lint: .action-lint ##      Lint GitHub Action workflows
.action-lint: $(shell find .github -type f) | action-lint-file
	$(ECHO_PREFIX) printf "  %-12s .github/...\n" "[ACTION LINT]"
	$(CMD_PREFIX) if ! which actionlint $(PIPE_DEV_NULL) ; then \
		echo "Please install actionlint." ; \
		echo "go install github.com/rhysd/actionlint/cmd/actionlint@latest" ; \
		exit 1 ; \
	fi
	$(CMD_PREFIX) if ! which shellcheck $(PIPE_DEV_NULL) ; then \
		echo "Please install shellcheck." ; \
		echo "https://github.com/koalaman/shellcheck#user-content-installing" ; \
		exit 1 ; \
	fi
	$(CMD_PREFIX) actionlint -color
	$(CMD_PREFIX) touch $@

.PHONY: md-lint
md-lint: .md-lint ##      Lint markdown files
.md-lint: $(wildcard */**/*.md) | md-lint-file
	$(ECHO_PREFIX) printf "  %-12s ./...\n" "[MD LINT]"
	$(CMD_PREFIX) docker run --rm -v $$(pwd):/workdir davidanson/markdownlint-cli2:v0.16.0 "**/*.md" "#.venv"
	$(CMD_PREFIX) touch $@

.PHONY: py-Lint
py-lint: ##      Lint Python files
	$(ECHO_PREFIX) printf "  %-12s ./...\n" "[PY LINT]"
	$(CMD_PREFIX) if ! which uv $(PIPE_DEV_NULL) ; then \
		echo "Please install uv." ; \
		exit 1 ; \
	fi
	$(CMD_PREFIX) uv sync --extra ui
	$(CMD_PREFIX) uv run pre-commit run --all-files

.PHONY: run-docling-cpu
run-docling-cpu: ## Run the docling-serve container with CPU support and assign a container name
	$(ECHO_PREFIX) printf "  %-12s Removing existing container if it exists...\n" "[CLEANUP]"
	$(CMD_PREFIX) docker rm -f docling-serve-cpu 2>/dev/null || true
	$(ECHO_PREFIX) printf "  %-12s Running docling-serve container with CPU support on port 5001...\n" "[RUN CPU]"
	$(CMD_PREFIX) docker run -it --name docling-serve-cpu -p 5001:5001 ghcr.io/docling-project/docling-serve-cpu:main

.PHONY: run-docling-cu124
run-docling-cu124: ## Run the docling-serve container with CUDA 12.4 support and assign a container name
	$(ECHO_PREFIX) printf "  %-12s Removing existing container if it exists...\n" "[CLEANUP]"
	$(CMD_PREFIX) docker rm -f docling-serve-cu124 2>/dev/null || true
	$(ECHO_PREFIX) printf "  %-12s Running docling-serve container with GPU support on port 5001...\n" "[RUN CUDA 12.4]"
	$(CMD_PREFIX) docker run -it --name docling-serve-cu124 -p 5001:5001 ghcr.io/docling-project/docling-serve-cu124:main

.PHONY: run-docling-cu126
run-docling-cu126: ## Run the docling-serve container with CUDA 12.6 support and assign a container name
	$(ECHO_PREFIX) printf "  %-12s Removing existing container if it exists...\n" "[CLEANUP]"
	$(CMD_PREFIX) docker rm -f docling-serve-cu126 2>/dev/null || true
	$(ECHO_PREFIX) printf "  %-12s Running docling-serve container with GPU support on port 5001...\n" "[RUN CUDA 12.6]"
	$(CMD_PREFIX) docker run -it --name docling-serve-cu126 -p 5001:5001 ghcr.io/docling-project/docling-serve-cu126:main

.PHONY: run-docling-cu128
run-docling-cu128: ## Run the docling-serve container with CUDA 12.8 support and assign a container name
	$(ECHO_PREFIX) printf "  %-12s Removing existing container if it exists...\n" "[CLEANUP]"
	$(CMD_PREFIX) docker rm -f docling-serve-cu128 2>/dev/null || true
	$(ECHO_PREFIX) printf "  %-12s Running docling-serve container with GPU support on port 5001...\n" "[RUN CUDA 12.8]"
	$(CMD_PREFIX) docker run -it --name docling-serve-cu128 -p 5001:5001 ghcr.io/docling-project/docling-serve-cu128:main

.PHONY: run-docling-rocm
run-docling-rocm: ## Run the docling-serve container with ROCm support and assign a container name
	$(ECHO_PREFIX) printf "  %-12s Removing existing container if it exists...\n" "[CLEANUP]"
	$(CMD_PREFIX) docker rm -f docling-serve-rocm 2>/dev/null || true
	$(ECHO_PREFIX) printf "  %-12s Running docling-serve container with GPU support on port 5001...\n" "[RUN ROCM]"
	$(CMD_PREFIX) docker run -it --name docling-serve-rocm -p 5001:5001 ghcr.io/docling-project/docling-serve-rocm:main

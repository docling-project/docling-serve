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

action-lint-file:
	$(CMD_PREFIX) touch .action-lint

md-lint-file:
	$(CMD_PREFIX) touch .markdown-lint

.PHONY: docling-serve-cpu-image
docling-serve-cpu-image: Containerfile ## Build docling-serve "cpu only" container image
	$(ECHO_PREFIX) printf "  %-12s Containerfile\n" "[docling-serve CPU]"
	$(CMD_PREFIX) docker build --load --build-arg "UV_SYNC_EXTRA_ARGS=--no-extra cu124" -f Containerfile -t ghcr.io/ds4sd/docling-serve-cpu:$(TAG) .
	$(CMD_PREFIX) docker tag ghcr.io/ds4sd/docling-serve-cpu:$(TAG) ghcr.io/ds4sd/docling-serve-cpu:main
	$(CMD_PREFIX) docker tag ghcr.io/ds4sd/docling-serve-cpu:$(TAG) quay.io/ds4sd/docling-serve-cpu:main

.PHONY: docling-serve-gpu-image
docling-serve-gpu-image: Containerfile ## Build docling-serve container image with GPU support
	$(ECHO_PREFIX) printf "  %-12s Containerfile\n" "[docling-serve with GPU]"
	$(CMD_PREFIX) docker build --load --build-arg "UV_SYNC_EXTRA_ARGS=--no-extra cpu" -f Containerfile --platform linux/amd64 -t ghcr.io/ds4sd/docling-serve:$(TAG) .
	$(CMD_PREFIX) docker tag ghcr.io/ds4sd/docling-serve:$(TAG) ghcr.io/ds4sd/docling-serve:main
	$(CMD_PREFIX) docker tag ghcr.io/ds4sd/docling-serve:$(TAG) quay.io/ds4sd/docling-serve:main

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
	$(CMD_PREFIX) docker run --rm -v $$(pwd):/workdir davidanson/markdownlint-cli2:v0.14.0 "**/*.md"
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
	$(CMD_PREFIX) docker run -it --name docling-serve-cpu -p 5001:5001 ghcr.io/ds4sd/docling-serve-cpu:main

.PHONY: run-docling-gpu
run-docling-gpu: ## Run the docling-serve container with GPU support and assign a container name
	$(ECHO_PREFIX) printf "  %-12s Removing existing container if it exists...\n" "[CLEANUP]"
	$(CMD_PREFIX) docker rm -f docling-serve-gpu 2>/dev/null || true
	$(ECHO_PREFIX) printf "  %-12s Running docling-serve container with GPU support on port 5001...\n" "[RUN GPU]"
	$(CMD_PREFIX) docker run -it --name docling-serve-gpu -p 5001:5001 ghcr.io/ds4sd/docling-serve:main

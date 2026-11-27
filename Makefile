UV ?= uv
PYTHON ?= 3.11
VENV ?= .venv
PANEL ?= $(VENV)/bin/panel
BENCH_METHODS = judge,jury,chateval,committee
BENCH_SEEDS = 0,1,2

.DEFAULT_GOAL := help
.PHONY: help install test lint typecheck demo showcase bench bench-dev

help: ## List available commands
	@awk 'BEGIN {FS = ":.*## "} /^[a-z-]+:.*## / {printf "  %-12s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: ## Install the package and development dependencies
	@test -x "$(VENV)/bin/python" || $(UV) venv --python "$(PYTHON)" "$(VENV)"
	$(UV) pip install --python "$(VENV)/bin/python" -e ".[dev]"

test: ## Run the keyless test suite
	$(VENV)/bin/pytest -q

lint: ## Check source, tests, scripts and examples with Ruff
	$(VENV)/bin/ruff check src tests scripts showcase examples

typecheck: ## Check Python types with mypy
	$(VENV)/bin/mypy src/condorium

demo: ## Replay the recorded evaluations offline
	CONDORIUM_OFFLINE=1 $(PANEL) demo

showcase: ## Rebuild the showcase from recorded runs
	CONDORIUM_OFFLINE=1 LIVE=0 bash showcase/make_showcase.sh

bench: ## Run the pairwise benchmark on the test split
	$(PANEL) bench pairwise --split test --seeds $(BENCH_SEEDS) --methods $(BENCH_METHODS)

bench-dev: ## Run the pairwise benchmark on the development split
	$(PANEL) bench pairwise --split dev --seeds $(BENCH_SEEDS) --methods $(BENCH_METHODS)

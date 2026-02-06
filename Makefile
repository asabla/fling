.PHONY: help test lint fmt typecheck check clean install run tui serve list build-css

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install all dependencies (including dev + extras)
	uv sync --all-extras

test: ## Run tests with pytest
	uv run pytest --tb=short -q

test-v: ## Run tests with verbose output
	uv run pytest --tb=short -v

test-cov: ## Run tests with coverage report
	uv run pytest --cov=fling --cov-report=term-missing --tb=short -q

lint: ## Run ruff linter
	uv run ruff check src tests

lint-fix: ## Run ruff linter with auto-fix
	uv run ruff check --fix src tests

fmt: ## Format code with ruff
	uv run ruff format src tests

fmt-check: ## Check code formatting without modifying files
	uv run ruff format --check src tests

typecheck: ## Run mypy type checker
	uv run mypy src/fling

check: lint fmt-check typecheck test ## Run all checks (lint, format check, typecheck, test)

# ---------------------------------------------------------------------------
# Frontend build targets
# ---------------------------------------------------------------------------

TAILWIND_VERSION := 3.4.17
TAILWIND_BIN := .bin/tailwindcss
TAILWIND_URL := https://github.com/tailwindlabs/tailwindcss/releases/download/v$(TAILWIND_VERSION)/tailwindcss-linux-x64

$(TAILWIND_BIN):
	@mkdir -p .bin
	@echo "Downloading Tailwind CSS standalone CLI v$(TAILWIND_VERSION)..."
	@curl -sL $(TAILWIND_URL) -o $(TAILWIND_BIN)
	@chmod +x $(TAILWIND_BIN)

build-css: $(TAILWIND_BIN) ## Compile Tailwind CSS from templates
	$(TAILWIND_BIN) -i src/fling/web/static/css/input.css -o src/fling/web/static/css/app.css --minify

# ---------------------------------------------------------------------------
# Application targets
# ---------------------------------------------------------------------------
# Usage:
#   make run FILE=api.http
#   make run FILE=api.http ARGS="--name login --env production"
#   make tui FILE=api.http
#   make serve FILE=api.http ARGS="--port 9000"

FILE ?=
ARGS ?=

run: ## Run requests from a .http file (FILE=<path> ARGS="...")
	@test -n "$(FILE)" || (echo "Usage: make run FILE=<path.http> [ARGS=\"...\"]" && exit 1)
	uv run fling run $(FILE) $(ARGS)

tui: ## Launch the TUI (FILE=<path>)
	@test -n "$(FILE)" || (echo "Usage: make tui FILE=<path.http> [ARGS=\"...\"]" && exit 1)
	uv run fling tui $(FILE) $(ARGS)

serve: ## Launch the web interface (FILE=<path> ARGS="...")
	@test -n "$(FILE)" || (echo "Usage: make serve FILE=<path.http> [ARGS=\"...\"]" && exit 1)
	uv run fling serve $(FILE) $(ARGS)

list: ## List requests in a .http file (FILE=<path>)
	@test -n "$(FILE)" || (echo "Usage: make list FILE=<path.http>" && exit 1)
	uv run fling list $(FILE)

clean: ## Remove build artifacts and caches
	rm -rf build/ dist/ .eggs/ *.egg-info
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true

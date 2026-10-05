.PHONY: help install test test-integration lint format format-check dev seed reset-db up down eval demo

PYTHON ?= python
PIP ?= $(PYTHON) -m pip

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dependencies (editable) and frontend deps when present
	$(PIP) install -e .
	@if [ -f apps/web/package.json ]; then npm --prefix apps/web install; fi

test: ## Run backend test suite
	$(PYTHON) -m pytest -q

test-integration: ## Run the end-to-end synthetic demo flow
	$(PYTHON) -m pytest tests/integration -q

lint: ## Lint backend and frontend
	$(PYTHON) -m ruff check .
	@if [ -f apps/web/package.json ]; then npm --prefix apps/web run lint; fi

format: ## Auto-format backend and frontend
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .
	@if [ -f apps/web/package.json ]; then npm --prefix apps/web run format; fi

format-check: ## Verify formatting without writing
	$(PYTHON) -m ruff format --check .
	@if [ -f apps/web/package.json ]; then npm --prefix apps/web run format:check; fi

dev: ## Run the API with autoreload
	$(PYTHON) -m uvicorn apps.api.app.main:app --reload --port 8000

seed: ## Load synthetic demo fixtures
	$(PYTHON) -m packages.fixtures.seed

reset-db: ## Downgrade to base, upgrade to head, then reseed
	$(PYTHON) -m alembic downgrade base
	$(PYTHON) -m alembic upgrade head
	$(PYTHON) -m packages.fixtures.seed

up: ## Start PostgreSQL and Redis
	docker compose up -d postgres redis

down: ## Stop the local stack
	docker compose down

eval: ## Run the evaluation harness (fixed seed)
	$(PYTHON) -m eval.run_eval --count 100 --seed 20260928 --output artifacts/eval/report.json

demo: ## Publish the fixture events for the main demo patient
	$(PYTHON) scripts/run_demo.py --patient P-1001

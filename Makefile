SHELL := /bin/bash
.DEFAULT_GOAL := help

COMPOSE := docker compose
EXEC    := $(COMPOSE) exec backend
DB_USER := biletflow
DB_NAME := biletflow
API_URL := http://localhost:8000

.PHONY: help up dev down restart rebuild nuke reset-db ps logs logs-db shell psql tables docs \
        migration migrate downgrade current heads history \
        fmt lint test check ci deps add sync branch clean

# Ask for confirmation before destructive targets
define confirm
@read -p "$(1) [y/N] " ans && [ "$$ans" = "y" ] || (echo "Aborted." && exit 1)
endef

##@ Help

help: ## Show this help
	@awk 'BEGIN {FS = ":.*## "} \
		/^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0, 5)} \
		/^[a-zA-Z_-]+:.*## / {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo

##@ Docker

up: ## Start db + backend in the background (waits until healthy)
	$(COMPOSE) up -d --wait
	@echo ">> API docs: $(API_URL)/docs"

dev: ## Start everything with live logs (rebuilds the image)
	$(COMPOSE) up --build

down: ## Stop containers (keeps database data)
	$(COMPOSE) down

restart: ## Restart only the backend container
	$(COMPOSE) restart backend

rebuild: ## Rebuild image + refresh the container .venv (use after changing dependencies)
	$(COMPOSE) up -d --build --renew-anon-volumes --wait

nuke: ## Stop containers and DELETE all volumes (database data included)
	$(call confirm,This deletes the database. Continue?)
	$(COMPOSE) down -v

reset-db: ## Wipe the database, restart, and re-apply all migrations
	$(call confirm,This deletes the database. Continue?)
	$(COMPOSE) down -v
	$(MAKE) up
	$(MAKE) migrate

ps: ## Show container status
	$(COMPOSE) ps

logs: ## Follow backend logs
	$(COMPOSE) logs -f --tail=100 backend

logs-db: ## Follow database logs
	$(COMPOSE) logs -f --tail=100 db

shell: ## Open a shell inside the backend container
	$(EXEC) bash

psql: ## Open psql inside the database container
	$(COMPOSE) exec db psql -U $(DB_USER) -d $(DB_NAME)

tables: ## List database tables
	$(COMPOSE) exec db psql -U $(DB_USER) -d $(DB_NAME) -c '\dt'

docs: ## Open Swagger UI in the browser (macOS)
	open $(API_URL)/docs

##@ Database migrations (Alembic)

migration: ## Autogenerate a migration: make migration m="add events"
	@test -n "$(m)" || (echo 'Usage: make migration m="message"' && exit 1)
	$(EXEC) alembic revision --autogenerate -m "$(m)"
	@echo ">> Review the new file in alembic/versions/ BEFORE running: make migrate"

migrate: ## Apply all pending migrations
	$(EXEC) alembic upgrade head

downgrade: ## Roll back the last migration
	$(EXEC) alembic downgrade -1

current: ## Show the revision the database is on
	$(EXEC) alembic current

heads: ## Show migration heads (should be exactly one)
	$(EXEC) alembic heads

history: ## Show migration history
	$(EXEC) alembic history --indicate-current

##@ Code quality

fmt: ## Auto-format and auto-fix lint issues (ruff)
	uv run ruff format .
	uv run ruff check . --fix

lint: ## Check formatting and lint without changing files (same as CI)
	uv run ruff format --check .
	uv run ruff check .

test: ## Run pytest
	uv run pytest

check: fmt test ## Format, fix, then test (run before every commit)

ci: lint test ## Exactly what GitHub Actions runs

##@ Dependencies

deps: ## Install/sync local dependencies from uv.lock
	uv sync

add: ## Add a dependency and rebuild: make add pkg=httpx
	@test -n "$(pkg)" || (echo 'Usage: make add pkg=<package>' && exit 1)
	uv add $(pkg)
	$(MAKE) rebuild

##@ Git helpers

sync: ## Switch to main and pull the latest (fast-forward only)
	git checkout main
	git pull --ff-only --prune
	@echo ">> If teammates added migrations, run: make migrate"

branch: ## Create a branch from main: make branch n=feat/events-crud
	@test -n "$(n)" || (echo 'Usage: make branch n=type/short-description' && exit 1)
	git checkout -b $(n)

##@ Cleanup

clean: ## Remove caches (__pycache__, .pytest_cache, .ruff_cache)
	find . -type d -name __pycache__ -not -path "./.venv/*" -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache
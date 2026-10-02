# One entry point for local work. On Windows, run from Git Bash/WSL with `make` installed,
# or run the commands below directly.
.PHONY: help up down up-app sync lint test test-integration sweep reports evals-smoke web infra-synth helm-lint

BACKEND := cd backend &&
export PYTHONUTF8 := 1

help:
	@grep -E '^[a-z-]+:' Makefile | cut -d: -f1

up:            ## dependencies: pgvector, Keycloak, LocalStack
	docker compose up -d
down:
	docker compose down
up-app:        ## dependencies + app services (same images as prod)
	docker compose --profile app up -d --build

sync:
	$(BACKEND) uv sync

lint:          ## ruff, mypy, and the architecture import contracts
	$(BACKEND) uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports

test:          ## unit tests (no I/O)
	$(BACKEND) uv run pytest
test-integration: ## needs `make up`
	$(BACKEND) uv run pytest -m integration

sweep:         ## run the learning-record sweeper once (PRD §9.2)
	$(BACKEND) uv run python -m smart_tutor.apps.jobs.record_sweeper
reports:       ## run the content-gap report once (PRD §9.6)
	$(BACKEND) uv run python -m smart_tutor.apps.jobs.content_gap_report

evals-smoke:
	$(BACKEND) uv run --extra eval python -m evals.run --split smoke

web:
	cd web && npm run dev

infra-synth:
	cd infra && uv run cdk synth

helm-lint:
	helm lint deploy/helm/smart-tutor

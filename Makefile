# One entry point for local work. On Windows, run from Git Bash/WSL with `make` installed,
# or run the commands below directly.
.PHONY: help up down up-app sync lint test test-integration sweep glacier-tag retention evals-smoke web infra-synth helm-lint
.PHONY: design-states design-accept design-shots design-diff

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
glacier-tag:   ## run the Glacier tagger once (PRD §9.5)
	$(BACKEND) uv run python -m smart_tutor.apps.jobs.glacier_tagger
retention:     ## run the retention job once: traces 180 days, decline log 90 days (PRD D25, §9.6)
	$(BACKEND) uv run python -m smart_tutor.apps.jobs.retention

evals-smoke:
	$(BACKEND) uv run --extra eval python -m evals.run --split smoke

web:
	cd web && npm run dev

infra-synth:
	cd infra && uv run cdk synth

helm-lint:
	helm lint deploy/helm/smart-tutor

design-states: ## regenerate sdd/design/states.json from the prototype (design spec §5)
	cd web && npm run design:states
design-accept: ## ROUND=v0.3 [FEEDBACK="Q7, D1–D12"]: record an accepted design round
	cd web && npm run design:accept -- --round "$(ROUND)" --feedback "$(FEEDBACK)"
design-shots:  ## STATES="chat-*" [ROUND=v0.3] [THEME=light|dark|both]: render mockup states to .design-shots/
	cd web && npm run design:shots -- --states "$(STATES)" $(if $(ROUND),--round $(ROUND)) --theme $(or $(THEME),light)
design-diff:   ## FROM=v0.2 [TO=v0.3]: state changes between rounds and the open issues citing them
	cd web && npm run design:diff -- --from "$(FROM)" $(if $(TO),--to $(TO))

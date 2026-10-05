# One entry point for local work. On Windows, run from Git Bash/WSL with `make` installed,
# or run the commands below directly.
.PHONY: help up down up-app api agent mcp worker sync migrate lint test test-integration bedrock-check sweep glacier-tag retention evals-smoke web api-client infra-synth helm-lint
.PHONY: design-states design-accept design-shots design-diff

BACKEND := cd backend &&
# Host processes load the root .env into the environment: boto3 reads AWS_ENDPOINT_URL_* (LocalStack) only from there.
HOST := $(BACKEND) uv run --env-file ../.env
export PYTHONUTF8 := 1

help:
	@grep -E '^[a-z-]+:' Makefile | cut -d: -f1

up:            ## dependencies: pgvector, Keycloak, LocalStack
	docker compose up -d
down:
	docker compose down
up-app:        ## dependencies + app services (same images as prod)
	docker compose --profile app up -d --build

# App services on the host, one terminal each, on the same ports as the app profile (needs `make up`, `make migrate`).
api:           ## API at :10450, reloads on change
	$(HOST) uvicorn smart_tutor.apps.api.main:app --reload --port 10450
agent:         ## agent at :10451, reloads on change
	$(HOST) uvicorn smart_tutor.apps.agent.server:app --reload --port 10451
mcp:           ## RAG MCP server at :10452/mcp (SMART_TUTOR_MCP_PORT in .env)
	$(HOST) python -m smart_tutor.apps.mcp_server.server
worker:        ## ingestion worker (no port); restart it after code changes
	$(HOST) --extra ingest python -m smart_tutor.apps.worker.main

sync:
	$(BACKEND) uv sync

migrate:       ## bring the local database to the latest Alembic revision (needs `make up`)
	$(BACKEND) uv run python -m smart_tutor.apps.jobs.migrate

lint:          ## ruff, mypy, and the architecture import contracts
	$(BACKEND) uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports

test:          ## unit tests (no I/O)
	$(BACKEND) uv run pytest
test-integration: ## needs `make up`
	$(BACKEND) uv run pytest -m integration
bedrock-check: ## real Bedrock calls (us-east-1, your AWS credentials): models reachable and behaving (PRD M0)
	$(BACKEND) uv run pytest -m bedrock

sweep:         ## run the learning-record sweeper once (PRD §9.2)
	$(BACKEND) uv run python -m smart_tutor.apps.jobs.record_sweeper
glacier-tag:   ## run the Glacier tagger once (PRD §9.5)
	$(BACKEND) uv run python -m smart_tutor.apps.jobs.glacier_tagger
retention:     ## run the retention job once: traces 180 days, decline log 90 days (PRD D25, §9.6)
	$(BACKEND) uv run python -m smart_tutor.apps.jobs.retention

evals-smoke:
	$(BACKEND) uv run --extra eval python -m evals.run --split smoke

api-client:    ## regenerate web/src/api from the API's OpenAPI schema
	$(BACKEND) uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate

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

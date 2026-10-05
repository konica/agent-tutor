# Smart Tutor

An AI tutor for your own documents: learners upload PDFs, the system suggests subjects from a shared catalog, and the tutor answers questions only from the learner's documents in the conversation's subjects (up to 3), with citations. Identical files are processed once across all users. Release 2 adds a research map (citation links, timeline, reading order); later releases add quizzes and reports, sharing and imports, and a deep knowledge graph. Product requirements: [`sdd/prd.md`](sdd/prd.md). Repository layout: [`sdd/specs/2026-10-02-project-structure-design.md`](sdd/specs/2026-10-02-project-structure-design.md).

## Layout

| Path | What |
|---|---|
| `sdd/` | PRD, design specs, ADRs, designer briefs |
| `backend/` | The `smart_tutor` Python package (API, agent, RAG MCP server, ingestion worker, jobs), tests, evals |
| `web/` | React + TypeScript web app |
| `infra/` | AWS CDK app (Python), us-east-1 |
| `deploy/helm/` | Umbrella Helm chart for EKS and cluster add-on values |
| `local/` | Files used only by Docker Compose (Keycloak realm, LocalStack and Postgres init) |

## Local development

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node 22+, an AWS profile allowed to invoke the Bedrock models (PRD Appendix A).

```bash
cp .env.example .env          # fill in AWS_PROFILE and LANGSMITH_API_KEY
make up                       # pgvector, Keycloak (realm imported), LocalStack
make sync                     # backend dependencies
make lint test                # ruff, mypy, import contracts, unit tests
make web                      # http://localhost:10453
```

Keycloak admin console: http://localhost:10401 (admin / admin). Test users: `learner@example.com` / `learner`, `learner2@example.com` / `learner2`, `admin@example.com` / `admin`.

No `make` on Windows? Each target in the `Makefile` is a one-line command you can run directly.

### Run the app

Two ways, on the same ports: dependency services count up from 10400, app services from 10450.

| Service | Port | Option A: all in Docker | Option B: app on your machine |
|---|---|---|---|
| Postgres (pgvector) | 10400 | Docker | Docker |
| Keycloak | 10401 | Docker | Docker |
| LocalStack (S3, SQS, SSM) | 10402 | Docker | Docker |
| API | 10450 | Docker | `make api` (reloads on change) |
| Agent | 10451 | Docker | `make agent` |
| RAG MCP server | 10452 | Docker | `make mcp` |
| Ingestion worker | — | Docker | `make worker` |
| Web | 10453 | Docker (nginx build) | `make web` (Vite, hot reload) |

**Option A** (same images as production): `make up-app`, then open http://localhost:10453.

**Option B** (faster to iterate): dependencies in Docker, app processes on your machine.

```bash
docker compose --profile app stop     # only if Option A is running: it holds 10450–10453
make up                               # pgvector, Keycloak, LocalStack
make sync migrate                     # backend dependencies, database schema
cd web && npm ci && cd ..             # web dependencies (first time)
# then one terminal each:
make api                              # http://localhost:10450/docs
make worker                           # processes uploads from the LocalStack queue
make web                              # http://localhost:10453 — sign in as learner@example.com / learner
make agent                            # optional until the tutor lands (M2)
make mcp                              # optional until the tutor lands (M2)
```

Without `make` (PowerShell, from the repository root):

```powershell
docker compose up -d
cd backend; uv sync; uv run python -m smart_tutor.apps.jobs.migrate; cd ..
# one terminal each:
cd backend; uv run --env-file ../.env uvicorn smart_tutor.apps.api.main:app --reload --port 10450
cd backend; uv run --env-file ../.env --extra ingest python -m smart_tutor.apps.worker.main
cd web; npm ci; npm run dev
cd backend; uv run --env-file ../.env uvicorn smart_tutor.apps.agent.server:app --reload --port 10451
cd backend; uv run --env-file ../.env python -m smart_tutor.apps.mcp_server.server
```

- Always start backend processes with `--env-file ../.env`. Settings read `.env` only from the working directory (`backend/`), and boto3 reads the `AWS_ENDPOINT_URL_*` variables only from the environment. Without that file, uploads would go to real AWS instead of LocalStack.
- The MCP server listens on `SMART_TUTOR_MCP_PORT`: 10452 on the host from `.env`, and 8000 inside its container. If your `.env` was copied before this setting existed, add `SMART_TUTOR_MCP_PORT=10452` to it.
- The web app's defaults already point at the API (:10450) and Keycloak (:10401), and Keycloak's `smart-tutor-web` client allows only http://localhost:10453. Keep Vite on that port; `strictPort` makes it fail rather than move to another one.
- Back to Option A: stop the host processes, then run `make up-app`.

## Architecture rules

Code is organized by module (`knowledge`, `tutoring`, `learning`, `accounts`, `insights`, ...) with `domain / application / ports / adapters` inside each, and entrypoints in `smart_tutor/apps`. The rules are enforced by `lint-imports` (contracts in `backend/pyproject.toml`) in CI.

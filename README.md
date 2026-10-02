# Smart Tutor

An AI tutor for your own documents: learners upload PDFs, the system suggests subjects from a shared catalog, and the tutor answers questions only from the learner's documents in one subject at a time, with citations. Identical files are processed once across all users. Later releases add quizzes and reports, then sharing and a knowledge graph of how documents relate over time. Product requirements: [`sdd/prd.md`](sdd/prd.md). Repository layout: [`sdd/specs/2026-10-02-project-structure-design.md`](sdd/specs/2026-10-02-project-structure-design.md).

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
make web                      # http://localhost:5173
```

Keycloak admin console: http://localhost:8080 (admin / admin). Test users: `learner@example.com` / `learner`, `learner2@example.com` / `learner2`, `admin@example.com` / `admin`.

No `make` on Windows? Each target in the `Makefile` is a one-line command you can run directly.

## Architecture rules

Code is organized by module (`knowledge`, `tutoring`, `learning`, `accounts`, `insights`, ...) with `domain / application / ports / adapters` inside each, and entrypoints in `smart_tutor/apps`. The rules are enforced by `lint-imports` (contracts in `backend/pyproject.toml`) in CI.

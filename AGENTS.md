# AGENTS.md

Instructions for coding agents working in this repository. Humans: start with `README.md`.
Nested files take precedence for their folder: see `backend/AGENTS.md` before changing Python code.

## Project overview

Smart Tutor is a subject-scoped AI tutor. A learner enrolls in subjects (e.g. IELTS, AI Agents) and asks questions; the tutor detects the subject, answers **only** from admin-uploaded PDFs with citations (title + page), and declines everything else. Learners keep one Lesson Note per conversation, and a lifetime learning record is written per thread.

- Product requirements (source of truth for behavior): `sdd/prd.md`
- Repository layout and architecture rules: `sdd/specs/2026-10-02-project-structure-design.md`
- Release 1 = core tutor (modules `knowledge`, `tutoring`, `learning`, `accounts`, `insights`). Release 2 = quizzes, reports, recommendations, topic catalog. Do not build Release 2 features unless asked.

Runtime pieces: Web app (React) → API (FastAPI) → Agent (LangGraph) → RAG MCP server → PostgreSQL + pgvector. Ingestion worker consumes S3 events from SQS (Docling → chunk → embed). Identity: Keycloak (OIDC); the user's JWT is forwarded API → agent → MCP. Models on Amazon Bedrock (us-east-1): agent `us.amazon.nova-2-lite-v1:0`, embeddings `amazon.nova-2-multimodal-embeddings-v1:0` (1024-dim), judge `qwen.qwen3-32b-v1:0`. Production: everything on EKS via Helm; AWS resources via CDK (Python).

## Repository map

| Path | What |
|---|---|
| `backend/` | The one Python package `smart_tutor` (all backend deployables), `tests/`, `evals/` — see `backend/AGENTS.md` |
| `web/` | React 19 + TypeScript + Vite; screens in `src/features/<feature>/` |
| `infra/` | AWS CDK app (Python, separate uv project); one stack per concern in `smart_tutor_infra/stacks/` |
| `deploy/helm/` | Umbrella chart `smart-tutor` with subcharts (`api`, `agent`, `mcp-server`, `worker`, `web`, `jobs`, `keycloak`) and add-on values |
| `local/` | Compose-only files: Keycloak realm import, LocalStack init script, Postgres init SQL |
| `sdd/` | PRD, design specs, ADRs (`sdd/adr/`), designer briefs |

## Dev environment tips

- Tools: Docker, `uv`, Node 22+, Helm. Python 3.12 is pinned in `backend/.python-version`; uv downloads it.
- `docker compose up -d` starts dependencies only (pgvector, Keycloak on :8080, LocalStack on :4566). `docker compose --profile app up -d --build` adds the app containers.
- Copy `.env.example` to `.env`. Bedrock and LangSmith have no local emulator: local runs call real us-east-1 models with a developer AWS profile.
- Local Keycloak users: `learner@example.com`/`learner`, `learner2@example.com`/`learner2`, `admin@example.com`/`admin`; admin console admin/admin.
- The `Makefile` lists every common command. On Windows without `make`, run the target's command directly.
- Windows Git Bash: prefix with `PYTHONUTF8=1` for `lint-imports` (its output crashes on cp1252), and `MSYS_NO_PATHCONV=1` for commands that take `/smart-tutor/...` style paths (SSM parameter names).
- Changing `local/keycloak/realm-smart-tutor.json`: Keycloak imports it only when the realm does not exist; run `docker compose down -v` to re-import. The file lists roles explicitly, so built-in roles (`offline_access`, `uma_authorization`) must stay defined in it.

## Build and test commands

```bash
# backend (run inside backend/)
uv sync                                   # core + dev group
uv run ruff check . && uv run ruff format --check .
uv run mypy                               # strict, src/ only
PYTHONUTF8=1 uv run lint-imports          # architecture contracts — must stay "0 broken"
uv run pytest                             # unit tests (integration excluded by default)
uv run pytest -m integration              # needs docker compose up

# web (inside web/)
npm ci && npm run build                   # tsc + vite build

# infra (inside infra/)
uv run pytest                             # CDK synth test

# helm (repo root)
helm lint deploy/helm/smart-tutor && helm lint deploy/helm/smart-tutor -f deploy/helm/smart-tutor/values-prod.yaml

# images (repo root)
docker build --target api|agent|mcp|worker backend/
docker build web/
```

CI (`.github/workflows/ci.yml`) runs the backend checks, the web build, and helm lint. Run the same locally before pushing.

## Code style

- Python: ruff (line length 120), strict mypy, type hints everywhere, dataclasses or Pydantic for data. Dependencies passed through constructors; no module-level clients or globals.
- Match the surrounding code: comment density, naming, docstring style (one-line module docstring stating responsibility and PRD reference).
- TypeScript: strict mode; one folder per feature under `web/src/features/`; API calls only through `web/src/api/` (generated from the API's OpenAPI schema).
- Keep docs in plain, short sentences. Reference PRD sections (e.g. "PRD §9.3") when code implements a requirement.

## Testing instructions

- Add or update tests for every behavior change. Unit tests use fakes from `backend/tests/fakes/` (e.g. `FakeChatModel`, `FakeEmbeddingModel`), never real Bedrock.
- Domain rules (e.g. `Thread.bind_subject()` refuses to rebind, notes are archived not deleted) get unit tests in `backend/tests/unit/<module>/`.
- Data isolation (PRD US-12) tests live in `backend/tests/isolation/`; any new endpoint or MCP tool that returns learner data needs one.
- Agent quality is measured with LangSmith evals in `backend/evals/`; release targets are in `backend/evals/thresholds.yaml`. Don't loosen a threshold to make a run pass.

## Security considerations

- Never commit secrets; `.env` is git-ignored. Production secrets come from AWS Secrets Manager via External Secrets.
- The user's JWT is passed in runtime context and HTTP headers only — never put tokens in prompts, logs, or traces.
- Subject access is enforced in the MCP server in code and SQL (enrolled subjects ∩ requested subjects), never by the prompt.
- Only the user's prompt is untrusted input; keep prompt-injection defenses on it. Content-gap records must not store user ids.
- Documents and Lesson Notes are never hard-deleted (archive only).

## Commit and PR instructions

- Never commit to `main`; work on a branch and open a PR.
- Commit subject in the imperative mood ("Add …", "Fix …"), body explains why.
- Before committing: backend lint, mypy, `lint-imports`, and pytest pass; web build passes if `web/` changed; `helm lint` passes if `deploy/` changed.
- If a change alters product behavior or architecture, update `sdd/prd.md` (bump its version in the status line) or the spec in the same PR. Record new architecture decisions as ADRs in `sdd/adr/`.

# backend

The one Python package, `smart_tutor`, shared by every backend deployable.

| Path | What |
|---|---|
| `src/smart_tutor/shared/` | Shared kernel: ids, `TokenUsage`, `Citation`, `ModelFactory` (LangChain chat and embedding models by role), auth, infra clients, settings |
| `src/smart_tutor/<module>/` | Feature modules (`knowledge`, `tutoring`, `learning`, `accounts`, `insights`; R2: `catalog`, `quizzes`, `recommendations`, `reports`), each with `domain/ application/ ports/ adapters/` |
| `src/smart_tutor/apps/` | Entrypoints: `api`, `agent`, `mcp_server`, `worker`, `jobs` |
| `tests/` | `unit/` (fakes, no I/O), `integration/` (Compose stack), `isolation/` (US-12), `fakes/` |
| `evals/` | LangSmith dataset generators, evaluators, thresholds, runner |

## Commands

```bash
uv sync                      # core + dev group
uv sync --extra ingest       # + PDF loader (worker)
uv sync --extra eval         # + evaluation deps
uv run pytest                # unit tests
uv run pytest -m integration # needs `make up`
uv run lint-imports          # architecture rules (see pyproject.toml)
uv run ruff check . && uv run mypy
```

## Images

`Dockerfile` has one target per deployable: `api`, `agent`, `mcp`, `worker` (only the worker installs `[ingest]`). CronJobs reuse the `api` image.

Design: `sdd/specs/2026-10-02-project-structure-design.md`.

## Check sign-in against Compose

The unit tests fake Keycloak; this is the end-to-end check for US-1 (#45).

1. `docker compose down -v && docker compose --profile app up -d --build` (re-imports the realm, runs `migrate`). `down -v` wipes local Compose data (database, Keycloak users).
2. Open http://localhost:5173, sign in as `learner@example.com` / `learner`: the Library shows "Upload your first document" and the user menu shows "Local Learner".
3. In the browser's dev tools, copy the `Authorization` header of the `GET /me` request, then:
   `curl -i http://localhost:8001/me -H "Authorization: Bearer <token>"` → `200`.
4. Sign out from the user menu, then repeat the `curl` → `401` (the token is revoked although not expired).
5. `curl -i http://localhost:8001/me` → `401` with `WWW-Authenticate: Bearer`.

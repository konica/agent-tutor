# backend

The one Python package, `smart_tutor`, shared by every backend deployable.

| Path | What |
|---|---|
| `src/smart_tutor/shared/` | Shared kernel: ids, `TokenUsage`, `Citation`, model ports (`ChatModel`, `EmbeddingModel`), `ModelFactory`, auth, infra clients, settings |
| `src/smart_tutor/<module>/` | Feature modules (`knowledge`, `tutoring`, `learning`, `accounts`, `insights`; R2: `catalog`, `quizzes`, `recommendations`, `reports`), each with `domain/ application/ ports/ adapters/` |
| `src/smart_tutor/apps/` | Entrypoints: `api`, `agent`, `mcp_server`, `worker`, `jobs` |
| `tests/` | `unit/` (fakes, no I/O), `integration/` (Compose stack), `isolation/` (US-12), `fakes/` |
| `evals/` | LangSmith dataset generators, evaluators, thresholds, runner |

## Commands

```bash
uv sync                      # core + dev group
uv sync --extra ingest       # + Docling (worker)
uv sync --extra eval         # + evaluation deps
uv run pytest                # unit tests
uv run pytest -m integration # needs `make up`
uv run lint-imports          # architecture rules (see pyproject.toml)
uv run ruff check . && uv run mypy
```

## Images

`Dockerfile` has one target per deployable: `api`, `agent`, `mcp`, `worker` (only the worker installs `[ingest]`). CronJobs reuse the `api` image.

Design: `sdd/specs/2026-10-02-project-structure-design.md`.

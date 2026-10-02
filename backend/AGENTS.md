# AGENTS.md — backend

Applies to everything under `backend/`. Repo-wide context (product, commands, security, PR rules) is in the root `AGENTS.md`.

## Package layout

One package, `src/smart_tutor/`, shared by every backend deployable. Modules first, layers inside each module:

```
smart_tutor/
├── shared/      # kernel: ids, TokenUsage, Citation, errors; ports ChatModel/EmbeddingModel/Clock; ModelFactory; auth, postgres, aws, bedrock adapters; config.py
├── knowledge/   # documents, chunks, ingestion, search
├── tutoring/    # threads, subject detection, relevance gate, ask path
├── learning/    # Lesson Notes, learning records
├── accounts/    # learners, enrollments, token usage, rate-limit policy
├── insights/    # content gaps
├── catalog/ quizzes/ recommendations/ reports/   # Release 2 — empty until then
└── apps/        # api, agent, mcp_server, worker, jobs — one composition root per deployable
```

Each module has `domain/` (entities and rules, no I/O), `application/` (one service per use case — the module's public API), `ports/` (ABCs), `adapters/` (implementations; the only place vendor SDKs appear) and a `README.md` stating what it owns.

## Where does my change go?

- A business rule → a method on a domain class in the owning module (e.g. `tutoring/domain/thread.py`).
- A use case → a service in that module's `application/`, receiving ports through its constructor.
- Talking to Bedrock, Postgres, S3, SQS, MCP, LangGraph store → a port in `ports/` plus an implementation in `adapters/`.
- An HTTP route, graph node, MCP tool, SQS handler or CronJob → `apps/<app>/`; it parses input, calls one service, formats output. No business rules in `apps/`.
- Model calls → ask `ModelFactory` for a role (`agent`, `judge`, `embedding`). Never hard-code a model ID or import `boto3`/`langchain_aws` outside adapters.

## Architecture rules (enforced by `PYTHONUTF8=1 uv run lint-imports`)

Contracts live in `pyproject.toml` under `[tool.importlinter]`; CI fails if any is broken.

1. Inside each module: `adapters | application` → `ports` → `domain`. Adapters and application never import each other.
2. Another module is used only through its `application` package. Its `domain`, `ports`, `adapters` are private. Everyone may import `shared`; `shared` imports no feature module.
3. Nothing imports `smart_tutor.apps`.
4. `domain`, `application`, `ports` import no vendor SDK (`boto3`, `botocore`, `docling`, `fastapi`, `langchain_aws`, `langgraph`, `mcp`, `psycopg`, `sqlalchemy`) and not `shared.adapters`.
5. Docling is imported only in `knowledge.adapters` (it pulls in PyTorch and is installed only in the worker image).
6. Module dependency order, top to bottom: `reports` → `recommendations` → `quizzes | catalog` → `learning` → `tutoring | knowledge` → `accounts | insights`. A lower module never imports a higher one. If you need a new cross-module dependency, change this order deliberately and say why in the PR; flows that go the "wrong" way are orchestrated in `apps/` (e.g. "Discuss this note": `apps/api` reads the note from `learning`, then starts a thread in `tutoring`).
7. The agent never reads chunk tables: `tutoring` retrieves through its `Retriever` port (MCP client), which calls `apps/mcp_server` → `knowledge.application.SearchService`.

Do not silence a contract with `ignore_imports` to make CI pass; fix the dependency direction.

## Dependencies

- Core dependencies go in `[project.dependencies]`. Heavy, single-service dependencies go behind an extra: `ingest` (Docling, worker only) or `eval` (evaluation runs). Dev tools go in the `dev` dependency group.
- After editing `pyproject.toml`, run `uv lock` and commit `uv.lock`.
- `mcp` is 2.x: the server class is `mcp.server.MCPServer` (FastMCP was renamed); host and port are passed to `run()`.

## Tests

- `tests/unit/<module>/` — domain and application with fakes (`tests/fakes/`), no I/O; this is the default `pytest` run.
- `tests/integration/<module>/` — adapters against the Compose stack; mark with `@pytest.mark.integration`.
- `tests/isolation/` — cross-user and cross-subject access tests (PRD US-12).
- Async tests need no decorator (`asyncio_mode = "auto"`). Import fakes as `from fakes import FakeChatModel`.

## Images

`Dockerfile` targets: `api`, `agent`, `mcp`, `worker` (CronJobs reuse `api`). Containers run as uid 10001. Only `worker` installs the `ingest` extra; keep it that way.

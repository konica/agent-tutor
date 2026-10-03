# AGENTS.md — backend

Applies inside `backend/`. Product rules, checks, and PR rules are in the root `AGENTS.md`.

## Package layout

One package, `src/smart_tutor/`, shared by every backend deployable. **Modules first, layers inside each module** (ADR 0001):

```
smart_tutor/
├── shared/      # kernel: ids, TokenUsage, Citation, errors; ports ChatModel/EmbeddingModel/Clock; ModelFactory;
│                #   bedrock, auth (JWT), postgres, aws adapters; config.py
├── knowledge/   # library: contents (SHA-256 dedupe, states, retry), documents, can_read, upload, ingestion, search
├── subjects/    # shared subject catalog, personal names, suggestion ranking, name checks
├── tutoring/    # threads (1–3 subjects, growth), detection, relevance gate, ask path
├── learning/    # Lesson Notes, learning records
├── accounts/    # learner profile and terms, rate limits and daily caps, token usage
├── insights/    # decline log
├── graph/       # Release 2 research map (Release 5 deep graph)
├── catalog/ quizzes/ recommendations/ reports/   # Release 3
└── apps/        # api, agent, mcp_server, worker, jobs — one composition root per deployable
```

Each module has `domain/` (entities and rules, no I/O), `application/` (one service per use case — the module's public API), `ports/` (ABCs), `adapters/` (implementations; the only place vendor SDKs appear). **Each module's `README.md` states what it owns, its key classes, what it may use, and its rules — read it before editing the module.**

## Where a change goes

- A business rule → a method on the owning domain class (e.g. `Thread.add_subject()`, `Document.set_subjects()`, `Content.retry()`).
- A use case → a service in the owning module's `application/`, receiving ports through its constructor.
- Talking to Bedrock, PostgreSQL, S3, SQS, MCP, the PDF loader, or the LangGraph store → a port in `ports/` and its implementation in `adapters/`.
- An HTTP route, graph node, MCP tool, SQS handler, or CronJob → `apps/<app>/`: parse input, call one service, format output.
- A flow that crosses modules against the dependency order → orchestrate it in `apps/` (e.g. "Discuss this note": `apps/api` reads the note from `learning`, then starts a thread in `tutoring`).
- A model call → ask `ModelFactory` for a role (`agent`, `judge`, `embedding`).

## Architecture rules

Enforced by `PYTHONUTF8=1 uv run lint-imports` (18 contracts in `pyproject.toml` under `[tool.importlinter]`, generated from one module list):

1. Inside a module: `adapters | application` → `ports` → `domain`.
2. Another module is used only through its `application` package; `shared` is open to all and imports no module.
3. `apps` is a leaf: nothing imports it.
4. `domain`, `application`, and `ports` stay free of vendor SDKs and `shared.adapters`; the PDF loader (`pypdf`, `langchain_text_splitters`) lives only in `knowledge.adapters` and ships only in the worker image (ADR 0005).
5. Module order, top to bottom: `reports` → `recommendations` → `quizzes | catalog` → `learning` → `tutoring` → `graph` → `knowledge` → `subjects` → `accounts | insights`. A module imports only modules below it.
6. The agent retrieves through `tutoring`'s `Retriever` port (MCP client) → `apps/mcp_server` → `knowledge.application.SearchService`; chunk tables are read only by `knowledge`.

A new cross-module dependency means moving a module in the order on purpose and explaining why in the PR; fix the dependency direction to make a broken contract pass.

## Dependencies

- Core dependencies in `[project.dependencies]`; heavy single-service ones behind an extra: `ingest` (PDF loader and text splitter, worker only) or `eval`. Dev tools in the `dev` dependency group. Run `uv lock` and commit `uv.lock` after editing.
- `mcp` is 2.x: the server class is `mcp.server.MCPServer`, and host/port go to `run()`.
- Bedrock adapters use boto3 Converse/InvokeModel directly, not `langchain-aws` chat models (ADR 0006); `boto3-stubs[bedrock-runtime]` types the client for mypy.

## Tests

- `tests/unit/<module>/` — domain and application with fakes from `tests/fakes/` (`from fakes import FakeChatModel`); the default `pytest` run. Async tests need no decorator.
- `tests/integration/<module>/` — adapters against the Compose stack, marked `@pytest.mark.integration`.
- `tests/isolation/` — cross-user access and dedupe guarantees (PRD US-11, US-12).
- `tests/bedrock/` — real Bedrock calls through `ModelFactory`, marked `@pytest.mark.bedrock` (`make bedrock-check`). Run it after changing a model ID, an adapter, or boto3. Unit tests never trace to LangSmith (`tests/unit/conftest.py`).

## Images

`Dockerfile` targets `api`, `agent`, `mcp`, `worker` (CronJobs reuse `api`), running as uid 10001. Only `worker` installs the `ingest` extra.

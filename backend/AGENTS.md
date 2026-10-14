# AGENTS.md — backend

Applies inside `backend/`. Product rules, checks, and PR rules are in the root `AGENTS.md`.

## Package layout

One package, `src/smart_tutor/`, shared by every backend deployable. **Modules first, layers inside each module** (ADR 0001):

```
smart_tutor/
├── shared/      # kernel: ids, TokenUsage, Citation, errors; port Clock; ModelFactory (LangChain models by role);
│                #   bedrock, auth (JWT), postgres, aws adapters; config.py
├── knowledge/   # library: contents (per learner, SHA-256 duplicate check, states, retry), documents (archive, delete), can_read, upload, ingestion, search, viewer links
├── subjects/    # shared subject catalog, personal names, suggestion ranking, name checks
├── tutoring/    # threads and their documents used, relevance gate, ask path
├── learning/    # Lesson Notes, learning records
├── accounts/    # learner profile and terms, rate limits and daily caps, token usage
├── insights/    # decline log
├── graph/       # Release 2 research map (Release 5 deep graph)
├── catalog/ quizzes/ recommendations/ reports/   # Release 3
└── apps/        # api, agent, mcp_server, worker, jobs — one composition root per deployable
```

Each module has `domain/` (entities and rules, no I/O), `application/` (one service per use case — the module's public API), `ports/` (ABCs), `adapters/` (implementations; the only place vendor SDKs appear). **Each module's `README.md` states what it owns, its key classes, what it may use, and its rules — read it before editing the module.**

## Where a change goes

- A business rule → a method on the owning domain class (e.g. `Document.set_subjects()`, `Content.retry()`).
- A use case → a service in the owning module's `application/`, receiving ports through its constructor.
- Talking to Bedrock, PostgreSQL, S3, SQS, MCP, the PDF loader, or the LangGraph store → a port in `ports/` and its implementation in `adapters/`.
- An HTTP route, graph node, MCP tool, SQS handler, or CronJob → `apps/<app>/`: parse input, call one service, format output.
- A flow that crosses modules against the dependency order → orchestrate it in `apps/` (e.g. "Discuss this note": `apps/api` reads the note from `learning`, then starts a thread in `tutoring`).
- A model call → ask `ModelFactory` for a role (`agent`, `judge`, `embedding`).

## Architecture rules

Enforced by `PYTHONUTF8=1 uv run lint-imports` (21 contracts in `pyproject.toml` under `[tool.importlinter]`, generated from one module list):

1. Inside a module: `adapters | application` → `ports` → `domain`.
2. Another module is used only through its `application` package; `shared` is open to all and imports no module.
3. `apps` is a leaf: nothing imports it.
4. `domain`, `application`, and `ports` stay free of vendor SDKs and `shared.adapters`; the PDF loader (`pypdf`, `langchain_text_splitters`) lives only in `knowledge.adapters` and ships only in the worker image (ADR 0005).
5. Module order, top to bottom: `reports` → `recommendations` → `quizzes | catalog` → `learning` → `tutoring` → `graph` → `knowledge` → `subjects` → `accounts | insights`. A module imports only modules below it.
6. The agent retrieves through `tutoring`'s `Retriever` port (MCP client) → `apps/mcp_server` → `knowledge.application.SearchService`; chunk tables are read only by `knowledge`.

A new cross-module dependency means moving a module in the order on purpose and explaining why in the PR; fix the dependency direction to make a broken contract pass.

## Dependencies

- Core dependencies in `[project.dependencies]`; heavy single-service ones behind an extra: `ingest` (PDF loader and text splitter, worker only), `guard` (Guardrails AI output guard, agent only; ADR 0018), `topic` (onnxruntime and tokenizers for the topic check, agent only; ADR 0020), or `eval`. Dev tools in the `dev` dependency group. Run `uv lock` and commit `uv.lock` after editing.
- `mcp` is 2.x: the server class is `mcp.server.MCPServer`, and host/port go to `run()`.
- Models are LangChain's: services take a `BaseChatModel` or `Embeddings` from `ModelFactory` (`init_chat_model`; ADR 0006). Don't hand-write model wrappers or call `bedrock-runtime` with boto3. The one exception is ApplyGuardrail, which LangChain doesn't wrap: it goes through `shared.adapters.aws.clients.bedrock_runtime_client` in an adapter (ADR 0019).

## Tests

- `tests/unit/<module>/` — domain and application with fakes from `tests/fakes/` (`from fakes import fake_chat_model, fake_embeddings`); the default `pytest` run. Async tests need no decorator.
- `tests/integration/<module>/` — adapters against the Compose stack, marked `@pytest.mark.integration`.
- `tests/isolation/` — cross-user access, per-learner contents, and delete guarantees (PRD US-10c, US-11, US-12).
- `tests/bedrock/` — real Bedrock calls through `ModelFactory` (`test_question_screen.py` calls ApplyGuardrail directly and skips without a guardrail id and version), marked `@pytest.mark.bedrock` (`make bedrock-check`). Run it after changing a model ID, an adapter, or boto3.
- No test traces, whatever environment is loaded (ADR 0017): `tests/conftest.py` blanks `SMART_TUTOR_PHOENIX_URL` for the session and fails a test that leaves LangChain instrumented; it also turns LangSmith tracing off (evals use LangSmith) and makes its default client a `RecordingClient`. A test that checks spans traces inside `fakes.recorded_traces()` (in-memory exporter).

## Images

`Dockerfile` targets `api`, `agent`, `agent-jailbreak`, `mcp`, `worker` (CronJobs reuse `api`), running as uid 10001. Only `worker` installs the `ingest` extra and only `agent` the `guard` and `topic` extras and the topic-check model folder (`models/topic_check/`). `agent-jailbreak` is the agent plus the `jailbreak` extra and the DetectJailbreak models (#200); CI builds only `agent`.

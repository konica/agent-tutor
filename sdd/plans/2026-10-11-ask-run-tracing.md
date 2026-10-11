# Ask run tracing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every `/ask` run traces to LangSmith as one root run named `ask` with operator metadata and a keyed learner hash (never the user id, email, or token); the API stores the run id with the turn and returns it; the worker's model calls trace into their own project.

**Architecture:** The API mints a run id (UUID) and, for a new conversation, the thread id before it calls the agent, and sends both in the `/ask` body. The agent wraps its stream in `langsmith.trace("ask", run_id=…)`; LangGraph's runs nest under it through LangSmith's tracing context; facts known only at the end (decline code, chunks given to the model) are merged into the root's metadata when it ends. The learner is an HMAC-SHA256 of their user id with a key from settings. The worker groups each content's processing under an `ingest` run in `<LANGSMITH_PROJECT>-ingestion`, through a small `RunTracing` port so `knowledge.application` stays free of LangSmith.

**Tech Stack:** Python 3.13, FastAPI, LangGraph 1.2, langsmith 0.14 (`langsmith.trace`, `RunTree`), langchain-core 1.6, SQLAlchemy + Alembic, pydantic-settings; web client regenerated from OpenAPI.

**Spec:** GitHub issue #221 (parent #220); PRD §10.4, §9.2; ADR 0007. Deployment provisioning of keys and turning tracing on in deployed environments is #229; learner ratings on the run id are #227.

## Decisions taken for this slice

- **Turn id = run id.** `thread_turns.turn_id` is an identity assigned only when the answer is kept, after the run has started. The API mints one UUID per ask; it is the trace's root run id and is stored on the turn as `run_id`. The trace carries `thread_id`; the run id identifies the turn. No separate `turn_id` metadata key.
- **New conversation's thread id is minted by the API before the agent call** (`ConversationService.start_thread(..., thread_id=...)`), so a first turn's trace carries its thread id.
- **Deployment kind is a new setting** `deployment: Literal["local", "on-premise", "native-cloud"]` (metadata key `deployment`); the existing `environment` holds the stage (`prod`).
- **The hash key is required only while LangSmith tracing is on.** On-premise deploys from `main` with tracing off and no key; #229 provisions the key with the LangSmith API key. A process that starts with tracing on and no key refuses to start.
- **Embedding calls are not LangChain-traced** (NovaEmbeddings has no callbacks); the worker's `ingest` run groups the describer's chat call; the embedding model id is in its metadata.

## Global Constraints

- Settings come from env with prefix `SMART_TUTOR_`: new `SMART_TUTOR_LEARNER_HASH_KEY` (SecretStr, default empty) and `SMART_TUTOR_DEPLOYMENT` (default `local`). The key is never in code; tests pass it explicitly.
- The raw user id, the principal's name/email, and the token never appear in any recorded trace payload (inputs, outputs, metadata, tags, extra).
- Metadata keys on the `ask` root: `thread_id`, `deployment`, `chat_model`, `embedding_model`, `learner_hash`, `limited` (bool), and at end `decline` (`"limited"`, `"no_documents"`, or `"none"`) and `chunks` (int; 0 for a decline).
- Unit tests never reach the network: they use `RecordingClient` (tests/fakes/tracing.py); `tests/unit/conftest.py` keeps tracing off unless a test opts in with `langsmith.tracing_context(enabled=True)`.
- Import rules (backend/AGENTS.md): `knowledge.application` may use `shared.ports`, never `shared.adapters` or vendor SDKs; `apps` is a leaf.
- Checks before each commit: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`.
- Commit subjects in the imperative mood; body says why; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A client disconnect mid-stream** closes the agent's generator from another context: the trace must still end (no `ValueError` from context reset, no hung run). `langsmith.trace._teardown` restores by `.set()`, so this holds; Task 2 pins it with a test that closes the generator after the first event.
2. **An agent error mid-turn** (`unavailable`/`unauthenticated`) still ends the `ask` root with an error and the static metadata, and the learner still gets the error event — tracing never changes what the learner sees.
3. **Old callers** (evals, older API) send no `run_id`/`thread_id`: the agent still traces, with a fresh run id and no `thread_id` key.
4. **Turns kept before this change** have no run id: `run_id` is nullable and `GET /threads/{id}/turns` returns `null` for them.
5. **Same learner, two processes** (agent and worker) must produce the same hash for the same key so per-learner usage groups across projects: both use `LearnerHasher` from `shared.adapters.tracing`.

---

### Task 1: Learner hash, run metadata, and the RunTracing port

**Files:**
- Modify: `backend/src/smart_tutor/shared/config.py` (two settings)
- Modify: `backend/src/smart_tutor/shared/domain/ids.py` (`RunId`)
- Create: `backend/src/smart_tutor/shared/ports/run_tracing.py`
- Create: `backend/src/smart_tutor/shared/adapters/tracing.py`
- Create: `backend/tests/fakes/tracing.py`; export from `backend/tests/fakes/__init__.py`
- Modify: `backend/tests/unit/apps/agent/test_no_token_in_traces.py` (import `RecordingClient` from fakes instead of defining it)
- Test: `backend/tests/unit/shared/test_tracing.py`

**Interfaces:**
- Produces:
  - `Settings.deployment: Literal["local", "on-premise", "native-cloud"] = "local"`, `Settings.learner_hash_key: SecretStr = SecretStr("")`
  - `RunId = NewType("RunId", str)` in `shared.domain.ids`
  - `shared.ports.run_tracing.RunTracing` (ABC) with `run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> AbstractContextManager[None]`; `NoRunTracing(RunTracing)` returning `nullcontext()`
  - `shared.adapters.tracing.LearnerHasher(key: str)`, `__call__(user_id: UserId) -> str` (64 hex chars); raises `ValueError` on an empty key
  - `shared.adapters.tracing.learner_hasher(settings: Settings) -> LearnerHasher | None` — None when no key is set and tracing is off; `RuntimeError("SMART_TUTOR_LEARNER_HASH_KEY is not set, but LangSmith tracing is on")` when no key is set and tracing is on
  - `shared.adapters.tracing.run_metadata(settings: Settings) -> dict[str, str]` → `{"deployment", "chat_model", "embedding_model"}`
  - `shared.adapters.tracing.ingestion_project() -> str` → `f"{langsmith.utils.get_tracer_project()}-ingestion"`
  - `shared.adapters.tracing.LangSmithRunTracing(hasher: LearnerHasher | None, project_name: str, metadata: Mapping[str, str], client: langsmith.Client | None = None)` implementing `RunTracing`
  - `fakes.RecordingClient` (as in today's test: records `create_run`/`update_run` kwargs in `.payloads`), `fakes.FakeRunTracing` (records `(name, user_id, dict(metadata))` in `.runs`)

- [ ] **Step 1: Write the failing tests** — `backend/tests/unit/shared/test_tracing.py`

```python
"""Keyed learner hash and LangSmith run tracing (PRD §10.4): the learner appears only as an HMAC of their user id."""

import json

import langsmith
import pytest
from langchain_core.messages import AIMessage

from fakes import RecordingClient, fake_chat_model
from smart_tutor.shared.adapters.tracing import (
    LangSmithRunTracing,
    LearnerHasher,
    learner_hasher,
    run_metadata,
)
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId


def test_the_hash_is_stable_for_one_learner_and_differs_between_learners() -> None:
    hasher = LearnerHasher("key-one")
    assert hasher(UserId("ada")) == hasher(UserId("ada"))
    assert hasher(UserId("ada")) != hasher(UserId("bob"))
    assert len(hasher(UserId("ada"))) == 64 and "ada" not in hasher(UserId("ada"))


def test_the_hash_changes_when_the_key_changes() -> None:
    assert LearnerHasher("key-one")(UserId("ada")) != LearnerHasher("key-two")(UserId("ada"))


def test_an_empty_key_is_refused() -> None:
    with pytest.raises(ValueError, match="SMART_TUTOR_LEARNER_HASH_KEY"):
        LearnerHasher("")


def test_the_key_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMART_TUTOR_LEARNER_HASH_KEY", "from-env")
    hasher = learner_hasher(Settings())
    assert hasher is not None and hasher(UserId("ada")) == LearnerHasher("from-env")(UserId("ada"))


def test_no_key_is_fine_while_tracing_is_off() -> None:
    with langsmith.tracing_context(enabled=False):
        assert learner_hasher(Settings(learner_hash_key="")) is None


def test_no_key_refuses_to_start_while_tracing_is_on() -> None:
    with langsmith.tracing_context(enabled=True), pytest.raises(RuntimeError, match="SMART_TUTOR_LEARNER_HASH_KEY"):
        learner_hasher(Settings(learner_hash_key=""))


def test_run_metadata_names_the_deployment_and_models() -> None:
    meta = run_metadata(Settings(deployment="on-premise"))
    assert meta == {
        "deployment": "on-premise",
        "chat_model": Settings().models.agent.model_id,
        "embedding_model": Settings().models.embedding.model_id,
    }


def test_a_run_and_its_model_calls_trace_into_the_given_project_with_the_learner_hash() -> None:
    recorder = RecordingClient()
    tracing = LangSmithRunTracing(LearnerHasher("k"), "proj-ingestion", {"deployment": "local"}, client=recorder)
    model = fake_chat_model(AIMessage("A summary."))
    with langsmith.tracing_context(enabled=True), tracing.run("ingest", UserId("user-123"), {"content_id": "c-1"}):
        model.invoke("Describe these pages.")
    created = [p for p in recorder.payloads if p["op"] == "create"]
    root = next(p for p in created if p["name"] == "ingest")
    assert root["session_name"] == "proj-ingestion"
    meta = root["extra"]["metadata"]
    assert meta["content_id"] == "c-1" and meta["deployment"] == "local"
    assert meta["learner_hash"] == LearnerHasher("k")(UserId("user-123"))
    children = [p for p in created if p.get("parent_run_id") is not None]
    assert children and all(p["session_name"] == "proj-ingestion" for p in children)
    assert "user-123" not in json.dumps(recorder.payloads, default=str)
```

If `session_name` is not the kwarg name `create_run` receives in langsmith 0.14, read `RunTree.post`/`_get_dicts_safe` in `.venv/Lib/site-packages/langsmith/run_trees.py` and use the key it sends (it is `session_name` in 0.14). Check the child's parent key the same way.

- [ ] **Step 2: Run the tests to see them fail**

Run: `cd backend && uv run pytest tests/unit/shared/test_tracing.py -q`
Expected: FAIL at import (`smart_tutor.shared.adapters.tracing` / `fakes.RecordingClient` missing).

- [ ] **Step 3: Implement**

`backend/tests/fakes/tracing.py` — move `RecordingClient` from `test_no_token_in_traces.py` verbatim, and add:

```python
class FakeRunTracing(RunTracing):
    """Records each run's name, learner, and metadata."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, UserId, dict[str, str]]] = []

    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> AbstractContextManager[None]:
        self.runs.append((name, user_id, dict(metadata)))
        return nullcontext()
```

Export both from `fakes/__init__.py` (follow its existing `from fakes.x import ...` + `__all__` style), and in `test_no_token_in_traces.py` replace the class with `from fakes import RecordingClient`.

`backend/src/smart_tutor/shared/ports/run_tracing.py`:

```python
"""Groups one unit of work's model calls under a named trace (PRD §10.4)."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext

from smart_tutor.shared.domain.ids import UserId


class RunTracing(ABC):
    @abstractmethod
    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> AbstractContextManager[None]:
        """Model calls made inside trace as children of a run named `name`. The learner appears in it only as a keyed
        hash of `user_id`."""


class NoRunTracing(RunTracing):
    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> AbstractContextManager[None]:
        return nullcontext()
```

`backend/src/smart_tutor/shared/adapters/tracing.py`:

```python
"""LangSmith tracing (PRD §10.4): who a run is for appears only as a keyed hash of the learner's user id, so usage can
be grouped per learner without the trace naming them. Tokens, user ids, and emails never reach a trace (ADR 0007)."""

import hashlib
import hmac
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

import langsmith
from langsmith import utils as ls_utils

from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.ports.run_tracing import RunTracing

KEY_SETTING = "SMART_TUTOR_LEARNER_HASH_KEY"


class LearnerHasher:
    """HMAC-SHA256 of a user id: stable per learner and key, different between learners, changed with the key."""

    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError(f"{KEY_SETTING} is empty")
        self._key = key.encode()

    def __call__(self, user_id: UserId) -> str:
        return hmac.new(self._key, user_id.encode(), hashlib.sha256).hexdigest()


def learner_hasher(settings: Settings) -> LearnerHasher | None:
    """The configured hasher; None when no key is set and tracing is off. Refuses to start without a key while
    tracing is on, so a trace never goes out without its learner hash."""
    key = settings.learner_hash_key.get_secret_value()
    if key:
        return LearnerHasher(key)
    if ls_utils.tracing_is_enabled():
        raise RuntimeError(f"{KEY_SETTING} is not set, but LangSmith tracing is on")
    return None


def run_metadata(settings: Settings) -> dict[str, str]:
    """What every traced run says about where it ran and with which models."""
    return {
        "deployment": settings.deployment,
        "chat_model": settings.models.agent.model_id,
        "embedding_model": settings.models.embedding.model_id,
    }


def ingestion_project() -> str:
    """The worker's own project, beside the ask project, so ask traces stay readable."""
    return f"{ls_utils.get_tracer_project()}-ingestion"


class LangSmithRunTracing(RunTracing):
    def __init__(
        self,
        hasher: LearnerHasher | None,
        project_name: str,
        metadata: Mapping[str, str],
        client: langsmith.Client | None = None,
    ) -> None:
        self._hasher = hasher
        self._project = project_name
        self._metadata = dict(metadata)
        self._client = client  # None: LangSmith's default client; tests pass a recording one

    @contextmanager
    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> Iterator[None]:
        learner = {"learner_hash": self._hasher(user_id)} if self._hasher else {}
        with langsmith.trace(
            name,
            project_name=self._project,
            metadata={**self._metadata, **metadata, **learner},
            client=self._client,
        ):
            yield
```

Check `ls_utils.tracing_is_enabled()` exists with that name in langsmith 0.14 (`grep -n "def tracing_is_enabled" .venv/.../langsmith/utils.py`); it reads the tracing context first, then `LANGSMITH_TRACING`.

`shared/config.py` — after `environment`, add (import `Literal` from `typing`):

```python
    # Where this process runs, for traces (PRD §10.4): local (Compose or host), on-premise, or native-cloud (EKS).
    deployment: Literal["local", "on-premise", "native-cloud"] = "local"
```

and after `keycloak_client_secret`:

```python
    # HMAC key for the learner hash in traces (PRD §10.4). A secret: from Secrets Manager when deployed (#229); required
    # only while LangSmith tracing is on.
    learner_hash_key: SecretStr = SecretStr("")
```

`shared/domain/ids.py` — add:

```python
RunId = NewType("RunId", str)  # an ask's LangSmith root run (UUID); minted by the API, kept with its turn
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/unit/shared/test_tracing.py tests/unit/apps/agent -q`
Expected: PASS.

- [ ] **Step 5: Full checks and commit**

Run the Global Constraints check line. Commit: `Add a keyed learner hash and LangSmith run tracing for traces`.

---

### Task 2: The agent traces each ask as one `ask` run

**Files:**
- Create: `backend/src/smart_tutor/apps/agent/tracing.py`
- Modify: `backend/src/smart_tutor/apps/agent/server.py`
- Test: `backend/tests/unit/apps/agent/test_ask_trace.py` (new), `backend/tests/unit/apps/agent/test_no_token_in_traces.py` (extend), `backend/tests/unit/apps/agent/test_server.py` (startup check, route wiring)

**Interfaces:**
- Consumes: `LearnerHasher`, `learner_hasher`, `run_metadata` (Task 1); `RecordingClient` (fakes).
- Produces:
  - Agent `AskRequest` gains `thread_id: uuid.UUID | None = None` and `run_id: uuid.UUID | None = None` (still `extra="forbid"`).
  - `apps.agent.tracing.AskRun` (frozen dataclass): `run_id: uuid.UUID`, `thread_id: str | None`, `user_id: UserId`, `question: str`, `document_ids: list[str] | None`.
  - `apps.agent.tracing.AskTracing(metadata: Mapping[str, str], hasher: LearnerHasher | None, client: langsmith.Client | None = None)` with a context manager `trace(run: AskRun) -> Iterator[AskTrace]`; `AskTrace.finish(answer: str, decline: str | None, chunks: int) -> None`.
  - `answer_events(graph, body, token, run: AskRun, tracing: AskTracing)`.
  - `create_app(settings=None, verifier=None, graph=None, tracing: AskTracing | None = None)`.

- [ ] **Step 1: Write the failing trace tests** — `backend/tests/unit/apps/agent/test_ask_trace.py`

Drive `answer_events` directly inside `langsmith.tracing_context(enabled=True)` (a `TestClient` runs the app in another thread, where the test's tracing context doesn't reach).

```python
"""PRD §10.4: each ask is one `ask` trace with run metadata; the learner only as a keyed hash."""

import json
import uuid
from typing import Any

import langsmith
from langchain_core.messages import AIMessage

from fakes import FakeRetriever, RecordingClient, fake_chat_model
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.server import AskRequest, answer_events
from smart_tutor.apps.agent.tracing import AskRun, AskTracing
from smart_tutor.shared.adapters.tracing import LearnerHasher
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

RUN_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
THREAD_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
USER = UserId("user-under-test-123")
META = {"deployment": "local", "chat_model": "chat-x", "embedding_model": "embed-y"}
CHUNKS = [
    RetrievedChunk("c1", "d1", "a.pdf", 3, "Attention weighs tokens.", 0.9),
    RetrievedChunk("c2", "d2", "b.pdf", 1, "Other text.", 0.8),
]


async def traced(
    body: AskRequest, chunks: list[RetrievedChunk] = CHUNKS, close_after: int | None = None
) -> tuple[list[dict[str, Any]], list[str]]:
    recorder = RecordingClient()
    tracing = AskTracing(META, LearnerHasher("k"), client=recorder)
    graph = build_graph(lambda token: FakeRetriever(chunks), fake_chat_model(AIMessage("It weighs tokens [1].")))
    run = AskRun(RUN_ID, body.thread_id and str(body.thread_id), USER, body.question, body.document_ids)
    got: list[str] = []
    with langsmith.tracing_context(enabled=True):
        events = answer_events(graph, body, "tok", run, tracing)
        async for event in events:
            got.append(event)
            if close_after is not None and len(got) >= close_after:
                await events.aclose()
                break
    return recorder.payloads, got


def root(payloads: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The ask run's create payload and its final metadata (create merged with the last update)."""
    [create] = [p for p in payloads if p["op"] == "create" and p["name"] == "ask"]
    meta = dict(create["extra"]["metadata"])
    for p in payloads:
        if p["op"] == "update" and str(p.get("run_id")) == str(RUN_ID) and p.get("extra"):
            meta.update(p["extra"].get("metadata", {}))
    return create, meta


async def test_an_answer_traces_as_one_ask_run_with_its_metadata() -> None:
    payloads, _ = await traced(AskRequest(question="What is attention?", thread_id=uuid.UUID(THREAD_ID)))
    create, meta = root(payloads)
    assert str(create["id"]) == str(RUN_ID) and create.get("parent_run_id") is None
    assert create["inputs"]["question"] == "What is attention?"
    assert meta["thread_id"] == THREAD_ID
    assert meta["learner_hash"] == LearnerHasher("k")(USER)
    assert {k: meta[k] for k in META} == META
    assert meta["limited"] is False and meta["decline"] == "none" and meta["chunks"] == 2
    others = [p for p in payloads if p["op"] == "create" and p["name"] != "ask"]
    assert others and all(p.get("parent_run_id") is not None for p in others)  # LangGraph nests under ask


async def test_a_decline_traces_with_its_code_and_no_chunks_given_to_the_model() -> None:
    low = [RetrievedChunk("c1", "d1", "a.pdf", 3, "Unrelated.", 0.01)]
    payloads, _ = await traced(AskRequest(question="Q?", document_ids=["d1"]), chunks=low)
    _, meta = root(payloads)
    assert meta["limited"] is True and meta["decline"] == "limited" and meta["chunks"] == 0


async def test_a_no_documents_decline_traces_its_code() -> None:
    payloads, _ = await traced(AskRequest(question="Q?"), chunks=[])
    assert root(payloads)[1]["decline"] == "no_documents"


async def test_without_a_thread_id_the_run_still_traces() -> None:
    payloads, _ = await traced(AskRequest(question="Q?"))
    assert "thread_id" not in root(payloads)[1]


async def test_a_closed_stream_still_ends_the_ask_run() -> None:
    payloads, got = await traced(AskRequest(question="What is attention?"), close_after=1)
    assert len(got) == 1
    assert any(p["op"] == "update" and str(p.get("run_id")) == str(RUN_ID) for p in payloads)


async def test_the_user_id_never_reaches_the_trace() -> None:
    payloads, _ = await traced(AskRequest(question="What is attention?"))
    assert USER not in json.dumps(payloads, default=str)
```

Adjust the payload keys (`id`, `parent_run_id`, `extra`, `run_id` on update) to what `RecordingClient` actually receives from langsmith 0.14 — print one `recorder.payloads` once to confirm, then fix the helper, not the assertions' intent.

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && uv run pytest tests/unit/apps/agent/test_ask_trace.py -q` — Expected: FAIL at import.

- [ ] **Step 3: Implement `apps/agent/tracing.py`**

```python
"""Each ask is one LangSmith trace named `ask` (PRD §10.4). Its metadata says where and with which models it ran,
for which thread, whether the search was limited to the conversation's documents, and, once done, the decline code
and how many chunks the model was given. The learner appears only as a keyed hash; the token stays in runtime context
(ADR 0007)."""

import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass

import langsmith
from langsmith.run_trees import RunTree

from smart_tutor.shared.adapters.tracing import LearnerHasher
from smart_tutor.shared.domain.ids import UserId

NO_DECLINE = "none"


@dataclass(frozen=True)
class AskRun:
    run_id: uuid.UUID  # the trace's root run; the API keeps it with the turn
    thread_id: str | None
    user_id: UserId  # hashed before it reaches the trace
    question: str
    document_ids: list[str] | None


class AskTrace:
    def __init__(self, run: RunTree) -> None:
        self._run = run

    def finish(self, answer: str, decline: str | None, chunks: int) -> None:
        """What the run ended with: a decline gives the model no chunks."""
        self._run.end(
            outputs={"answer": answer, "decline": decline},
            metadata={"decline": decline or NO_DECLINE, "chunks": 0 if decline else chunks},
        )


class AskTracing:
    def __init__(
        self, metadata: Mapping[str, str], hasher: LearnerHasher | None, client: langsmith.Client | None = None
    ) -> None:
        self._metadata = dict(metadata)
        self._hasher = hasher
        self._client = client  # None: LangSmith's default client; tests pass a recording one

    @contextmanager
    def trace(self, run: AskRun) -> Iterator[AskTrace]:
        metadata: dict[str, object] = {**self._metadata, "limited": run.document_ids is not None}
        if run.thread_id is not None:
            metadata["thread_id"] = run.thread_id
        if self._hasher is not None:
            metadata["learner_hash"] = self._hasher(run.user_id)
        with langsmith.trace(
            "ask",
            run_id=run.run_id,
            inputs={"question": run.question, "document_ids": run.document_ids},
            metadata=metadata,
            client=self._client,
        ) as root:
            yield AskTrace(root)
```

(`RunTree.end(metadata=...)` merges into `extra["metadata"]`, and `trace` patches the run on exit.)

- [ ] **Step 4: Wire `server.py`**

- `AskRequest`: add `thread_id: uuid.UUID | None = None` and `run_id: uuid.UUID | None = None` with a comment: "Set by the API (PRD §10.4): the conversation and the run id it keeps with the turn. Callers without them (evals) still trace, under a fresh run id."
- `answer_events(graph, body, token, run, tracing)`: wrap the whole existing `try/except` in `with tracing.trace(run) as trace:`; keep `answer = ""` and `decline: str | None = None`; append each delta's text to `answer`; set `decline = code` on a decline; after the stream loop and before `yield sse("done", {})`, call `trace.finish(answer, decline, len(chunks))`. In each `except` block, call `trace.fail(code)` with the error event's code (`"unauthenticated"` / `"unavailable"`) before yielding the error event — the blocks swallow the exception, so `langsmith.trace` would otherwise end the run as a success. Keep the existing events byte-identical.
- Add to `AskTrace`:

```python
    def fail(self, code: str) -> None:
        """The run ended with an error event; the learner saw `code`."""
        self._run.end(error=code, metadata={"decline": NO_DECLINE, "chunks": 0})
```

- Add a test to `test_ask_trace.py`: a retriever that raises `RetrievalError` (see `test_server.py` for how it fakes one) → the stream ends with the `error` event as before, and the `ask` run's final update has `error == "unavailable"`.
- The `/ask` route: replace `dependencies=[Depends(current_principal)]` with a `principal: Principal = Depends(current_principal)` parameter (or the existing annotated alias if `bearer.py` has one), build `AskRun(body.run_id or uuid.uuid4(), str(body.thread_id) if body.thread_id else None, principal.user_id, body.question, body.document_ids)`, pass `request.app.state.tracing`.
- `create_app(..., tracing: AskTracing | None = None)`: `app.state.tracing = tracing or AskTracing(run_metadata(settings), hasher)` where `hasher` is `LearnerHasher(key)` when `settings.learner_hash_key` is set, else None. In the lifespan's real-startup branch (verifier is None), call `learner_hasher(settings)` before anything else so a process with tracing on and no key refuses to start (and use its result for `app.state.tracing` when `tracing` wasn't injected).
- Update the module docstring: the request may carry `thread_id` and `run_id`; each ask is traced as `ask` (PRD §10.4).

- [ ] **Step 5: Extend the no-token test** — `test_no_token_in_traces.py`

Add a server-level test that runs `answer_events` with a principal-shaped run and asserts the token, the raw user id, and the email are absent from every recorded payload, with a positive control:

```python
USER_ID = "user-id-under-test-42"
EMAIL = "ada.lovelace@example.com"


async def ask_payloads(question: str) -> str:
    recorder = RecordingClient()
    tracing = AskTracing({"deployment": "local"}, LearnerHasher("k"), client=recorder)
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("It weighs tokens [1].")))
    body = AskRequest(question=question)
    run = AskRun(uuid.uuid4(), None, UserId(USER_ID), body.question, None)
    with langsmith.tracing_context(enabled=True):
        async for _ in answer_events(graph, body, TOKEN, run, tracing):
            pass
    assert recorder.payloads
    return json.dumps(recorder.payloads, default=str)


async def test_the_ask_trace_holds_no_token_user_id_or_email() -> None:
    traces = await ask_payloads("What is attention?")
    assert "What is attention?" in traces
    for secret in (TOKEN, USER_ID, EMAIL):
        assert secret not in traces


async def test_positive_control_a_user_id_in_the_question_is_caught() -> None:
    assert USER_ID in await ask_payloads(f"What is attention? {USER_ID} {EMAIL}")
```

(The agent never holds the email; `Principal.name` is not passed to tracing. The test pins that.)

- [ ] **Step 6: Startup and wiring tests in `test_server.py`**

```python
def test_startup_refuses_tracing_without_a_learner_hash_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("smart_tutor.shared.adapters.tracing.ls_utils.tracing_is_enabled", lambda *a: True)
    with (
        pytest.raises(RuntimeError, match="SMART_TUTOR_LEARNER_HASH_KEY"),
        TestClient(create_app(Settings(keycloak_client_secret="s", learner_hash_key=""))),
    ):
        pass
```

and a wiring test using a recording subclass of `AskTracing` whose `trace` records the `AskRun` and yields an object with a no-op `finish`, asserting that a request with `run_id`/`thread_id` reaches it as `AskRun(run_id, thread_id, UserId("ada"), ...)` and that a request without them gets a fresh UUID and `thread_id=None`. Also assert an unknown body field is still a 422.

- [ ] **Step 7: Run and commit**

Run: `cd backend && uv run pytest tests/unit/apps/agent -q`, then the full check line. Commit: `Trace each ask as one run with metadata and a keyed learner hash`.

---

### Task 3: Turns keep their run id; a new thread's id can be given

**Files:**
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0015_thread_turn_run_id.py`
- Modify: `backend/src/smart_tutor/tutoring/domain/turn.py`, `backend/src/smart_tutor/tutoring/application/conversation_service.py`, `backend/src/smart_tutor/tutoring/adapters/sql_threads.py`, `backend/tests/fakes/tutoring.py` (InMemoryThreads, if it copies fields), `backend/src/smart_tutor/tutoring/README.md` (if it lists turn fields)
- Test: `backend/tests/unit/tutoring/test_conversation_service.py`, `backend/tests/integration/tutoring/test_sql_threads.py`, `backend/tests/integration/shared/test_migrations.py` (if it lists heads)

**Interfaces:**
- Consumes: `RunId` (Task 1).
- Produces:
  - `Turn.run_id: RunId | None = None` (last field), `AnsweredTurn.run_id: RunId | None = None` (last field), `TurnView.run_id: RunId | None = None` (last field)
  - `ConversationService.start_thread(user_id, question=None, document_id=None, *, thread_id: ThreadId | None = None)` — uses the given id, else a new UUID
  - Column `thread_turns.run_id uuid NULL`

- [ ] **Step 1: Failing unit tests** (in `test_conversation_service.py`, using its existing helpers):

```python
def test_a_thread_can_start_with_a_given_id() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    thread = service(library, threads, FixedClock()).start_thread(LEARNER, "Q?", thread_id=ThreadId("7d1f..."))
    assert thread.thread_id == "7d1f..."


def test_a_kept_turn_keeps_its_run_id_and_shows_it() -> None:
    ...start a thread, record_turn(tid, LEARNER, AnsweredTurn("Q?", "A.", run_id=RunId(RUN))) ...
    assert [t.run_id for t in svc.turns(tid, LEARNER)] == [RUN]


def test_a_turn_without_a_run_id_shows_none() -> None:
    ...record_turn with AnsweredTurn("Q?", "A.") ...
    assert [t.run_id for t in svc.turns(tid, LEARNER)] == [None]
```

Use a real UUID string for the given thread id (e.g. `str(uuid.uuid4())`) and match names to the file's existing helpers (`service`, `LEARNER`, `FixedClock`).

- [ ] **Step 2: Run to fail** — `uv run pytest tests/unit/tutoring -q`.

- [ ] **Step 3: Implement**

- `turn.py`: add `run_id: RunId | None = None` as the last field of `Turn`, `AnsweredTurn`, and `TurnView`, each commented "the ask's LangSmith root run (PRD §10.4); None for turns kept before it was recorded".
- `conversation_service.py`: `start_thread(..., *, thread_id: ThreadId | None = None)` → `Thread.start(thread_id or ThreadId(str(uuid.uuid4())), ...)`; docstring: "The API may give the id, minted before the agent call so the first turn's trace carries it." `record_turn` passes `turn.run_id` to `Turn(...)`; `turns` passes `t.run_id` to `TurnView(...)`.
- Migration `0015` (revises `0014`, docstring: "The ask's LangSmith run id with its turn (PRD §10.4, #221), so a rating can attach to its trace (#227). Nullable: turns kept before it have none."):

```python
def upgrade() -> None:
    op.add_column("thread_turns", sa.Column("run_id", sa.Uuid(as_uuid=False)))


def downgrade() -> None:
    op.drop_column("thread_turns", "run_id")
```

- `sql_threads.py`: add `Column("run_id", Uuid(as_uuid=False))` to the `thread_turns` Table, write `run_id=turn.run_id` in `add_turn`, read `RunId(row.run_id) if row.run_id else None` in `_turn`.
- Integration test in `test_sql_threads.py`: a turn added with a run id reads back with it; one without reads `None` (follow the file's existing turn test style; marked `integration`).

- [ ] **Step 4: Run** `uv run pytest tests/unit/tutoring -q`; if Compose is up (`docker compose ps`), `uv run --env-file ../.env alembic`-backed `make migrate` then `uv run pytest -m integration tests/integration/tutoring tests/integration/shared -q`. If Compose isn't running, say so in the report rather than skipping silently.

- [ ] **Step 5: Full checks, commit** — `Keep each turn's run id and let a new thread's id be given`.

---

### Task 4: The API mints the run id, sends it with the thread id, and returns it with turns

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/agent_client.py`, `backend/src/smart_tutor/apps/api/routes/threads.py`
- Regenerate: `web/src/api/` (`make api-client`, or its one-line command from the `Makefile`), the OpenAPI snapshot used by `tests/unit/apps/api/test_openapi_snapshot.py` (see that test for how it is refreshed)
- Test: `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py` (only if it asserts the exact turn shape)

**Interfaces:**
- Consumes: `RunId`, `AnsweredTurn.run_id`, `TurnView.run_id`, `start_thread(..., thread_id=)` (Task 3); agent `AskRequest.thread_id/run_id` (Task 2).
- Produces: `AgentClient.open_answer(access_token, question, document_ids=None, *, thread_id: str | None = None, run_id: str | None = None)` sending `thread_id`/`run_id` in the JSON body when given; `TurnResponse.run_id: str | None`.

- [ ] **Step 1: Failing tests** in `test_thread_routes.py` (reuse `setup`, `recording`, `QUESTION`, `AUTH`):

```python
def test_a_new_thread_sends_its_thread_id_and_a_fresh_run_id_to_the_agent_and_keeps_the_run_id() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen))
    client.post("/threads", json=QUESTION, headers=AUTH)
    [thread] = threads.threads.values()
    body = json.loads(seen[0].content)
    assert body["thread_id"] == thread.thread_id
    run_id = str(uuid.UUID(body["run_id"]))
    [turn] = client.get(f"/threads/{thread.thread_id}/turns", headers=AUTH).json()
    assert turn["run_id"] == run_id


def test_each_question_in_a_thread_gets_its_own_run_id() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen))
    client.post("/threads", json=QUESTION, headers=AUTH)
    [thread] = threads.threads.values()
    client.post(f"/threads/{thread.thread_id}/questions", json=QUESTION, headers=AUTH)
    first, second = (json.loads(r.content) for r in seen)
    assert second["thread_id"] == thread.thread_id and first["run_id"] != second["run_id"]
    turns = client.get(f"/threads/{thread.thread_id}/turns", headers=AUTH).json()
    assert [t["run_id"] for t in turns] == [first["run_id"], second["run_id"]]


def test_a_declined_turn_keeps_its_run_id_too() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen, sse_no_documents), ready_document=False)
    client.post("/threads", json=QUESTION, headers=AUTH)
    [thread] = threads.threads.values()
    [turn] = client.get(f"/threads/{thread.thread_id}/turns", headers=AUTH).json()
    assert turn["run_id"] == json.loads(seen[0].content)["run_id"]
```

Also a test that a turn recorded without a run id (insert directly via `threads` fake with `AnsweredTurn` lacking it) lists `"run_id": None`.

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement**

- `agent_client.open_answer`: add keyword-only `thread_id`/`run_id`; put them in the body when not None; docstring: "`thread_id` and `run_id` name the ask's trace (PRD §10.4); the run id is kept with the turn."
- `routes/threads.py`:
  - `_open(agent, token, question, document_ids, thread_id, run_id)` forwards them.
  - `ask_in_new_thread`: before `_open`, `new_id = ThreadId(str(uuid.uuid4()))` and `run_id = RunId(str(uuid.uuid4()))`; `_open(..., thread_id=new_id, run_id=run_id)`; `start()` calls `conversations.start_thread(principal.user_id, body.question, document_id, thread_id=new_id)`.
  - `ask_in_thread`: `run_id = RunId(str(uuid.uuid4()))`, `_open(..., thread_id=tid, run_id=run_id)`.
  - `_recorder(conversations, user_id, question, thread_id, run_id)` → `AnsweredTurn(question, seen.answer, seen.citations, seen.decline, seen.document_ids, run_id)`.
  - `TurnResponse.run_id: str | None` with a docstring/Field description "The ask's LangSmith run id, for attaching a rating (#227); null for turns kept before it was recorded."; `_turn_response` sets it.
  - Module docstring: one clause saying each ask gets a run id that names its trace and is kept with the turn.
- Regenerate the web client and the OpenAPI snapshot; run `cd web && npm ci && npm run build`.

- [ ] **Step 4: Run** `uv run pytest tests/unit/apps/api tests/isolation -q` and the full check line; `cd web && npm run build`.

- [ ] **Step 5: Commit** — `Send each ask's run and thread id to the agent and keep the run id with the turn`.

---

### Task 5: The worker traces each content's processing into its own project

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/application/ingestion_service.py` (`ProcessingTools.tracing`, wrap processing), `backend/src/smart_tutor/apps/worker/main.py`, `backend/tests/fakes/processing.py` (if it needs the new field), `backend/src/smart_tutor/knowledge/README.md` (one line: processing runs inside a `RunTracing` run)
- Test: `backend/tests/unit/knowledge/` ingestion service test file (find with `grep -rln "process_content" backend/tests/unit/knowledge`)

**Interfaces:**
- Consumes: `RunTracing`, `NoRunTracing` (shared.ports.run_tracing), `LangSmithRunTracing`, `learner_hasher`, `run_metadata`, `ingestion_project` (shared.adapters.tracing), `FakeRunTracing` (fakes).
- Produces: `ProcessingTools.tracing: RunTracing = field(default_factory=NoRunTracing)` (last field).

- [ ] **Step 1: Failing test**

```python
def test_processing_a_content_runs_inside_one_ingest_run_for_its_owner() -> None:
    tracing = FakeRunTracing()
    # build the service as the file's other process_content tests do, with ProcessingTools(..., tracing=tracing)
    ...
    ingestion.process_content(content_id)
    assert tracing.runs == [("ingest", owner_id, {"content_id": content_id})]


def test_a_content_no_longer_processing_opens_no_run() -> None:
    # same setup, content already ready
    assert tracing.runs == []
```

To prove the describer's model call happens inside the run, give `FakeRunTracing` a flag the fake describer model can't see — simplest: make the test's `FakeRunTracing.run` return a context manager that sets `tracing.active = True` on enter and False on exit, and have the test's chat model (a `fake_chat_model` wrapped in a tiny `BaseChatModel` callback, or a `RunnableLambda`) record `tracing.active` when invoked. If that adds more than ~15 lines, assert ordering via the fake's recorded run and the describer having been called, and rely on Task 1's adapter test for nesting.

- [ ] **Step 2: Run to fail.**

- [ ] **Step 3: Implement**

- `ProcessingTools`: add `tracing: RunTracing = field(default_factory=NoRunTracing)` with comment "groups a content's model calls in one trace (PRD §10.4)"; import `field` from dataclasses and the port from `smart_tutor.shared.ports.run_tracing`.
- `process_content`: keep the locked read and the not-processing early return; then:

```python
        with self._tools.tracing.run("ingest", content.owner_id, {"content_id": content_id}):
            return self._process(content)
```

  and move the rest of the current body into `def _process(self, content: Content) -> ContentState | None:` unchanged (use the content's own `content_id`).
- `apps/worker/main.py`: build `tracing = LangSmithRunTracing(learner_hasher(settings), ingestion_project(), run_metadata(settings))` near the top of `main()` (so a missing key with tracing on stops startup before polling) and pass `tracing=tracing` to `ProcessingTools`. Update the module docstring with one sentence: each content's processing is traced as `ingest` into `<LANGSMITH_PROJECT>-ingestion`, with the content id and learner hash.

- [ ] **Step 4: Run** `uv run pytest tests/unit/knowledge tests/unit/apps/worker -q` and the full check line (lint-imports proves `knowledge.application` uses only the port).

- [ ] **Step 5: Commit** — `Trace each content's processing into the ingestion project`.

---

### Task 6: Configuration, deployment kind, and the PRD

**Files:**
- Modify: `.env.example`, `compose.yaml` (agent and worker services), `deploy/on-premise/compose.yaml` (agent and worker: `SMART_TUTOR_DEPLOYMENT: on-premise`), `deploy/helm/smart-tutor/charts/agent/templates/deployment.yaml` and `.../worker/templates/deployment.yaml` (`SMART_TUTOR_DEPLOYMENT` = `native-cloud`), `infra/tests/test_helm_chart.py` (assert it on agent and worker), `sdd/prd.md`, `AGENTS.md` (PRD version in the sources table), `CONTEXT.md` (term "Learner hash", if the file has a glossary of such terms)

- [ ] **Step 1: Env and Compose**

`.env.example`, under the LangSmith block:

```
# Learner hash in traces (PRD §10.4): HMAC key; any value locally, a Secrets Manager secret when deployed (#229).
SMART_TUTOR_LEARNER_HASH_KEY=local-learner-hash-key
```

`compose.yaml`: if the agent and worker services read `.env` via `env_file`, nothing more; otherwise add `SMART_TUTOR_LEARNER_HASH_KEY: ${SMART_TUTOR_LEARNER_HASH_KEY:-local-learner-hash-key}` to agent and worker, matching how the file passes `LANGSMITH_*`.

- [ ] **Step 2: Deployment kind** — add `SMART_TUTOR_DEPLOYMENT: on-premise` after `SMART_TUTOR_ENVIRONMENT: prod` for `agent` and `worker` in `deploy/on-premise/compose.yaml`; add

```yaml
            - name: SMART_TUTOR_DEPLOYMENT
              value: native-cloud
```

after `SMART_TUTOR_ENVIRONMENT` in the Helm agent and worker templates. Add an assertion to the existing agent and worker tests in `infra/tests/test_helm_chart.py` (`env["SMART_TUTOR_DEPLOYMENT"] == "native-cloud"`, following how those tests read `env`). Run `cd infra && uv run pytest -q` and `helm lint deploy/helm/smart-tutor` (skip helm lint with a note if `helm` isn't installed).

- [ ] **Step 3: PRD** — `sdd/prd.md`:
  - Status line `Draft v2.38` → `Draft v2.39`.
  - New row above "Changes from v2.37": `| **Changes from v2.38** | Ask tracing (#221, §10.4): each ask is one LangSmith trace named \`ask\`; the API mints its run id (and a new conversation's thread id) before calling the agent and keeps the run id with the turn (\`thread_turns.run_id\`, returned by \`list_thread_turns\`). Metadata: thread id, deployment (local, on-premise, native-cloud), chat and embedding model ids, decline code or none, chunks given to the model, and whether the search was limited to the conversation's documents. The learner appears only as a keyed hash (HMAC-SHA256 of the user id; key \`SMART_TUTOR_LEARNER_HASH_KEY\`, a secret); no user id, email, or token in inputs, outputs, metadata, or tags. The worker traces each content's processing as \`ingest\` (content id, learner hash) into its own project. |`
  - §10.4: after "Trace every run;" insert a sentence: "Each ask is one `ask` trace whose run id is kept with its turn; traces carry the thread id, deployment, model ids, decline code, chunks given to the model, and whether the search was limited, and name the learner only by a keyed hash of their user id — never the user id, email, or token. The worker's processing traces into its own project with the content id and learner hash."
  - §9.4 Thread turn row: add `run_id` (the ask's LangSmith run, nullable for older turns) to the field list.
- `AGENTS.md`: sources table PRD version → `v2.39`.

- [ ] **Step 4: Commit** — `Document ask tracing in the PRD and set each deployment's kind`.

---

## Finish

- Whole-branch review (superpowers `requesting-code-review`), then the full check line, `cd web && npm run build`, `cd infra && uv run pytest`.
- Push the branch and open a PR into `main` titled "Trace each ask as one run with metadata and a keyed learner hash (#221)", body: what changed, the decisions above (turn id = run id; key required only while tracing is on; deployment provisioning is #229), the checks run, and `Closes #221`.

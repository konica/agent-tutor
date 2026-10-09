# Conversations Have No Subjects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every question searches all of the learner's ready, non-archived documents; threads, the agent, MCP search, the API, the web chat, settings and infra no longer know about thread subjects or subject detection (issue #121).

**Architecture:** Delete detection end to end. MCP `search(query, k)` filters only by `can_read` + ready + not archived. The ask graph becomes `search → answer`. `Thread` loses `subject_ids` (migration 0007 drops the column). The API starts the thread when the agent's first event is not an `error`, and its `thread` event carries only `thread_id`. The web chat decides "Upload a document first" from the learner's documents instead of their subjects.

**Tech Stack:** Python 3.13, FastAPI, LangGraph, MCP 2.x, SQLAlchemy + Alembic, pgvector; React + TypeScript + Vite (vitest); AWS CDK (Python); LocalStack.

**Spec:** GitHub issue #121; PRD `sdd/prd.md` v2.23 §8 US-3/US-4, §9.2 (ask path), §9.3 step 4, Q55. The PRD already describes this behavior: **no PRD change**.

## Global Constraints

- Read `AGENTS.md` and `backend/AGENTS.md`; module READMEs are updated in the same task that changes the module.
- Backend checks (from `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`.
- Web checks (from `web/`): `npm run build` and `npx vitest run`.
- Infra checks (from `infra/`): `uv run pytest`.
- Windows Git Bash: `make` may be missing; run the Makefile target's one-line command directly.
- Commit subjects in the imperative mood; body says why; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Acceptance grep must end empty of subject-detection meaning: `grep -rni "detect" backend/src web/src` (matches unrelated to subjects, e.g. the browser's duplicate check, are fine).
- Copy for the empty chat (prototype `design-v0.10`, `chat-new`): heading "Ask about your documents", text "I answer only from the documents in your Library and show the page each answer came from. There's nothing to choose first: just ask."
- A learner with no ready, non-archived documents gets 409 "Upload a document first" from `POST /threads` and the web shows the `chat-no-documents` empty state (unchanged copy).

## Review Focus

1. Agent's first event is `error` (e.g. MCP refused the token): relay it as-is and start **no** thread — test in Task 2.
2. Agent stream ends or drops before its first complete event: one well-formed `unavailable` error event, no thread — test in Task 2.
3. A learner whose only ready document is archived: `POST /threads` is 409 and web shows "Upload a document first" — tests in Task 2 (`has_ready_documents`) and Task 3 (documents list with only non-ready docs).
4. Two learners sharing a subject: MCP search never returns the other's chunks — isolation test in Task 1.
5. The web documents load fails: the page explains it ("Your documents couldn't be loaded. Reload the page to try again.") rather than showing a false upload prompt; a session expiry during load renders nothing — test in Task 3.

---

### Task 1: Search all ready documents; the agent graph is search → answer

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/domain/search.py` (drop `ChunkHit.subject_ids`)
- Modify: `backend/src/smart_tutor/knowledge/domain/document.py:85-92` (`searchable_by(user_id)`)
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py` (`ChunkRepository.search(user_id, embedding, k)`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py:305-360`
- Modify: `backend/src/smart_tutor/knowledge/application/search_service.py`, `knowledge/application/__init__.py` (drop `MAX_SEARCH_SUBJECTS`), `knowledge/README.md`
- Modify: `backend/src/smart_tutor/apps/mcp_server/server.py` (tool `search(query, k=5)`; `ChunkResult` without `subject_ids`)
- Modify: `backend/src/smart_tutor/tutoring/ports/retriever.py`, `tutoring/adapters/mcp_retriever.py`, `tutoring/domain/retrieved_chunk.py` (drop `subject_ids`)
- Delete: `tutoring/domain/detection.py`, `tutoring/application/subject_detector.py`, `tutoring/application/detection_settings.py`, `apps/agent/nodes/resolve_subjects.py`
- Modify: `tutoring/application/__init__.py`, `tutoring/application/answer.py` (prompt without subjects), `apps/agent/graph.py`, `apps/agent/state.py`, `apps/agent/server.py`, `apps/agent/nodes/search.py`, `apps/agent/nodes/answer.py`, `apps/agent/nodes/__init__.py`, `apps/api/agent_client.py` (body `{"question"}` only), `shared/config.py` (drop the three `*_param` detection settings)
- Tests: `backend/tests/fakes/knowledge.py`, `fakes/tutoring.py`; `tests/unit/knowledge/test_search_service.py`, `test_domain.py`; `tests/integration/knowledge/test_sql_library.py`; `tests/unit/apps/mcp_server/test_server.py`; `tests/unit/tutoring/test_mcp_retriever.py`; `tests/unit/apps/agent/test_graph.py`, `test_server.py`, `test_no_token_in_traces.py`; any answer-prompt test; `tests/isolation/test_search.py`. Delete `tests/unit/tutoring/test_detection_policy.py`, `test_detection_settings.py`, `test_subject_detector.py`, `tests/isolation/test_detection.py`.

**Interfaces:**
- Produces: `SearchService.search(user_id: UserId, query: str, k: int = 5) -> list[ChunkHit]`; `ChunkRepository.search(user_id, embedding: list[float], k: int) -> list[ChunkHit]`; `Document.searchable_by(user_id: UserId) -> bool`; MCP tool `search(query: str, k: int = 5)`; `Retriever.search(query: str, k: int = 5) -> list[RetrievedChunk]`; `RetrievedChunk(chunk_id, document_title, page, text, score)`; `answer_messages(question: str, chunks) -> list[BaseMessage]`; `build_graph(retriever_for, model) -> AskGraph`; `AskState` keys `question, chunks, answer, citations`; agent `POST /ask` body `{"question": str}` (`extra="forbid"`); agent SSE: `delta*`, `citations`, `done` | `error` — **no `subjects` event**; `AgentClient.open_answer(access_token, question) -> AgentAnswer`.

- [ ] **Step 1: Rewrite the isolation test first (fails to run against the old tool signature)**

`backend/tests/isolation/test_search.py`: keep `world()` / `search_as()`; make B and A share a subject explicitly, call the tool without `subject_ids`, and delete `test_a_hit_names_only_the_subjects_asked_for`:

```python
def world() -> tuple[InMemoryLibrary, FakeTokenVerifier, str]:
    library = InMemoryLibrary()
    a_doc = ingest_ready(library, "learner-a", A_TEXT, subject_ids=[GENERAL_SUBJECT_ID])
    ingest_ready(library, "learner-b", B_TEXT, subject_ids=[GENERAL_SUBJECT_ID])
    ...

async def test_b_never_gets_as_chunks_even_with_the_same_subjects() -> None:
    library, verifier, a_doc = world()
    result = await search_as(library, verifier, "token-b", query=A_TEXT)
    assert not result.is_error
    chunks = result.structured_content["chunks"]
    assert chunks and all(c["text"] == B_TEXT for c in chunks)
    raw = json.dumps(result.structured_content)
    assert A_TEXT not in raw and a_doc not in raw

async def test_a_user_id_argument_changes_nothing() -> None:
    ...  # same as today without subject_ids=...

async def test_search_covers_documents_in_any_subject() -> None:
    library, verifier, _ = world()
    other = SubjectId("00000000-0000-4000-8000-0000000000b2")
    ingest_ready(library, "learner-a", "Attention scales with heads.", subject_ids=[other])
    result = await search_as(library, verifier, "token-a", query="Attention scales with heads.", k=2)
    assert {c["text"] for c in result.structured_content["chunks"]} == {"Attention scales with heads.", A_TEXT}
    assert all("subject_ids" not in c for c in result.structured_content["chunks"])
```

Delete `tests/isolation/test_detection.py` (its guarantee is now covered above).

- [ ] **Step 2: Run it — expect failures** (`subject_ids` is a required tool argument)

Run: `cd backend && uv run pytest tests/isolation/test_search.py -q`

- [ ] **Step 3: Knowledge search without subjects**

`Document.searchable_by`:

```python
    def searchable_by(self, user_id: UserId) -> bool:
        """`can_read` plus search's own filter: ready and not archived (PRD §9.3 step 4)."""
        return self.can_be_read_by(user_id) and self.state is DocumentState.READY and not self.archived
```

`SearchService.search(user_id, query, k=5)`: keep the query and `k` checks, delete `MAX_SUBJECTS` and the subject validation, call `tx.chunks.search(user_id, embedding, k)`. Remove `MAX_SEARCH_SUBJECTS` from `knowledge/application/__init__.py`.

`_Chunks.search` in `sql_library.py`: delete `requested`, `hit_subjects`, `in_subjects` and the `subject_ids` column; the `where` is `readable_by(user_id)`, ready, not archived. `ChunkHit` loses its last field. Fake `InMemoryLibrary` chunk search in `tests/fakes/knowledge.py` mirrors it (`d.searchable_by(user_id)`). Drop now-unused imports (`func` only if unused elsewhere). Update the `ChunkRepository.search` docstring: "`can_read` in SQL: chunks of the caller's ready, non-archived documents."

MCP tool:

```python
    @mcp.tool(name="search")
    async def search_tool(query: str, k: int = 5) -> SearchResponse:
        """Chunks of the caller's ready, non-archived documents, nearest first."""
        ...
            hits = await asyncio.to_thread(search.search, UserId(token.subject), query, k)
```

and remove `subject_ids` from `ChunkResult` and the `SubjectId` import.

Update `tests/unit/knowledge/test_search_service.py` (delete the subject-count / UUID tests; add one asserting an archived document's chunks and a document in another subject are excluded/included as the filter says), `test_domain.py` (`searchable_by` tests take only `user_id`), `tests/integration/knowledge/test_sql_library.py` search tests, and `tests/unit/apps/mcp_server/test_server.py`.

- [ ] **Step 4: Retriever and agent without detection**

`Retriever.search(self, query: str, k: int = 5)`; `McpRetriever` calls `client.call_tool("search", {"query": query, "k": k})` and builds `RetrievedChunk(c["chunk_id"], c["document_title"], c["page"], c["text"], c["score"])`. `RetrievedChunk` drops `subject_ids`. `FakeRetriever.calls: list[tuple[str, int]]`.

Delete the detection files listed above; `tutoring/application/__init__.py` drops `DETECTION_K`, `Detection`, `DetectionPolicy`, `SubjectDetector`, `load_detection_policy` (Task 2 removes `ThreadSubjectsError`).

`answer.py` system prompt first sentence: `"You are Smart Tutor. You answer a learner's question using only chunks of their own documents."`; `answer_messages(question, chunks)` with `SystemMessage(_SYSTEM)`.

`graph.py`:

```python
"""The ask graph (PRD §9.2): search → answer. Single turn, no checkpointer (#31)."""
...
def build_graph(retriever_for: Callable[[str], Retriever], model: BaseChatModel) -> AskGraph:
    return (
        StateGraph(AskState, context_schema=AgentContext)
        .add_node("search", search_node(retriever_for))
        .add_node("answer", answer_node(model))
        .add_edge(START, "search")
        .add_edge("search", "answer")
        .add_edge("answer", END)
        .compile()
    )
```

`state.py` `AskState`: `question`, `chunks`, `answer`, `citations`. `search.py` docstring "the learner's ready documents, k = 5"; `chunks = await retriever.search(state["question"], K)`. `answer.py` node: `answer_messages(state["question"], chunks)`. `nodes/__init__.py` docstring: "Graph nodes: search, answer. Each calls an application service."

`server.py`: module docstring events become `delta` {"text"} …, `citations`, `done`; or `error` (may come first). `AskRequest` keeps only `question` (`extra="forbid"`); delete `SubjectIn`, the validator, `MAX_SEARCH_SUBJECTS`, the `subjects` branch in `answer_events`, the SSM/`load_detection_policy` lifespan code (`build_graph(lambda token: McpRetriever(settings.mcp_url, token), model)`), and unused imports (`SsmParameterStore`, `ssm_client`, `field_validator`).

`shared/config.py`: delete `detect_threshold_param`, `detect_margin_param`, `multi_margin_param` and their comment.

`apps/api/agent_client.py`:

```python
    async def open_answer(self, access_token: str, question: str) -> AgentAnswer:
        """Ask the agent; it searches all of the learner's ready documents with their token."""
        request = self._http.build_request(
            "POST", self._url, json={"question": question}, headers={"Authorization": f"Bearer {access_token}"}
        )
```

Make `apps/api/routes/threads.py` compile for now by calling `agent.open_answer(token, body.question)` and dropping the `names`/`named` lookup (Task 2 rewrites the relay; keep its `subjects` handling until then — the route's unit tests that assert `learner_subjects` in the agent body get updated here to assert `{"question": ...}`).

Update agent tests: `test_graph.py` (no policy; graph nodes are `search`, `answer`; retriever called with `(question, 5)`), `test_server.py` (request body `{"question": "..."}`; a `learner_subjects` field is 422; no `subjects` event; events start with `delta` or `error`), `test_no_token_in_traces.py`, `tests/unit/tutoring/test_mcp_retriever.py` (tool args `{"query", "k"}`), and the answer-prompt tests (`grep -rn answer_messages backend/tests`).

- [ ] **Step 5: Run the backend checks** (all five; fix until green)

- [ ] **Step 6: Commit**

```bash
git add -A backend
git commit -m "Search all of the learner's ready documents; drop subject detection" -m "Conversations have no subjects (PRD v2.23 §9.2, Q55): MCP search filters only by can_read, ready and not archived, and the ask graph is search → answer."
```

---

### Task 2: Threads without subjects; the API starts the thread on the agent's first event

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/domain/thread.py`, `tutoring/domain/errors.py` (delete `ThreadSubjectsError`), `tutoring/application/__init__.py`, `tutoring/application/conversation_service.py`, `tutoring/adapters/sql_threads.py`, `tutoring/__init__.py`, `tutoring/README.md`
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py` (add `has_ready_documents`), `knowledge/README.md`
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0007_threads_without_subjects.py`
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py`
- Modify: `backend/AGENTS.md` (the "business rule" example names `Thread.add_subject()`; use `Document.set_subjects()`, `Content.retry()`)
- Regenerate: `web/src/api/` (`cd web && npm run api-client` or the Makefile `api-client` command) — the `thread` event is documented only in prose, so the diff may be empty; run it anyway.
- Tests: `tests/unit/tutoring/test_thread.py`, `test_conversation_service.py`, `tests/unit/knowledge/test_document_service.py`, `tests/integration/tutoring/test_sql_threads.py`, `tests/unit/apps/api/test_thread_routes.py`, `tests/isolation/test_threads.py`

**Interfaces:**
- Consumes (Task 1): `AgentClient.open_answer(access_token, question)`; the agent stream has no `subjects` event.
- Produces: `Thread(thread_id, user_id, created_at, status=ACTIVE, title=None, last_learner_message_at=None)`; `Thread.start(thread_id, user_id, now)`; `DocumentService.has_ready_documents(user_id) -> bool`; `ConversationService.require_documents(user_id) -> None` (raises `NoDocumentsError("Upload a document first")`); `ConversationService.start_thread(user_id) -> Thread`; API SSE `thread` event data `{"thread_id": str}`.

- [ ] **Step 1: Failing tests for the domain and service**

`test_thread.py`: replace the subject tests with

```python
def test_a_new_thread_belongs_to_its_learner_and_records_the_first_question() -> None:
    now = datetime(2026, 10, 9, tzinfo=UTC)
    thread = Thread.start(ThreadId("t1"), UserId("ada"), now)
    assert thread.is_owned_by(UserId("ada")) and not thread.is_owned_by(UserId("bob"))
    assert thread.created_at == thread.last_learner_message_at == now
    assert thread.status is ThreadStatus.ACTIVE
```

`test_document_service.py`:

```python
def test_has_ready_documents_ignores_archived_and_unfinished_documents() -> None:
    # a learner with one processing, one awaiting_subjects and one archived ready document → False;
    # after another ready, non-archived document → True; another learner's ready document never counts.
```

(write it with the existing helpers in that file — `ingest_ready`, archive via `DocumentService.archive` or the domain `archive()` as the file already does.)

`test_conversation_service.py`: `start_thread(user_id)` persists a thread owned by the learner; with no ready documents `require_documents` and `start_thread` raise `NoDocumentsError`.

- [ ] **Step 2: Run them — expect failures**

Run: `cd backend && uv run pytest tests/unit/tutoring tests/unit/knowledge/test_document_service.py -q`

- [ ] **Step 3: Implement domain, service, repository, migration**

`thread.py`:

```python
"""One conversation (PRD §9.4 Thread). It has no subjects; its documents used are only ever added (US-4b)."""
...
@dataclass
class Thread:
    thread_id: ThreadId
    user_id: UserId
    created_at: datetime
    status: ThreadStatus = ThreadStatus.ACTIVE
    title: str | None = None
    last_learner_message_at: datetime | None = None

    @classmethod
    def start(cls, thread_id: ThreadId, user_id: UserId, now: datetime) -> "Thread":
        """A new thread with its first question asked now."""
        return cls(thread_id, user_id, now, last_learner_message_at=now)

    def is_owned_by(self, user_id: UserId) -> bool:
        return self.user_id == user_id
```

`DocumentService`:

```python
    def has_ready_documents(self, user_id: UserId) -> bool:
        """Whether the learner has a ready, non-archived document to answer from (PRD §8 US-3)."""
        with self._uow() as tx:
            documents = tx.documents.list_readable_by(user_id)
        return any(d.state is DocumentState.READY for d in documents)
```

(`list_readable_by` already excludes archived documents — confirm in `sql_library.py` and the fake; if not, also check `not d.archived`.)

`ConversationService`:

```python
"""Start a thread (PRD §8 US-3): it answers from all of the learner's ready documents."""
...
    def require_documents(self, user_id: UserId) -> None:
        """No ready, non-archived document → "Upload a document first"."""
        if not self._documents.has_ready_documents(user_id):
            raise NoDocumentsError("Upload a document first")

    def start_thread(self, user_id: UserId) -> Thread:
        """A new thread owned by the learner, persisted."""
        self.require_documents(user_id)
        thread = Thread.start(ThreadId(str(uuid.uuid4())), user_id, self._clock.now())
        self._threads.add(thread)
        return thread
```

`sql_threads.py`: drop the `subject_ids` column, `ARRAY`/`SubjectId` imports, and the field in `_thread`/`add`. Delete `ThreadSubjectsError` from errors and `__init__`. Update `tutoring/__init__.py` docstring ("tutoring: threads and their documents used, relevance gate, ask path, conversations.") and rewrite `tutoring/README.md` to match the module now (Owns: threads with no subjects and their documents used, relevance gate, ask path; Built so far: `Thread`, `SqlThreadRepository`, `ConversationService.require_documents/start_thread`, `Retriever`/`McpRetriever` (`search(query, k)` over all ready documents), `answer_messages`/`cited_chunks`; remove the detection, growth and interim-rule text). In `knowledge/README.md` list `has_ready_documents` with `DocumentService` and replace the `SearchService.search(user_id, query, subject_ids, k=5)` sentence with the new signature/filter (no subject rejection, no `subject_ids` on hits).

Migration `0007_threads_without_subjects.py`:

```python
"""Threads have no subjects (PRD v2.23 §9.4, Q55): drop threads.subject_ids.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("threads_subject_count", "threads", type_="check")
    op.drop_column("threads", "subject_ids")


def downgrade() -> None:
    # Old rows can't regain their subjects; they come back empty, so the 1-3 check isn't restored.
    op.add_column(
        "threads",
        sa.Column("subject_ids", postgresql.ARRAY(sa.Uuid(as_uuid=False)), nullable=False, server_default="{}"),
    )
```

(Check `0005_threads.py` for the exact constraint name: `threads_subject_count`.)

- [ ] **Step 4: Failing route tests, then the relay**

Rewrite `tests/unit/apps/api/test_thread_routes.py` around an agent stream with no `subjects` event (`AGENT_ANSWER` = `delta`, `citations`, `done`). Required cases:
- starts a thread and sends `event: thread` with exactly `{"thread_id": <id>}` first, then the agent's events byte-identical; the agent body is `{"question": "<stripped question>"}`.
- an agent `error` first is relayed as-is and starts no thread (Review Focus 1).
- the stream ends before any complete event, or drops inside the first event → one `unavailable` error event, no thread (Review Focus 2).
- a failure starting the thread → `unavailable` error event.
- an archived-only learner → 409 before any agent call (Review Focus 3).
- keep: 401/503/422 cases, split-across-reads, dropped-mid-stream cases, OpenAPI test.
- delete: placeholder-name, detected-subjects, subject-not-the-learner's, malformed-`subjects` parametrized tests.

`tests/isolation/test_threads.py`: the fake agent answers `event: delta\ndata: {"text": "Hi"}\n\nevent: done\ndata: {}\n\n`; keep `test_each_learner_starts_their_own_thread`; replace `test_a_subject_only_another_learner_has_starts_no_thread` with a test that learner B (no documents) gets 409 while A has ready documents in a subject B would share, and no thread is stored.

`routes/threads.py`:
- Module docstring: "Thread routes (tutoring module): ask the first question of a new thread; it answers from all of the learner's ready documents. Answered as SSE (PRD §9.2)."
- Drop `Subjects`, `UNNAMED_SUBJECT`, `SubjectId`, `ThreadSubjectsError` imports; `SSE_RESPONSE` description stays "thread, then delta*, citations, done (or error)."
- `StartThread = Callable[[], Awaitable[bytes | None]]`.
- Replace `_subject_ids` and `_opening` with:

```python
async def _opening(first: bytes | None, start: StartThread) -> bytes | None:
    """What goes before the agent's first event: nothing for an `error` (relayed as-is, no thread), else the
    `thread` event; None when the stream ended before any event or the thread couldn't start."""
    if first is None:
        logger.warning("the agent's stream ended before its first event")
        return None
    event = _event(first)
    if event is not None and event[0] == "error":
        return b""
    return await start()
```

- `_relay`: `opening = await _opening(first := await anext(events, None), start)`; `None` → yield `_UNAVAILABLE_EVENT` and return; else `if opening: yield opening`, then `yield first`, then the rest. Docstring: "The agent's events after a `thread` event, each forwarded only once complete. The thread starts on the agent's first event unless it is an `error`, which is relayed as-is and starts none. …(keep the partial-event sentence)".
- Route: `await run_in_threadpool(conversations.require_documents, principal.user_id)` (409 on `NoDocumentsError`), then `agent.open_answer(token, body.question)`; `start()` calls `conversations.start_thread(principal.user_id)`, catches `NoDocumentsError` (warning: "the thread was refused: %s") and `Exception` (`logger.exception("starting a thread failed")`), returns `_sse("thread", {"thread_id": thread.thread_id})`. Drop the `subjects` dependency parameter.

- [ ] **Step 5: Regenerate the web API client and run the backend checks**

Run: `cd web && npm run api-client` (or the `api-client` Makefile line), then the five backend checks. Integration tests (`tests/integration/tutoring/test_sql_threads.py`) need Compose; update them to the new `Thread` shape even if they can't run locally.

- [ ] **Step 6: Commit**

```bash
git add -A backend web/src/api
git commit -m "Start threads without subjects" -m "A thread has no subjects (PRD v2.23 §9.4, Q55). The API starts it on the agent's first event unless that is an error, and its thread event carries only the thread id. Migration 0007 drops threads.subject_ids."
```

---

### Task 3: Web chat without subjects

**Files:**
- Modify: `web/src/api/chat.ts`, `web/src/api/chat.test.ts`
- Modify: `web/src/features/chat/ChatPage.tsx`, `ChatPage.test.tsx`, `ChatPage.module.css` (remove now-unused `.chips`, `.headerChips`, `.yourSubjects` rules)

**Interfaces:**
- Consumes (Task 2): `thread` event data `{"thread_id": string}`.
- Produces: `ChatEvent` member `{ type: "thread"; thread_id: string }`; `ChatPage` props `{ ask?, loadDocs? }` (no `loadSubjects`).

- [ ] **Step 1: Failing tests**

`chat.test.ts`: the parsed `thread` event is `{ type: "thread", thread_id: "t1" }`.

`ChatPage.test.tsx` (`renderChat` passes `loadDocs={async () => [doc("ready")]}` by default; drop `SUBJECTS` and `loadSubjects`):
- "starts with the new-conversation header and the welcome, without subjects or example questions": heading "New conversation"; "Ask about your documents"; the text "There's nothing to choose first: just ask."; no list named "Your subjects" or "Subjects"; no "Subjects appear after your first question.".
- "asks for an upload first when the learner has no ready documents": `loadDocs: async () => [doc("processing"), doc("awaiting_subjects"), doc("failed")]` → "Upload a document first" (Review Focus 3).
- "explains when the documents can't be loaded": `loadDocs: () => Promise.reject(new Error("GET /documents failed (500)"))` → "Your documents couldn't be loaded. Reload the page to try again." and no "Upload a document first" (Review Focus 5).
- a `SessionExpiredError` from `loadDocs` renders nothing (replace the subjects version).
- "titles the conversation with the question, with no subject chips": after `thread` + `done`, the heading is the question and there is no list named "Subjects".
- the processing hint test now uses `loadDocs: async () => [doc("ready"), doc("processing"), doc("awaiting_subjects"), doc("failed")]` and expects "1 document is still processing and can't be used yet." (keep its existing intent).
- update every `{ type: "thread", thread_id: "t1", subjects: [...] }` to `{ type: "thread", thread_id: "t1" }`; delete the chips tests; change the `AskRefusedError` sample message from "Subject detection isn't available yet" to "The tutor can't answer that right now".

`doc(state)` already exists in the test file; reuse it.

- [ ] **Step 2: Run them — expect failures**

Run: `cd web && npx vitest run src/features/chat src/api/chat.test.ts`

- [ ] **Step 3: Implement**

`chat.ts`: `| { type: "thread"; thread_id: string }`; `case "thread": return { type: "thread", thread_id: payload().thread_id as string };`; `AskRefusedError` comment: "Another 409 from POST /threads: its message is for the learner."

`ChatPage.tsx`:
- Remove `loadMySubjects`, `SubjectChip`, `Subject`, `loadSubjects`, `Exchange.subjects`, the `thread` branch (ignore `thread` events: `if (event.type === "delta") … else if …`).
- Replace the `Subjects` state with `type Library = { status: "loading" | "failed" | "ended" } | { status: "ready" }` and one effect:

```tsx
  // The documents decide what the page is: none ready → upload first; still processing → a hint.
  useEffect(() => {
    let current = true;
    loadDocs().then(
      (docs) => {
        if (!current) return;
        setProcessing(docs.filter((d) => d.state === "processing").length);
        if (docs.some((d) => d.state === "ready")) setLibrary({ status: "ready" });
        else setNoDocuments(true);
      },
      (error: unknown) => current && setLibrary({ status: error instanceof SessionExpiredError ? "ended" : "failed" }),
    );
    return () => {
      current = false;
    };
  }, [loadDocs]);
```

(`GET /documents` returns only non-archived documents — confirm in `apps/api/routes/knowledge.py` / `DocumentService.list_documents`; if archived ones are included, also require `!d.archived`.)
- Loading/failed view: `<PageHeader title="New conversation" />` and, when failed, `<p className={styles.problem}>Your documents couldn't be loaded. Reload the page to try again.</p>`.
- Exchange header: `<PageHeader title={exchange.question} titleClassName={styles.clampedTitle} />`.
- Welcome: `<PageHeader title="New conversation" />`, then the section with `<h2>Ask about your documents</h2>` and the paragraph "I answer only from the documents in your Library and show the page each answer came from. There's nothing to choose first: just ask." No subjects block.
- Remove unused CSS rules from `ChatPage.module.css`.

Check `PageHeader`'s `description` prop is optional (`web/src/components/PageHeader/PageHeader.tsx`).

- [ ] **Step 4: Run web tests and build**

Run: `cd web && npx vitest run && npm run build`

- [ ] **Step 5: Look at it against the mockup**

Run: `make design-shots ROUND=v0.10 STATES="chat-new,chat-no-documents,chat-documents-processing" THEME=both` (or `cd web && npm run design:shots -- …` per `sdd/design/README.md`) and compare copy and structure; the prototype is a spec, rebuilt with existing components (no example questions: they are optional in `chat-new`).

- [ ] **Step 6: Commit**

```bash
git add -A web
git commit -m "Remove subjects from the chat" -m "Conversations have no subjects (PRD v2.23, design v0.10 chat-new): no subject chips or 'Your subjects' line, and 'Upload a document first' now follows the learner's ready documents."
```

---

### Task 4: Settings, infra, local stack, evals and docs without detection

**Files:**
- Modify: `infra/smart_tutor_infra/stacks/config.py` (drop the three parameters and the comment's detection clause), `infra/tests/test_config_stack.py` (replace `test_detection_thresholds_are_ssm_parameters` with a test that none of `detect-threshold`, `detect-margin`, `multi-margin` exist)
- Modify: `infra/smart_tutor_infra/stacks/cluster.py:~168` — the agent's pod identity no longer reads SSM: drop `ssm` from its policy (keep `chat`); update any infra test that asserts the agent's SSM permission.
- Modify: `local/localstack/init/ready.d/10-smart-tutor.sh` (delete the three `put-parameter` lines and comment; move `app-time-zone` last with the comment "Keep app-time-zone the last parameter written: the LocalStack healthcheck in compose.yaml waits for it.")
- Modify: `compose.yaml` (healthcheck reads `/smart-tutor/app-time-zone`; its comment says "it sets app-time-zone last" and "the api and worker read SSM at startup"; the agent service drops `AWS_ENDPOINT_URL_SSM`, `SMART_TUTOR_LOCALSTACK`, their comments, and `localstack` from `depends_on`)
- Modify: `backend/evals/thresholds.yaml` (delete `subject_detection` and `thread_growth`), `backend/evals/README.md` (generators line: drop "detection/ambiguous items, multi-turn subject switches"), `backend/evals/seed_corpus/README.md` ("Synthetic learners for dedupe and isolation tests")
- Check: `deploy/helm/` and `.env.example` for `DETECT`/`MULTI_MARGIN`/agent SSM env — remove any.

**Interfaces:** none (configuration only).

- [ ] **Step 1: Failing infra test**

```python
def test_no_subject_detection_parameters() -> None:
    template = ...  # same construction as the existing tests in this file
    names = {p["Properties"]["Name"] for p in template.find_resources("AWS::SSM::Parameter").values()}
    assert not names & {"/smart-tutor/detect-threshold", "/smart-tutor/detect-margin", "/smart-tutor/multi-margin"}
```

- [ ] **Step 2: Run** `cd infra && uv run pytest -q` — expect the new test to fail.

- [ ] **Step 3: Apply all file changes above.**

- [ ] **Step 4: Verify**

Run: `cd infra && uv run pytest -q`; `helm lint deploy/helm/smart-tutor` if `deploy/` changed; `docker compose config -q` (if Docker is available); and the acceptance grep: `grep -rniE "detect|multi.margin" backend/src web/src infra local compose.yaml backend/evals/thresholds.yaml` — only non-subject matches may remain.

- [ ] **Step 5: Commit**

```bash
git add -A infra local compose.yaml backend/evals deploy .env.example
git commit -m "Remove the subject detection settings" -m "The agent no longer reads detect-threshold, detect-margin or multi-margin (PRD v2.23 Q55), so the CDK parameters, the LocalStack seed, the agent's SSM access and the detection eval targets go too."
```

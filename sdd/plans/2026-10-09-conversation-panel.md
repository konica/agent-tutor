# Conversation panel: documents used (#122) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each thread records the documents whose chunks were given to the model for an answered turn, the API lists them (owner only), and the chat shows them in a collapsible conversation panel with the Lesson Note and Actions sections.

**Architecture:** The agent already knows which chunks it gave the model; it emits one internal `sources` SSE event (document ids, in order of first use) before `citations`. The API's relay keeps that event to itself and, when the agent's `done` arrives for a started thread, calls `ConversationService.record_answer` before forwarding `done`; an `error`, a dropped stream, or a client that stops reading never reaches that point, so it records nothing. `GET /threads/{id}/documents` resolves titles, authors, year, and `archived` at read time through `knowledge.application.DocumentService`; a document that no longer exists reads as deleted. The web chat page becomes a full-height two-column layout: a 260px conversation panel (toggle in a 40px chat header, remembered in `localStorage`) and the conversation.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core, Alembic, LangGraph; React + TypeScript + Vite, Vitest + Testing Library.

**Spec:** GitHub issue #122 (parent #118), `sdd/prd.md` v2.23 §8 US-4b, §9.2 step 4, §9.4 "Thread document"; `DESIGN.md` → Chat ("Conversation panel", chat header); mockups `design-v0.10` states `chat-documents-used`, `chat-documents-used-empty`, `chat-panel-collapsed`, `chat-summarize-done`.

## Global Constraints

- Table `thread_documents (thread_id, document_id, first_used_at, deleted_title)`, primary key `(thread_id, document_id)`, **no foreign key to `documents`**; FK to `threads` is fine. Plus one ordering column `seq bigint generated always as identity` (documents of one turn share `first_used_at`; order is `first_used_at, seq`).
- Documents used are only ever added; in order of first use; no duplicates.
- A decline (no chunks), an `error` event, a stream that ends before `done`, or a client that stops reading adds nothing.
- Retrieved chunk text is never stored. Citations carry `document_id` (stored as ids once answers are saved; titles resolve at read time).
- `GET /threads/{thread_id}/documents` → 404 "Conversation not found" for a thread the caller doesn't own (no existence leak). Body: list of `{document_id, title, authors, year, archived, deleted}`.
- Deleted document: `deleted: true`, title = `deleted_title` or "Deleted document", authors `[]`, year `null`, `archived: false`.
- Web copy (exact): empty list "Documents used to answer will appear here."; badge "Archived"; toggle accessible name "Hide panel" / "Show panel"; section headings "Documents", "Lesson Note", "Actions"; "Summarize lesson"; "Show citations"; "Archive conversation"; Lesson Note before the first answer: "After the first answer you can summarize this conversation into a note."; after: "Turn this conversation into a note you can edit."
- Out of scope (later tickets): follow-up questions in the same thread (chat stays single-turn, #82), saving answers and history, opening a document from a row (#123), "Add documents" / "Only search these documents" (#129–#131), summarize (US-7), archive conversation (US-13), delete (#125, which will fill `deleted_title`). "Summarize lesson" and "Archive conversation" render **disabled**.
- `localStorage` access is wrapped in try/catch; the page works without it.
- Run checks from `AGENTS.md` → Checks. Windows Git Bash: `PYTHONUTF8=1` for `lint-imports`.

## Review Focus

1. The same document cited by several chunks in one answer, or again in a later answer → listed once, at its first position (Task 3 test `test_record_answer_keeps_first_use_order_without_duplicates`).
2. The agent's stream errors after `sources` but before `done` → nothing recorded (Task 4 test `test_error_after_sources_records_nothing`).
3. The client stops reading mid-answer → nothing recorded (Task 4 test `test_a_stream_closed_before_done_records_nothing`).
4. Recording fails (database down) after the answer streamed → the learner still gets `done`; the failure is logged (Task 4 test `test_a_failed_record_still_ends_with_done`).
5. `localStorage` throws (private mode) → panel defaults to open and toggling still works (Task 5 test "works when storage throws").

---

### Task 1: knowledge — look up a learner's documents by id, archived included

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py` (add `archived` to `DocumentView`, add `documents_by_id`)
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py` (add `list_readable_by_ids`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py`
- Modify: `backend/tests/fakes/knowledge.py`
- Test: `backend/tests/unit/knowledge/test_document_service.py` (add tests), `backend/tests/integration/knowledge/test_sql_library.py` (add one integration test; find the existing file with `ls backend/tests/integration/knowledge`)
- Modify: `backend/src/smart_tutor/knowledge/README.md` (mention `documents_by_id`)

**Interfaces:**
- Produces: `DocumentView.archived: bool = False` (last field, default keeps existing constructors valid); `document_view(d, max_attempts)` sets it from `d.archived`.
- Produces: `DocumentRepository.list_readable_by_ids(user_id: UserId, document_ids: Collection[DocumentId]) -> list[Document]` — `can_read` in storage, **archived included**, any state, each with content title, authors, year (same columns as `list_readable_by`). Unknown ids or other learners' ids are simply absent.
- Produces: `DocumentService.documents_by_id(user_id: UserId, document_ids: Collection[DocumentId]) -> dict[DocumentId, DocumentView]`.

- [ ] **Step 1: Write failing unit tests** in `tests/unit/knowledge/test_document_service.py`, using the existing helpers there (`InMemoryLibrary`, `ingest_ready` from `fakes`; read the file's existing tests for the style):

```python
def test_documents_by_id_returns_the_learners_documents_archived_included() -> None:
    library = InMemoryLibrary()
    a = ingest_ready(library, "learner-a", "Attention weighs tokens.")
    b = ingest_ready(library, "learner-a", "Gradient descent follows the slope.")
    other = ingest_ready(library, "learner-b", "Someone else's.")
    archive(library, b)  # set the stored Document's archived = True through the fake's state
    service = DocumentService(library.unit_of_work, max_attempts=3)

    found = service.documents_by_id(UserId("learner-a"), [a, b, other, DocumentId("missing")])

    assert set(found) == {a, b}
    assert found[a].archived is False
    assert found[b].archived is True
```

If `ingest_ready` does not return the `DocumentId`, read `tests/fakes/knowledge.py` / `tests/fakes/ingest.py` and get the id the way other tests do. Write the small `archive` helper in the test file (load the document via a unit of work, set `archived=True`, save, commit) — or use `Document.archive()` if it exists in `knowledge/domain/document.py`.

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/unit/knowledge/test_document_service.py -q` — expect FAIL (`documents_by_id` missing).

- [ ] **Step 3: Implement.** Port method (abstract, docstring: "`can_read` in storage: the caller's documents with these ids, archived included, each with its content's title, attempts, authors, and year."). Fake: filter `state.documents` by `can_be_read_by(user_id)` and id membership, returning copies enriched like `list_readable_by` does. SQL: copy the `select` used by `list_readable_by` (same joins and `_load`), with `documents.c.document_id.in_(ids)` and `readable_by(user_id)`, **without** the archived filter; return `[]` without querying when `ids` is empty. Service:

```python
    def documents_by_id(self, user_id: UserId, document_ids: Collection[DocumentId]) -> dict[DocumentId, DocumentView]:
        """The learner's documents among these ids, archived included; others' and unknown ids are absent (`can_read`)."""
        if not document_ids:
            return {}
        with self._uow() as tx:
            documents = tx.documents.list_readable_by_ids(user_id, document_ids)
        return {d.document_id: document_view(d, self._max_attempts) for d in documents}
```

- [ ] **Step 4: Integration test** (marked `@pytest.mark.integration`, follow the existing file's fixtures): an archived document of learner A is returned to A, not to B. Run `uv run pytest tests/integration/knowledge -q -m integration` if Compose Postgres is up (`docker compose up -d`, `make migrate`); otherwise note it was not run.

- [ ] **Step 5: Run** `uv run pytest tests/unit -q && uv run mypy` — PASS. Check the library route still serializes (`DocumentResponse` built from `DocumentView` must not break; run `uv run pytest tests/unit/apps/api -q`).

- [ ] **Step 6: Commit** `Look up a learner's documents by id, archived included` (body: documents used list them, archived or not, US-4b).

---

### Task 2: tutoring storage — `thread_documents`

**Files:**
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0008_thread_documents.py`
- Create: `backend/src/smart_tutor/tutoring/domain/thread_document.py`
- Modify: `backend/src/smart_tutor/tutoring/ports/thread_repository.py`
- Modify: `backend/src/smart_tutor/tutoring/adapters/sql_threads.py`
- Modify: `backend/tests/fakes/tutoring.py`
- Test: `backend/tests/integration/tutoring/test_sql_threads.py`

**Interfaces:**
- Produces (domain):

```python
"""A document the thread drew on (PRD §9.4 Thread document); the row outlives the document."""

from dataclasses import dataclass
from datetime import datetime

from smart_tutor.shared.domain.ids import DocumentId, ThreadId


@dataclass(frozen=True)
class ThreadDocument:
    thread_id: ThreadId
    document_id: DocumentId
    first_used_at: datetime
    deleted_title: str | None = None  # the display title, copied when the document is deleted (US-10c)
```

- Produces (port, on `ThreadRepository`):
  - `add_documents_used(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None` — "Append the documents not listed yet, in this order, first used `at`; already listed ones keep their place (committed when this returns)."
  - `documents_used(self, thread_id: ThreadId) -> list[ThreadDocument]` — "In order of first use." (Callers check ownership first with `get_owned`.)

- [ ] **Step 1: Migration 0008** (`revision = "0008"`, `down_revision = "0007"`, docstring "Thread documents: the documents a thread drew on (PRD §9.4, US-4b); no foreign key to documents, so rows outlive a deleted document."):

```python
def upgrade() -> None:
    op.create_table(
        "thread_documents",
        sa.Column("thread_id", sa.Uuid(as_uuid=False), sa.ForeignKey("threads.thread_id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("first_used_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_title", sa.Text),
        # Documents of one turn share first_used_at; seq keeps their order.
        sa.Column("seq", sa.BigInteger, sa.Identity(always=True), nullable=False),
        sa.PrimaryKeyConstraint("thread_id", "document_id"),
    )


def downgrade() -> None:
    op.drop_table("thread_documents")
```

Check the type of `documents.document_id` in `knowledge/adapters/sql_tables.py` and match it (Uuid vs Text).

- [ ] **Step 2: Failing integration tests** in `tests/integration/tutoring/test_sql_threads.py` (follow the file's fixtures):

```python
def test_documents_used_keep_first_use_order_without_duplicates(repo, thread) -> None:
    d1, d2, d3 = (DocumentId(str(uuid.uuid4())) for _ in range(3))
    repo.add_documents_used(thread.thread_id, [d1, d2], T0)
    repo.add_documents_used(thread.thread_id, [d2, d3, d1], T1)

    used = repo.documents_used(thread.thread_id)

    assert [u.document_id for u in used] == [d1, d2, d3]
    assert [u.first_used_at for u in used] == [T0, T0, T1]
    assert all(u.deleted_title is None for u in used)
```

Also add a pure fake-backed unit test of the same behavior at `tests/unit/tutoring/test_thread_documents_fake.py` so the fake is held to the same contract (default `pytest` run).

- [ ] **Step 3: Implement.** SQL adapter: a `thread_documents` `Table` next to `threads`; `add_documents_used` inserts rows one per id in order inside one `engine.begin()` using `sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_nothing(index_elements=["thread_id", "document_id"])` (skip when the list is empty); `documents_used` selects ordered by `first_used_at, seq`. Fake: keep `self.documents_used_rows: dict[str, list[ThreadDocument]]`, append ids not present.

- [ ] **Step 4: Run** `uv run pytest tests/unit -q` (PASS); integration with Compose if available: `uv run pytest tests/integration/tutoring -q -m integration`. `make migrate` (or `uv run --env-file ../.env alembic upgrade head` per the Makefile) must apply 0008 cleanly; also try `alembic downgrade -1` then `upgrade head`.

- [ ] **Step 5: Commit** `Store a thread's documents used` (body: thread_documents per PRD §9.4; seq orders documents of one turn).

---

### Task 3: tutoring application — record an answer and list its documents

**Files:**
- Create: `backend/src/smart_tutor/tutoring/domain/document_used.py`
- Modify: `backend/src/smart_tutor/tutoring/domain/errors.py` (add `ThreadNotFoundError(DomainError)`)
- Modify: `backend/src/smart_tutor/tutoring/application/conversation_service.py`
- Modify: `backend/src/smart_tutor/tutoring/application/__init__.py` (export `DocumentUsed`, `ThreadNotFoundError`)
- Modify: `backend/src/smart_tutor/tutoring/README.md`, `backend/src/smart_tutor/tutoring/domain/thread.py` docstring ("its documents used (US-4b) are still to come" → now built)
- Test: `backend/tests/unit/tutoring/test_conversation_service.py`

**Interfaces:**
- Consumes: Task 1 `DocumentService.documents_by_id`, `DocumentView.archived`; Task 2 `ThreadRepository.add_documents_used / documents_used`, `ThreadDocument`.
- Produces:

```python
DELETED_DOCUMENT = "Deleted document"

@dataclass(frozen=True)
class DocumentUsed:
    """A document the conversation drew on, as the learner sees it now (US-4b)."""
    document_id: DocumentId
    title: str
    authors: tuple[str, ...]
    year: int | None
    archived: bool
    deleted: bool
```

- `ConversationService.record_answer(self, thread_id: ThreadId, user_id: UserId, document_ids: Sequence[DocumentId]) -> None` — no-op for an empty list; raises `ThreadNotFoundError` when the thread isn't the learner's; dedupes preserving order; `first_used_at = clock.now()`.
- `ConversationService.documents_used(self, thread_id: ThreadId, user_id: UserId) -> list[DocumentUsed]` — raises `ThreadNotFoundError("Conversation not found")` when not owned; resolves through `documents_by_id`; a missing document → `DocumentUsed(id, row.deleted_title or DELETED_DOCUMENT, (), None, archived=False, deleted=True)`.

- [ ] **Step 1: Failing tests** (use `InMemoryThreads`, `InMemoryLibrary`, `ingest_ready`, `FixedClock` like the existing tests in the file):

```python
def test_record_answer_keeps_first_use_order_without_duplicates() -> None:
    # two answers: [a, b, a] then [c, b] → a, b, c
    ...
    service.record_answer(thread.thread_id, LEARNER, [a, b, a])
    service.record_answer(thread.thread_id, LEARNER, [c, b])
    assert [d.document_id for d in service.documents_used(thread.thread_id, LEARNER)] == [a, b, c]

def test_record_answer_with_no_documents_adds_nothing() -> None:  # a decline
    service.record_answer(thread.thread_id, LEARNER, [])
    assert service.documents_used(thread.thread_id, LEARNER) == []

def test_documents_used_show_title_authors_year_and_archived() -> None: ...
def test_a_document_that_no_longer_exists_reads_as_deleted() -> None:
    # record an id unknown to the library → title "Deleted document", deleted=True
def test_another_learner_can_neither_record_nor_read() -> None:
    with pytest.raises(ThreadNotFoundError): service.documents_used(thread.thread_id, OTHER)
    with pytest.raises(ThreadNotFoundError): service.record_answer(thread.thread_id, OTHER, [a])
```

- [ ] **Step 2: Run** — FAIL. **Step 3: Implement** with the interfaces above. **Step 4: Run** `uv run pytest tests/unit/tutoring -q && uv run mypy && PYTHONUTF8=1 uv run lint-imports` — PASS.

- [ ] **Step 5: Commit** `Record and list a conversation's documents used`.

---

### Task 4: agent emits `sources`; the API records on `done` and serves the list

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/domain/retrieved_chunk.py` (add `document_id: str` as the second field, after `chunk_id`; `citation()` passes it)
- Modify: `backend/src/smart_tutor/shared/domain/citation.py` (add `document_id: str | None = None` at the end)
- Modify: `backend/src/smart_tutor/tutoring/adapters/mcp_retriever.py` (read `c["document_id"]`)
- Modify: `backend/src/smart_tutor/apps/agent/server.py` (emit `sources`; add `document_id` to citations; update the module docstring)
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py`
- Modify: every `RetrievedChunk(...)` construction in tests and evals (`grep -rn "RetrievedChunk(" backend`)
- Test: `backend/tests/unit/apps/agent/` (server tests), `backend/tests/unit/apps/api/` (threads route tests), `backend/tests/isolation/test_threads.py`
- Regenerate: `web/src/api/openapi.json` and `web/src/api/generated/` via `make api-client` (or the Makefile's one-line command)

**Interfaces:**
- Consumes: Task 3 `ConversationService.record_answer`, `documents_used`, `DocumentUsed`, `ThreadNotFoundError`.
- Produces: agent SSE event `sources` `{"document_ids": [...]}` — the distinct document ids of the chunks given to the model, in rank order, emitted right before `citations` and **only when chunks were given to the model** (the no-chunks reply emits none). Citations gain `"document_id"`.
- Produces: `GET /threads/{thread_id}/documents`, `operation_id="list_thread_documents"`, response `list[ThreadDocumentResponse]`:

```python
class ThreadDocumentResponse(BaseModel):
    document_id: str
    title: str
    authors: list[str]
    year: int | None
    archived: bool
    deleted: bool
```

- [ ] **Step 1: Agent tests first.** In the agent server tests (see how they build a graph with fake retriever/model), assert: with chunks from documents `d1, d2, d1` the stream is `delta…, sources {"document_ids": ["d1","d2"]}, citations, done` and each citation has `document_id`; with no chunks there is no `sources` event. Run — FAIL.

- [ ] **Step 2: Implement the agent.** In `answer_events`, inside the `updates`/`answer` branch, before the citations event:

```python
                if chunks := update.get("chunks_used", []):
                    yield sse("sources", {"document_ids": list(dict.fromkeys(c.document_id for c in chunks))})
```

To get the chunks there, have `answer_node` return `"chunks_used": chunks` alongside answer and citations when it called the model (add `chunks_used: list[RetrievedChunk]` to `AskState`), or read them from the `search` node's update (track `chunks` from `part["data"]["search"]` in a local). Prefer the local from the `search` update plus "only if the answer node called the model" — i.e. emit `sources` when `chunks` is non-empty, since a non-empty chunk list is exactly when `answer_node` calls the model. Add `"document_id": c.document_id` to each citation dict. Update the module docstring's event list.

- [ ] **Step 3: API route tests first** (`tests/unit/apps/api/test_threads*.py`; reuse `fake_agent`, `api_services`, `ingest_ready`). Agent fake bodies:

```python
SOURCES = 'event: sources\ndata: {"document_ids": ["%s", "%s"]}\n\n'
# answered: delta, sources, citations, done
```

Tests:
  - `test_an_answered_turn_records_its_documents_and_hides_sources` — after POST /threads, `GET /threads/{id}/documents` lists both in order; the POST body contains no `event: sources`.
  - `test_error_after_sources_records_nothing` — body `delta, sources, error` → list empty.
  - `test_a_stream_closed_before_done_records_nothing` — agent body `delta, sources` then ends (or ends inside an event) → list empty and the client gets the unavailable error event.
  - `test_a_decline_records_nothing` — `delta, citations [], done` with no `sources` → empty.
  - `test_a_failed_record_still_ends_with_done` — make `record_answer` raise (override `conversations` with a subclass whose `record_answer` raises `RuntimeError`) → the stream still ends with `event: done`.
  - `test_documents_list_marks_archived_and_deleted` — archived document → `archived: true`; recorded unknown id → `deleted: true`, title "Deleted document".
  - `test_unknown_thread_is_404`.
  Run — FAIL.

- [ ] **Step 4: Implement the relay.** In `_relay`, keep `sources: list[str] | None = None`. For each event after the opening: parse with `_event`; if its name is `sources`, store `data["document_ids"]` and **do not yield it**; if it is `done` and the thread started (the `thread` event was yielded) and `sources`, `await record()` before yielding `done`. Pass `record: Callable[[list[str]], Awaitable[None]]` into `_relay` next to `start`; in the route, `start()` keeps the started thread id in a local (`nonlocal thread_id`), and `record` calls `run_in_threadpool(conversations.record_answer, ThreadId(thread_id), principal.user_id, [DocumentId(d) for d in ids])`, catching `Exception` with `logger.exception("recording the documents used failed")`. The first event can't be `sources` or `done` in practice, but handle it the same way (it goes through the same per-event code). Update the SSE_RESPONSE description: "thread, then delta*, citations, done (or error)".

  New route:

```python
@router.get("/threads/{thread_id}/documents", operation_id="list_thread_documents", responses={404: {"description": "Not the caller's conversation."}})
def list_thread_documents(thread_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations) -> list[ThreadDocumentResponse]:
    try:
        used = conversations.documents_used(ThreadId(str(thread_id)), principal.user_id)
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    return [ThreadDocumentResponse(document_id=d.document_id, title=d.title, authors=list(d.authors), year=d.year, archived=d.archived, deleted=d.deleted) for d in used]
```

  (A sync `def` route runs in FastAPI's threadpool, as other sync routes in `routes/knowledge.py` do — check and match.) A malformed id is a 422 from FastAPI.

- [ ] **Step 5: Isolation test** in `tests/isolation/test_threads.py`: learner A asks (agent body with `sources` naming A's document) → A's `GET /threads/{id}/documents` lists it; B's GET of the same id is 404 and B cannot see A's titles. Module docstring of the file: extend to mention the documents list.

- [ ] **Step 6: Run** `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest` — PASS. Then `make api-client` (read the Makefile target and run its command directly if `make` is missing); `cd web && npm run build` must still pass.

- [ ] **Step 7: Commit** `Record documents used when an answer is done; list them per thread` (body: PRD §9.2 step 4; the agent's sources event stays between agent and API).

---

### Task 5: web — conversation panel

**Files:**
- Modify: `web/src/api/chat.ts` (add `document_id` to `ChatCitation`; add `loadDocumentsUsed`)
- Create: `web/src/features/chat/ConversationPanel.tsx`, `ConversationPanel.module.css`, `ConversationPanel.test.tsx`
- Create: `web/src/features/chat/usePanelOpen.ts`, `usePanelOpen.test.ts`
- Modify: `web/src/features/chat/ChatPage.tsx`, `ChatPage.module.css`, `ChatPage.test.tsx`
- Modify: `web/src/app/routes.tsx` (chat route `handle: { bleed: true }`), `web/src/components/AppShell/AppShell.tsx` + `.module.css` (a `bleed` page: no max-width, no padding, full height)
- Test: `web/src/api/chat.test.ts`

**Interfaces:**
- Consumes: generated `listThreadDocuments` and `ThreadDocumentResponse` from `web/src/api/generated/` (Task 4).
- Produces:
  - `loadDocumentsUsed(threadId: string, apiClient = client): Promise<ThreadDocumentResponse[]>` — same error handling as `loadDocuments` (`sessionOver` → `SessionExpiredError`; no data → `Error`).
  - `usePanelOpen(): [open: boolean, toggle: () => void]` — key `"smart-tutor.chat-panel-open"`, default `true`, read and write in try/catch.
  - `ConversationPanel` props: `{ id: string; documents: ThreadDocumentResponse[]; answered: boolean; showCitations: boolean; onShowCitationsChange: (on: boolean) => void }`.
  - `ChatPage` prop `loadUsed?: (threadId: string) => Promise<ThreadDocumentResponse[]>` (default `loadDocumentsUsed`).

Layout (read `DESIGN.md` → Chat and the rendered PNGs in `.design-shots/v0.10/`; render them with `make design-shots ROUND=v0.10 STATES="chat-documents-used,chat-documents-used-empty,chat-panel-collapsed,chat-summarize-done" THEME=both`):
- Page (bleed) = column: 40px chat header row (bottom border) with the toggle button (`PanelLeft` icon from lucide-react, `aria-expanded`, `aria-controls="conversation-panel"`, `aria-label`/tooltip "Hide panel"/"Show panel") and the title (`h1`, `--fs-14` semibold body font, single line with ellipsis: "New conversation" or the question).
- Below: grid `var(--chat-panel-w) minmax(0, 1fr)` (or `minmax(0,1fr)` when collapsed — the panel element is not rendered when closed); panel `--surface`, right border, padding `--sp-4`, scrolls on its own; the conversation pane scrolls and keeps the existing `.column` (`--chat-w`, centered) with its padding.
- Panel sections, each an `h2` (`--fs-12`/`--fs-13`, `--text-2`): **Documents** with a count badge (`documents.length`), then either the empty text or a `<ul>` of 32px rows (FileText 16px icon, title with ellipsis + `title` attribute, authors · year as the row's `title` tooltip too, "Archived" badge `StateBadge`-like small chip, or "Deleted" for deleted ones). Rows are plain `<li>` — not buttons (opening is #123). **Lesson Note**: the before/after copy and a disabled secondary `Button` "Summarize lesson" (only after the first answer). **Actions**: a switch "Show citations" (`<button role="switch" aria-checked>` or a checkbox styled as a switch — check `web/src/components/` for an existing one first) and a disabled "Archive conversation" button (Archive icon) shown only when a thread exists.
- "Show citations" off hides the Citations section of the answer.

- [ ] **Step 1: Failing tests.**
  - `chat.test.ts`: `loadDocumentsUsed` GETs `/threads/t1/documents` and returns the body; 401 → `SessionExpiredError`.
  - `usePanelOpen.test.ts`: default open; toggle persists `"false"`; a stored `"false"` starts closed; works when `localStorage.getItem`/`setItem` throw (`vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error(); })`).
  - `ConversationPanel.test.tsx`: empty text; rows in given order with "Archived" badge on an archived one; "Deleted" on a deleted one; disabled "Summarize lesson" after an answer; the switch calls `onShowCitationsChange(false)`.
  - `ChatPage.test.tsx`: before asking, the panel shows "Documents used to answer will appear here."; after an answer stream (`thread`, `delta`, `citations`, `done`) `loadUsed` is called with the thread id and both titles show in order; an `error` stream does not call `loadUsed`; the toggle has `aria-expanded="true"`, clicking (and pressing Enter/Space on it with `userEvent.keyboard`) collapses the panel (`aria-expanded="false"`, panel gone) and a re-render reads it back from `localStorage`; "Show citations" off hides the "Citations" region. Update existing tests that query the old `PageHeader` heading if they break.
  Run `cd web && npx vitest run src/features/chat src/api/chat.test.ts` — FAIL.

- [ ] **Step 2: Implement** per the layout above using design tokens only (no prototype CSS). In `ChatPage.submit`, remember `thread_id` from the `thread` event; after the loop, if a `done` was seen and a thread id exists, call `loadUsed(threadId)` and set the documents (a failure there leaves the list as it was; a `SessionExpiredError` is already reported). A new question (new thread, single-turn) clears the documents first.

- [ ] **Step 3: Run** `npx vitest run` and `npm run build` — PASS. Re-render the mockups and compare by eye with a dev build if feasible (`make web` with the stack up) — otherwise compare structure against the PNGs.

- [ ] **Step 4: Commit** `Show a conversation's documents used in a collapsible panel` (body: brief v0.10 P1, PRD Q60; Lesson Note and Archive stay disabled until US-7 and US-13).

---

### Task 6: docs

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/README.md` (built: `record_answer`, `documents_used`, `thread_documents`), `backend/src/smart_tutor/knowledge/README.md` (`documents_by_id`) if not already done.
- Modify: `sdd/prd.md` §9.4 "Thread document" row only if the implementation differs (it does: a `seq` ordering column; `added_by`/`added_at` arrive with US-4c) — add "`seq` orders documents first used in the same turn" and bump the status line to v2.23.1 with a one-line change note. If the PRD's convention for patch bumps differs, follow it.

- [ ] **Step 1:** Edit, **Step 2:** run the full backend checks once more, **Step 3:** commit `Document the documents used`.

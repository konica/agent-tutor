# Add and Remove Documents in a Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The learner adds documents to a conversation's document list from a searchable picker and removes them from it (issue #130, PRD v2.25 §8 US-4c, §9.4 Thread document, Q61).

**Architecture:** `thread_documents` gains `added_by` (`answer` / `learner`) and `added_at`; `first_used_at` becomes nullable. The list is ordered by `added_at, seq` (for answer rows `added_at = first_used_at`, so answers keep their order of first use). `ConversationService` gets `add_documents` (each id must be the caller's ready, non-archived document, read through `DocumentService.documents_by_id`, i.e. `can_read`) and `remove_document`. The API adds `POST /threads/{id}/documents` and `DELETE /threads/{id}/documents/{document_id}`. The web conversation panel gets "Add documents" (a `DocumentPicker` dialog) and a × remove button per row.

**Tech Stack:** FastAPI, SQLAlchemy Core, Alembic, pytest; React + TypeScript + Vite, Vitest + Testing Library, generated hey-api client.

**Spec:** Issue #130 (body is the spec), PRD `sdd/prd.md` §8 US-4c and §9.4 "Thread document", prototype `sdd/design/prototype/js/chat.js` at tag `design-v0.10` (`panelHtml`, `docPickerView`, `cp-remove`). No separate design doc: the issue is fully specified.

## Global Constraints

- Out of scope: the "Only search these documents" switch and scoped search (#131), starting a conversation from a document (#132), opening a document from the panel (#123).
- Release 1 `can_read`: owner only. A document id that isn't the caller's, isn't `ready`, or is archived is refused with `404` and nothing is added (all-or-nothing per request).
- A thread that isn't the caller's is `404` on both new endpoints (same message as today: "Conversation not found").
- Removing deletes the row; adding again recreates it (`added_by = learner`, new `added_at`). Removing never touches the document or old answers.
- An answer that uses a learner-added document sets its `first_used_at` (if still null) and keeps `added_by = learner` and its place. An answer that uses a removed document adds it back as `added_by = answer` ("answers still add the documents they use").
- POST body: `{"document_ids": [...]}`, 1–50 UUIDs, `extra="forbid"`. Duplicates and already-listed ids are ignored. Returns `200` with the full list (same shape as GET). DELETE returns `204`, also when the document wasn't listed.
- `ThreadDocumentResponse` gains `added_by: "answer" | "learner"` and `used: bool` (`first_used_at is not null`). The panel shows the "Added" badge when `!used` (prototype: `added && !used`).
- UI copy, verbatim: "Add documents" (button and dialog title); search placeholder and label "Search your documents"; list label "Your ready documents"; listed rows' meta "In this conversation"; empty search "No ready documents match."; footer "Cancel" and "Add" / "Add 1 document" / "Add N documents"; × button `aria-label="Remove {title} from this conversation"`, tooltip "Remove from this conversation"; badge "Added"; live announcement "{N document(s)} added to this conversation." / "{title} removed from this conversation.".
- "Add documents" shows only once the thread exists (`threadId !== null`): there is nothing to add to before the first question. (The prototype always shows it; recorded in the PR.)
- Focus: closing the picker (Add, Cancel, Escape) returns focus to "Add documents" (the `Dialog` restores the previous focus). Removing a row moves focus to the next row's remove button, else the previous row's, else "Add documents".
- Web visual rules: `DESIGN.md` (compact density), tokens only; rebuild with `web/src/components/` (`Dialog`, `Button`, `IconButton`), never paste prototype HTML/CSS.
- Backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Web: `cd web && npm run build` and `npx vitest run`.
- After changing routes: `make api-client` (or the Makefile's one-line command) regenerates `web/src/api/`.
- Commits: imperative subject, body says why, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. An answer that uses a document the learner added earlier must not duplicate the row nor move it; it only marks it used (so "Added" disappears). → Task 1 SQL + fake test, Task 2 service test.
2. A request mixing one valid id and one foreign/archived/processing id adds nothing (no partial add) and leaks no title. → Task 3 isolation test.
3. Removing a document that an answer later uses again: it comes back as an answer row. → Task 2 service test.
4. Removing the last row: focus lands on "Add documents", the empty text reappears. → Task 4 panel test.
5. A picker add that fails (network/500): the dialog stays open with an error line, selection kept; a session that expired is reported by the client. → Task 4 ChatPage test.

---

### Task 1: Store who added a thread document and when

**Files:**
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0010_thread_documents_added.py`
- Modify: `backend/src/smart_tutor/tutoring/domain/thread_document.py`
- Modify: `backend/src/smart_tutor/tutoring/ports/thread_repository.py`
- Modify: `backend/src/smart_tutor/tutoring/adapters/sql_threads.py`
- Modify: `backend/tests/fakes/tutoring.py`
- Test: `backend/tests/integration/tutoring/test_sql_threads.py`, `backend/tests/unit/tutoring/test_thread_documents_fake.py`

**Interfaces:**
- Produces:
  - `AddedBy = Literal["answer", "learner"]` in `tutoring/domain/thread_document.py`
  - `ThreadDocument(thread_id, document_id, added_by: AddedBy, added_at: datetime, first_used_at: datetime | None = None, deleted_title: str | None = None)`
  - `ThreadRepository.add_documents_used(thread_id, document_ids, at)` — unchanged signature; new rows are `added_by="answer", added_at=at, first_used_at=at`; an existing row with null `first_used_at` gets `at`; other existing rows are unchanged.
  - `ThreadRepository.add_documents(thread_id, document_ids: Sequence[DocumentId], at: datetime) -> None` — new rows `added_by="learner", added_at=at, first_used_at=None`, in this order; existing rows unchanged.
  - `ThreadRepository.remove_document(thread_id, document_id) -> None` — deletes the row if present.
  - `ThreadRepository.documents_used(thread_id)` — now the whole list, ordered by `added_at, seq`.

- [ ] **Step 1: Write the failing fake test** (append to `tests/unit/tutoring/test_thread_documents_fake.py`; keep its existing imports and style)

```python
T0 = datetime(2026, 10, 9, 9, 0, tzinfo=UTC)
T1 = datetime(2026, 10, 9, 9, 5, tzinfo=UTC)


def test_learner_added_documents_are_listed_unused_until_an_answer_uses_them() -> None:
    threads = InMemoryThreads()
    t, a, b = ThreadId("t"), DocumentId("a"), DocumentId("b")
    threads.add_documents_used(t, [a], T0)
    threads.add_documents(t, [b, a], T1)  # a is listed already

    threads.add_documents_used(t, [b], T1)

    rows = threads.documents_used(t)
    assert [(r.document_id, r.added_by, r.first_used_at) for r in rows] == [(a, "answer", T0), (b, "learner", T1)]


def test_a_removed_document_comes_back_when_added_again() -> None:
    threads = InMemoryThreads()
    t, a = ThreadId("t"), DocumentId("a")
    threads.add_documents_used(t, [a], T0)
    threads.remove_document(t, a)
    assert threads.documents_used(t) == []
    threads.add_documents(t, [a], T1)
    [row] = threads.documents_used(t)
    assert (row.added_by, row.added_at, row.first_used_at) == ("learner", T1, None)
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/unit/tutoring/test_thread_documents_fake.py -v` — Expected: FAIL (`add_documents` missing).

- [ ] **Step 3: Domain, port, fake**

`tutoring/domain/thread_document.py`:

```python
"""A document in the thread's document list (PRD §9.4 Thread document); the row outlives the document."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from smart_tutor.shared.domain.ids import DocumentId, ThreadId

AddedBy = Literal["answer", "learner"]


@dataclass(frozen=True)
class ThreadDocument:
    thread_id: ThreadId
    document_id: DocumentId
    added_by: AddedBy  # an answer drew on it, or the learner added it (US-4c)
    added_at: datetime
    first_used_at: datetime | None = None  # null until an answer uses it
    deleted_title: str | None = None  # the display title, copied when the document is deleted (US-10c)
```

Port (`tutoring/ports/thread_repository.py`): update `add_documents_used`'s docstring to "Append the documents not listed yet, in this order, added and first used `at`; a listed one keeps its place and is marked first used `at` if it wasn't used yet (committed when this returns)." Add:

```python
    @abstractmethod
    def add_documents(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        """The learner adds these documents, in this order, not used yet; listed ones are unchanged (committed)."""

    @abstractmethod
    def remove_document(self, thread_id: ThreadId, document_id: DocumentId) -> None:
        """Take the document off the list, if listed (committed). The document itself is untouched."""
```

and change `documents_used`'s docstring to "The thread's document list in the order documents joined it. (Callers check ownership first with `get_owned`.)"

Fake (`tests/fakes/tutoring.py`), replacing `add_documents_used` and adding the two methods (`import dataclasses`):

```python
    def add_documents_used(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        rows = self.documents_used_rows.setdefault(thread_id, [])
        for document_id in document_ids:
            i = next((i for i, row in enumerate(rows) if row.document_id == document_id), None)
            if i is None:
                rows.append(ThreadDocument(thread_id, document_id, "answer", at, first_used_at=at))
            elif rows[i].first_used_at is None:
                rows[i] = dataclasses.replace(rows[i], first_used_at=at)

    def add_documents(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        rows = self.documents_used_rows.setdefault(thread_id, [])
        for document_id in document_ids:
            if all(row.document_id != document_id for row in rows):
                rows.append(ThreadDocument(thread_id, document_id, "learner", at))

    def remove_document(self, thread_id: ThreadId, document_id: DocumentId) -> None:
        rows = self.documents_used_rows.get(thread_id, [])
        self.documents_used_rows[thread_id] = [row for row in rows if row.document_id != document_id]
```

(The fake appends in call order, which matches `added_at, seq` because callers pass a non-decreasing clock.)

- [ ] **Step 4: Run the fake test** — Expected: PASS.

- [ ] **Step 5: Migration 0010**

```python
"""Thread documents the learner adds (PRD §9.4, US-4c): who added a row and when; first use may be pending.

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Every existing row came from an answer, added when first used.
    op.add_column("thread_documents", sa.Column("added_by", sa.Text, nullable=False, server_default="answer"))
    op.add_column("thread_documents", sa.Column("added_at", sa.DateTime(timezone=True)))
    op.execute("UPDATE thread_documents SET added_at = first_used_at")
    op.alter_column("thread_documents", "added_at", nullable=False)
    op.alter_column("thread_documents", "added_by", server_default=None)
    op.create_check_constraint("thread_documents_added_by", "thread_documents", "added_by IN ('answer', 'learner')")
    op.alter_column("thread_documents", "first_used_at", nullable=True)


def downgrade() -> None:
    op.execute("DELETE FROM thread_documents WHERE first_used_at IS NULL")
    op.alter_column("thread_documents", "first_used_at", nullable=False)
    op.drop_constraint("thread_documents_added_by", "thread_documents")
    op.drop_column("thread_documents", "added_at")
    op.drop_column("thread_documents", "added_by")
```

- [ ] **Step 6: Integration test** (append to `tests/integration/tutoring/test_sql_threads.py`, reusing its helpers; read the existing `test_documents_used_keep_first_use_order_without_duplicates` first and follow its setup of a stored thread):

```python
def test_learner_added_documents_keep_their_place_and_are_marked_used(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    thread = Thread.start(ThreadId(str(uuid.uuid4())), UserId("learner-a"), datetime(2026, 10, 9, tzinfo=UTC))
    repo.add(thread)
    t = ThreadId(thread.thread_id)
    a, b, c = (DocumentId(str(uuid.uuid4())) for _ in range(3))
    t0, t1, t2 = (datetime(2026, 10, 9, 9, m, tzinfo=UTC) for m in (0, 5, 10))

    repo.add_documents_used(t, [a], t0)
    repo.add_documents(t, [c, b, a], t1)  # a is listed already
    repo.add_documents_used(t, [b], t2)

    rows = repo.documents_used(t)
    assert [(r.document_id, r.added_by, r.first_used_at) for r in rows] == [
        (a, "answer", t0),
        (c, "learner", None),
        (b, "learner", t2),
    ]

    repo.remove_document(t, c)
    repo.remove_document(t, c)  # not listed: nothing happens
    assert [r.document_id for r in repo.documents_used(t)] == [a, b]
```

- [ ] **Step 7: SQL adapter** (`sql_threads.py`): add `Column("added_by", Text)`, `Column("added_at", DateTime(timezone=True))` to `thread_documents`; module docstring mentions migration 0010. Replace methods:

```python
    def add_documents_used(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        if not document_ids:
            return
        with self._engine.begin() as conn:
            for document_id in document_ids:
                stmt = insert(thread_documents).values(
                    thread_id=thread_id, document_id=document_id, added_by="answer", added_at=at, first_used_at=at
                )
                # A listed document keeps its place; one the learner added is now used.
                conn.execute(
                    stmt.on_conflict_do_update(
                        index_elements=["thread_id", "document_id"],
                        set_={"first_used_at": func.coalesce(thread_documents.c.first_used_at, stmt.excluded.first_used_at)},
                    )
                )

    def add_documents(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        if not document_ids:
            return
        with self._engine.begin() as conn:
            for document_id in document_ids:
                conn.execute(
                    insert(thread_documents)
                    .values(thread_id=thread_id, document_id=document_id, added_by="learner", added_at=at)
                    .on_conflict_do_nothing(index_elements=["thread_id", "document_id"])
                )

    def remove_document(self, thread_id: ThreadId, document_id: DocumentId) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                thread_documents.delete().where(
                    thread_documents.c.thread_id == thread_id, thread_documents.c.document_id == document_id
                )
            )
```

`documents_used` orders by `thread_documents.c.added_at, thread_documents.c.seq` and builds `ThreadDocument(thread_id=..., document_id=..., added_by=r.added_by, added_at=r.added_at, first_used_at=r.first_used_at, deleted_title=r.deleted_title)`. Import `func` from `sqlalchemy`.

- [ ] **Step 8: Run** `uv run pytest tests/unit/tutoring tests/integration/tutoring -v` (integration needs `docker compose up -d`; if Postgres is unreachable, say so in the report — do not skip silently) and `uv run mypy`. Expected: PASS. Fix any other `ThreadDocument(` constructor callers mypy reports.

- [ ] **Step 9: Commit** — `git commit -m "Store who added a thread document and when"` (body: US-4c lets the learner add documents not used yet, so first use becomes optional and the list orders by when a document joined it).

---

### Task 2: Add and remove documents in ConversationService

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/application/conversation_service.py`
- Modify: `backend/src/smart_tutor/tutoring/domain/document_used.py`
- Modify: `backend/src/smart_tutor/tutoring/domain/errors.py`
- Modify: `backend/src/smart_tutor/tutoring/application/__init__.py`
- Modify: `backend/src/smart_tutor/tutoring/README.md`
- Test: `backend/tests/unit/tutoring/test_conversation_service.py`

**Interfaces:**
- Consumes: Task 1's `ThreadRepository.add_documents`, `remove_document`, `ThreadDocument.added_by`, `.first_used_at`; existing `DocumentService.documents_by_id(user_id, ids) -> dict[DocumentId, DocumentView]` (`DocumentView.state`, `.archived`).
- Produces:
  - `DocumentNotAvailableError(DomainError)` in `tutoring/domain/errors.py`, exported from `tutoring.application`.
  - `DocumentUsed` gains `added_by: AddedBy` and `used: bool` (new trailing fields, keyword-passed).
  - `ConversationService.add_documents(thread_id, user_id, document_ids: Sequence[DocumentId]) -> list[DocumentUsed]` — raises `ThreadNotFoundError` / `DocumentNotAvailableError("Document not found")`; returns the updated list.
  - `ConversationService.remove_document(thread_id, user_id, document_id) -> None` — raises `ThreadNotFoundError`.

- [ ] **Step 1: Failing tests** (append; reuse the file's `service`, `started` helpers, `ingest_ready`, `FixedClock`; read them first and match their style):

```python
def test_the_learner_adds_ready_documents_listed_as_added_and_unused() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock(NOW)
    used = ingest_ready(library, "learner-a", "Attention weighs tokens.")
    added = ingest_ready(library, "learner-a", "Gradient descent follows the slope.")
    conversations = service(library, threads, clock)
    thread = conversations.start_thread(UserId("learner-a"))
    t = ThreadId(thread.thread_id)
    conversations.record_answer(t, UserId("learner-a"), [DocumentId(used)])

    listed = conversations.add_documents(t, UserId("learner-a"), [DocumentId(added), DocumentId(used)])

    assert [(d.document_id, d.added_by, d.used) for d in listed] == [(used, "answer", True), (added, "learner", False)]
    conversations.record_answer(t, UserId("learner-a"), [DocumentId(added)])
    assert [d.used for d in conversations.documents_used(t, UserId("learner-a"))] == [True, True]


@pytest.mark.parametrize("kind", ["foreign", "archived", "processing", "unknown"])
def test_only_the_learners_ready_active_documents_can_be_added(kind: str) -> None:
    ...  # build: a ready doc of learner-b ("foreign"); a ready doc of learner-a then archived (use the library
    # fake's archive path the existing archived tests use); a processing doc of learner-a; a random uuid.
    # conversations.add_documents(t, learner-a, [good, bad]) raises DocumentNotAvailableError
    # and conversations.documents_used(t, learner-a) == []  (nothing added: all-or-nothing)


def test_removing_a_document_takes_it_off_the_list_until_an_answer_uses_it_again() -> None:
    # record_answer [a, b]; remove_document(a) -> list is [b]; the document a still exists in the library;
    # record_answer [a] -> list is [b, a] with a.added_by == "answer".
    ...


def test_another_learner_can_neither_add_nor_remove() -> None:
    # learner-b on learner-a's thread: add_documents and remove_document raise ThreadNotFoundError; list unchanged.
    ...
```

The `...` bodies above are to be written in full by the implementer following the comments exactly; look at `test_an_archived_only_learner_cannot_start_a_thread` and `test_a_processing_document_is_not_enough_to_start_a_thread` for how the fakes produce archived and processing documents.

- [ ] **Step 2: Run** `uv run pytest tests/unit/tutoring/test_conversation_service.py -v` — Expected: FAIL.

- [ ] **Step 3: Implement.** `errors.py`:

```python
class DocumentNotAvailableError(DomainError):
    """The document isn't the learner's ready, non-archived document, so it can't join a conversation (US-4c)."""
```

`document_used.py`: module/class docstring "A document in the conversation's list, as the learner sees it now (US-4b, US-4c)."; add fields `added_by: AddedBy` and `used: bool` after `deleted`.

`conversation_service.py` — refactor the row→view mapping into `_views(user_id, rows)`, used by `documents_used` and `add_documents`; pass `added_by=row.added_by, used=row.first_used_at is not None` to both `DocumentUsed(...)` constructions:

```python
    def add_documents(
        self, thread_id: ThreadId, user_id: UserId, document_ids: Sequence[DocumentId]
    ) -> list[DocumentUsed]:
        """The learner adds documents to the list (US-4c): each must be their ready, non-archived document
        (`can_read`), or nothing is added."""
        self._owned(thread_id, user_id)
        ids = list(dict.fromkeys(document_ids))
        views = self._documents.documents_by_id(user_id, ids)
        if any((v := views.get(i)) is None or v.state != "ready" or v.archived for i in ids):
            raise DocumentNotAvailableError("Document not found")
        self._threads.add_documents(thread_id, ids, self._clock.now())
        return self._views(user_id, self._threads.documents_used(thread_id))

    def remove_document(self, thread_id: ThreadId, user_id: UserId, document_id: DocumentId) -> None:
        """Take a document off the list; the document and old citations to it are unchanged (US-4c)."""
        self._owned(thread_id, user_id)
        self._threads.remove_document(thread_id, document_id)
```

with `_owned` raising `ThreadNotFoundError("Conversation not found")` (replace the three copies of that check). Update module docstring to mention US-4c. Export `DocumentNotAvailableError` in `application/__init__.py`.

`tutoring/README.md` "Built so far": add "the learner's additions and removals (`add_documents`, only their ready, non-archived documents; `remove_document`); rows record `added_by`".

- [ ] **Step 4: Run** the unit tests, `uv run mypy`, `PYTHONUTF8=1 uv run lint-imports`. Expected: PASS.

- [ ] **Step 5: Commit** — "Let the learner add and remove a conversation's documents" (body: US-4c; the `can_read` check is in code through `documents_by_id`, all-or-nothing so a refused id never half-adds).

---

### Task 3: API endpoints, isolation tests, regenerated client

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py`
- Test: `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py`
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`

**Interfaces:**
- Consumes: Task 2's `ConversationService.add_documents`, `remove_document`, `DocumentNotAvailableError`, `DocumentUsed.added_by`, `.used`.
- Produces (OpenAPI):
  - `POST /threads/{thread_id}/documents`, `operation_id="add_thread_documents"`, body `AddThreadDocumentsRequest {document_ids: list[UUID] (1..50)}`, `200 -> list[ThreadDocumentResponse]`, `404`.
  - `DELETE /threads/{thread_id}/documents/{document_id}`, `operation_id="remove_thread_document"`, `204`, `404`.
  - `ThreadDocumentResponse` gains `added_by: Literal["answer", "learner"]` and `used: bool`.
  - Generated SDK functions `addThreadDocuments`, `removeThreadDocument`.

- [ ] **Step 1: Failing route tests** (append to `test_thread_routes.py`, using its `setup`/`ask_with`/`documents_of` helpers — read them first):
  - adding two of the learner's ready documents returns 200 and the list with both `added_by == "learner"`, `used is False`; GET returns the same.
  - an empty `document_ids` and a non-UUID id are `422`; an unknown field is `422`.
  - DELETE of a listed document is `204` and GET no longer lists it; DELETE of an unlisted document is `204`.
  - an unknown thread id is `404` on both.
  - the existing GET test now also asserts `added_by == "answer"` and `used is True`.

- [ ] **Step 2: Failing isolation tests** (append to `tests/isolation/test_threads.py`, following `test_only_the_owner_lists_a_threads_documents_used`):

```python
def test_a_learner_can_add_only_their_own_ready_active_documents() -> None:
    # learner-a asks (thread started). Then POST /threads/{t}/documents as A with:
    #   [b_document]                     -> 404, response text contains neither B's title nor id
    #   [a_ready, b_document]            -> 404, GET as A lists nothing new (all-or-nothing)
    #   [a_archived], [a_processing]     -> 404
    #   [a_ready]                        -> 200
    # Use ingest_ready for ready documents; for archived/processing follow how tests/fakes and other isolation
    # tests produce them (grep tests/ for "archived" and "processing").


def test_only_the_owner_adds_or_removes_a_threads_documents() -> None:
    # As B on A's thread: POST with B's own ready document -> 404; DELETE of A's listed document -> 404;
    # GET as A still lists it.
```

The implementer writes these in full per the comments.

- [ ] **Step 3: Run** `uv run pytest tests/unit/apps/api/test_thread_routes.py tests/isolation -v` — Expected: FAIL.

- [ ] **Step 4: Implement routes** (in `threads.py`, after `list_thread_documents`; update the module docstring to say the learner adds and removes documents too):

```python
class AddThreadDocumentsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: Annotated[list[uuid.UUID], Field(min_length=1, max_length=50)]


def _response(d: DocumentUsed) -> ThreadDocumentResponse:
    return ThreadDocumentResponse(
        document_id=d.document_id, title=d.title, authors=list(d.authors), year=d.year,
        archived=d.archived, deleted=d.deleted, added_by=d.added_by, used=d.used,
    )


@router.post(
    "/threads/{thread_id}/documents",
    operation_id="add_thread_documents",
    responses={404: {"description": "Not the caller's conversation, or a document that isn't their ready one."}},
)
def add_thread_documents(
    thread_id: uuid.UUID, body: AddThreadDocumentsRequest, principal: CurrentPrincipal, conversations: Conversations
) -> list[ThreadDocumentResponse]:
    """Add the learner's ready, non-archived documents to the conversation's list (PRD US-4c); returns the list."""
    try:
        listed = conversations.add_documents(
            ThreadId(str(thread_id)), principal.user_id, [DocumentId(str(d)) for d in body.document_ids]
        )
    except (ThreadNotFoundError, DocumentNotAvailableError) as e:
        raise HTTPException(404, str(e)) from None
    return [_response(d) for d in listed]


@router.delete(
    "/threads/{thread_id}/documents/{document_id}",
    operation_id="remove_thread_document",
    status_code=204,
    responses={404: {"description": "Not the caller's conversation."}},
)
def remove_thread_document(
    thread_id: uuid.UUID, document_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations
) -> None:
    """Take a document off the conversation's list (PRD US-4c); the document and old citations are unchanged."""
    try:
        conversations.remove_document(ThreadId(str(thread_id)), principal.user_id, DocumentId(str(document_id)))
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
```

Add `added_by: Literal["answer", "learner"]` and `used: bool` to `ThreadDocumentResponse`; make `list_thread_documents` use `_response`. Imports: `Field`, `Literal`, `DocumentUsed`, `DocumentNotAvailableError` from `smart_tutor.tutoring.application`. Use `ruff format` (the compact `_response` above is not formatted).

- [ ] **Step 5: Run** backend checks from Global Constraints. Expected: PASS.

- [ ] **Step 6: Regenerate the client** — read the `api-client` target in the root `Makefile` and run its command (from the repo root on Windows Git Bash). Confirm `git diff --stat web/src/api` shows `openapi.json`, `generated/sdk.gen.ts`, `generated/types.gen.ts` with `addThreadDocuments`/`removeThreadDocument`. Run `cd web && npm run build` (existing panel code must still compile; `ThreadDocumentResponse` fixtures in web tests may need `added_by`/`used` — add `added_by: "answer", used: true` to them).

- [ ] **Step 7: Commit** — "Add and remove a conversation's documents through the API" (body: owner only; a document must be the caller's ready, non-archived one, else 404 with nothing added).

---

### Task 4: Web — Add documents picker and remove buttons

**Files:**
- Modify: `web/src/api/chat.ts`, `web/src/api/chat.test.ts`
- Create: `web/src/features/chat/DocumentPicker.tsx`, `DocumentPicker.module.css`, `DocumentPicker.test.tsx`
- Modify: `web/src/features/chat/ConversationPanel.tsx`, `ConversationPanel.module.css`, `ConversationPanel.test.tsx`
- Modify: `web/src/features/chat/ChatPage.tsx`, `ChatPage.test.tsx`

**Interfaces:**
- Consumes: generated `addThreadDocuments`, `removeThreadDocument`, `ThreadDocumentResponse` (with `added_by`, `used`); `loadDocuments({ state: "ready" })` from `web/src/api/documents.ts` (returns the learner's non-archived documents in that state); `Dialog`, `Button`, `IconButton` components.
- Produces:
  - `addThreadDocuments(threadId: string, documentIds: string[], apiClient?): Promise<ThreadDocumentResponse[]>` and `removeThreadDocument(threadId: string, documentId: string, apiClient?): Promise<void>` in `api/chat.ts` (same error style as `loadDocumentsUsed`: `SessionExpiredError` on session over, else `Error`). The SDK name clash: import the generated ones as `addThreadDocumentsSdk` / `removeThreadDocumentSdk`.
  - `DocumentPicker` props: `{ listedIds: ReadonlySet<string>; loadReady: () => Promise<DocumentResponse[]>; onAdd: (ids: string[]) => Promise<void>; onClose: () => void }`.
  - `ConversationPanel` new props: `onAddDocuments?: () => void` (button shown only when given and `threadId !== null`), `onRemoveDocument?: (documentId: string) => void`, and an exported ref handle is NOT needed: the panel finds focus targets itself (see Step 5).
  - `ChatPage` new optional props for tests: `loadReady`, `addDocs`, `removeDoc` with defaults calling the API functions.

- [ ] **Step 1: API wrapper tests** (in `chat.test.ts`, follow its existing `loadDocumentsUsed` tests' fake-client style): POST sends `{document_ids}` to `/threads/t1/documents` and returns the list; DELETE hits `/threads/t1/documents/d1`; a 401 throws `SessionExpiredError`; a 404 throws `Error`. Implement in `chat.ts`. Run `npx vitest run src/api/chat.test.ts` → PASS.

- [ ] **Step 2: DocumentPicker tests** (`DocumentPicker.test.tsx`):
  - renders a dialog named "Add documents"; the search box ("Search your documents") has focus.
  - lists the ready documents from `loadReady`; a listed one is checked, disabled, and its meta reads "In this conversation"; others show "authors · year".
  - typing filters by title, case-insensitive; no match shows "No ready documents match.".
  - "Add" is disabled until one is checked; checking two makes it "Add 2 documents"; clicking calls `onAdd(["id1","id2"])` in list order.
  - `onAdd` rejecting shows "Couldn't add the documents. Try again." (role `alert`) and keeps the selection and the dialog; `loadReady` rejecting shows "Your documents couldn't be loaded." .
  - "Cancel" calls `onClose`.

- [ ] **Step 3: Implement DocumentPicker**

```tsx
import { useEffect, useMemo, useState } from "react";

import type { DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { Dialog } from "../../components/Dialog/Dialog";
import styles from "./DocumentPicker.module.css";

type Props = {
  listedIds: ReadonlySet<string>;
  loadReady: () => Promise<DocumentResponse[]>;
  onAdd: (ids: string[]) => Promise<void>;
  onClose: () => void;
};

function byline(d: DocumentResponse): string {
  return [d.authors.join(", "), d.year === null ? "" : String(d.year)].filter(Boolean).join(" · ");
}

// "Add documents" (PRD US-4c): a searchable list of the learner's ready documents; listed ones are checked and fixed.
export function DocumentPicker({ listedIds, loadReady, onAdd, onClose }: Props) {
  const [docs, setDocs] = useState<DocumentResponse[] | "failed" | null>(null);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string[]>([]);
  const [adding, setAdding] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let current = true;
    loadReady().then((d) => current && setDocs(d), () => current && setDocs("failed"));
    return () => {
      current = false;
    };
  }, [loadReady]);

  const shown = useMemo(() => {
    if (!Array.isArray(docs)) return [];
    const q = query.trim().toLowerCase();
    return q ? docs.filter((d) => d.title.toLowerCase().includes(q)) : docs;
  }, [docs, query]);

  function toggle(id: string, on: boolean) {
    setSelected((s) => (on ? [...s, id] : s.filter((x) => x !== id)));
  }

  async function add() {
    setAdding(true);
    setFailed(false);
    try {
      const order = Array.isArray(docs) ? docs.map((d) => d.document_id) : [];
      await onAdd(order.filter((id) => selected.includes(id)));
    } catch {
      setFailed(true);
      setAdding(false);
    }
  }

  const n = selected.length;
  return (
    <Dialog
      title="Add documents"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={n === 0 || adding} onClick={() => void add()}>
            {n === 0 ? "Add" : n === 1 ? "Add 1 document" : `Add ${n} documents`}
          </Button>
        </>
      }
    >
      <input
        className={styles.search} type="search" placeholder="Search your documents" aria-label="Search your documents"
        value={query} onChange={(e) => setQuery(e.target.value)} data-autofocus
      />
      {docs === "failed" ? (
        <p className={styles.empty}>Your documents couldn't be loaded.</p>
      ) : (
        <ul className={styles.list} aria-label="Your ready documents" aria-busy={docs === null}>
          {docs !== null && shown.length === 0 && <li className={styles.empty}>No ready documents match.</li>}
          {shown.map((d) => {
            const listed = listedIds.has(d.document_id);
            return (
              <li key={d.document_id}>
                <label className={styles.row}>
                  <input
                    type="checkbox" checked={listed || selected.includes(d.document_id)} disabled={listed}
                    onChange={(e) => toggle(d.document_id, e.target.checked)}
                  />
                  <span className={styles.title} title={d.title}>{d.title}</span>
                  <span className={styles.meta}>{listed ? "In this conversation" : byline(d)}</span>
                </label>
              </li>
            );
          })}
        </ul>
      )}
      {failed && <p role="alert" className={styles.error}>Couldn't add the documents. Try again.</p>}
    </Dialog>
  );
}
```

Check `Button`'s real prop names (`variant` values) in `web/src/components/Button/Button.tsx` and the `DocumentResponse` field names (`document_id`, `title`, `authors`, `year`) in `types.gen.ts`, and adapt. CSS (`DocumentPicker.module.css`) with tokens only, following `DESIGN.md` compact density: search input full width (reuse the input look used elsewhere — grep `web/src` for an existing `.input` style or the Library search and match it); list `max-height: 320px; overflow-y: auto`; rows 36px, grid `auto minmax(0,1fr)` with title truncated and meta in `--text-2`, `--fs-12`; `.row:has(input:disabled)` text in `--text-2`; `.error` in the danger token used by other forms. Run the picker tests → PASS.

- [ ] **Step 4: ConversationPanel tests** (extend `ConversationPanel.test.tsx`):
  - with `threadId="t1"` and `onAddDocuments`, an "Add documents" button (`aria-haspopup="dialog"`) calls it; with `threadId={null}` there is no such button.
  - a learner row with `used: false` shows "Added"; a used learner row and answer rows don't.
  - each row has a button named "Remove {title} from this conversation" (deleted rows too) that calls `onRemoveDocument(id)`.
  - focus: render with rows a, b; focus b's remove button; rerender without b (simulating the parent's update after `onRemoveDocument("b")`): focus is on a's remove button. Rerender without any rows after removing the last: focus is on "Add documents". With rows a, b, removing a: focus on b's remove button.

- [ ] **Step 5: Implement ConversationPanel changes**
  - Import `Plus`, `X` from `lucide-react`; `IconButton` from `../../components/Button/IconButton` (check its props: `label`, `icon`, `tip`).
  - Each `<li>`: existing content, then `{d.used === false && d.added_by === "learner" && !d.deleted && !d.archived && <span className={styles.badge}>Added</span>}` (keep the Deleted/Archived badges taking precedence), then `<IconButton className={styles.remove} label={`Remove ${d.title} from this conversation`} tip="Remove from this conversation" icon={X} size="sm" onClick={() => remove(d.document_id)} data-remove={d.document_id} />` — adapt to `IconButton`'s actual props; if it doesn't take a custom tooltip text, use `title`.
  - Under the list: `{onAddDocuments && threadId !== null && <Button variant="quiet" size="sm" icon={Plus} className={styles.action} aria-haspopup="dialog" ref={addRef} onClick={onAddDocuments}>Add documents</Button>}` (check `Button` forwards refs and extra props; if not, find it by a `data-add-documents` attribute via a section ref).
  - Focus after remove: `remove(id)` stores the target id: the next row's id, else the previous row's, else `"add"`, in a ref, then calls `onRemoveDocument(id)`. A `useEffect` on `documents` moves focus to `[data-remove="<target>"]` or the Add button when the stored target is set and the removed row is gone, then clears it.
  - Announce the removal: a visually hidden `role="status"` region in the panel, text "{title} removed from this conversation." (grep `web/src` for an existing visually-hidden class like `vh`/`srOnly` and reuse it).
  - CSS: `.remove { opacity: 0; }` `.row:hover .remove, .row:focus-within .remove { opacity: 1; }` `@media (hover: none) { .remove { opacity: 1; } }`; the row stays 32px (use a 24px icon button). Update the component's doc comment (rows: remove button; Add documents).
  - Run panel tests → PASS.

- [ ] **Step 6: ChatPage wiring + tests**
  - State: `pickerOpen` boolean; a live `announcement` string for "N documents added to this conversation." (or reuse the panel's status region by passing it down — keep one status region in ChatPage if one exists already; grep `role="status"` in ChatPage).
  - `onAddDocuments={() => setPickerOpen(true)}`; render `{pickerOpen && threadId && <DocumentPicker listedIds={new Set(used.map(d => d.document_id))} loadReady={loadReady} onAdd={async ids => { const list = await addDocs(threadId, ids); if (turn is unchanged) setUsed(list); setUsedFailed(false); setPickerOpen(false); announce } } onClose={() => setPickerOpen(false)} />}`. A `SessionExpiredError` from `addDocs` was reported by the client already; let it reject so the picker shows its error (the session screen replaces the page anyway).
  - `onRemoveDocument={async id => { setUsed(u => u.filter(d => d.document_id !== id)); try { await removeDoc(threadId, id) } catch { reload the list with loadUsed(threadId) so the panel shows the truth; on SessionExpiredError do nothing } }}` — optimistic removal keeps the focus logic simple.
  - Defaults: `const defaultLoadReady = () => loadDocuments({ state: "ready" });`, `defaultAddDocs = (t, ids) => addThreadDocuments(t, ids)`, `defaultRemoveDoc = (t, id) => removeThreadDocument(t, id)` at module level (stable identities, like the existing defaults).
  - ChatPage tests (follow the file's existing fake `ask`/`loadUsed` style): after an answer, "Add documents" → picker → check one → "Add 1 document" → `addDocs` called with `(thread, [id])`, panel lists it with "Added", dialog closed, focus on "Add documents". `addDocs` rejecting keeps the dialog open with the error. Remove: clicking a row's remove button calls `removeDoc(thread, id)` and the row disappears; `removeDoc` rejecting reloads the list (row comes back). The citations of the answer are unchanged after removal (assert a citation for the removed document still renders).
  - Run `npx vitest run src/features/chat` → PASS; `npm run build` → PASS.

- [ ] **Step 7: Visual check** — `make design-shots ROUND=v0.10 STATES="chat-documents-add,chat-documents-used" THEME=both` (or the Makefile's command) and compare with the running app if it can be run (`make web` against a running API); otherwise compare against the code and say so in the report.

- [ ] **Step 8: Commit** — "Add documents to a conversation from a picker, and remove them" (body: US-4c web; focus returns to Add documents or the next row; Add documents waits for the thread).

---

### Task 5: Finish

- [ ] Run every check in Global Constraints; `git status` clean except intended files.
- [ ] PRD: no behavior change beyond US-4c v2.22 (already specified) — no PRD edit. If the implementation diverged from §9.4 (it should not), update §9.4 and bump the version.
- [ ] Open a PR into `main` titled "Add and remove documents in a conversation (#130)", body: summary, "Closes #130", the "Add documents waits for the thread" prototype divergence, test evidence, and `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.

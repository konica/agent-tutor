# Reopen a conversation with its history (#187) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A learner leaves a conversation and comes back to it at `/chat/<thread_id>` with every question, answer, citation, and decline they saw, plus its title, documents used, and search scope.

**Architecture:** Backend: a tutoring-owned table `thread_turns` (migration 0014) keeps each turn that ended with `done`: question, answer text, citations as `(n, document_id, chunk_id, page)` in JSONB, or the decline `(code, message)`, and the owner's `user_id`. The API's SSE relay already sees every event; it now gathers the answer's deltas, citations, and decline and, on `done`, calls `ConversationService.record_turn`, which stores the turn and the documents used in one transaction. `GET /threads/{id}/turns` returns the turns oldest first through owner-scoped SQL, with citation titles resolved at read time (display title, archived, or "Deleted document"). Web: Chat gets the route `chat/:threadId?`; a new conversation moves to its URL on the `thread` event; opening a URL loads the thread, its turns, and its documents; the page shows a list of turns instead of one exchange.

**Tech Stack:** FastAPI, SQLAlchemy Core + Alembic (PostgreSQL JSONB), React 19 + TypeScript, react-router 8 (optional segment `:threadId?`), Vitest + Testing Library.

**Spec:** GitHub issue #187 (parent #23 US-13); PRD v2.34 §8 US-13 ("open with history"), US-4b (a turn counts only when its answer is saved), §9.2 step 4 ("Each answer stores its citations as `(document_id, chunk_id, page)`; titles resolve at read time"), §9.4 Thread / Thread document; `DESIGN.md` → Chat; mockup `design-v0.10` state `conversations-open` (stacked turns: question bubble, answer, Sources line). Render: `cd web && npm run design:shots -- --states "conversations-open" --round v0.10 --theme both`.

## Global Constraints

- A turn is kept **only** when the agent's stream ends with `done` and the thread started. `error`, a stream that ends without `done`, or a stream dropped inside an event keeps nothing (no turn, no documents used).
- A decline is a kept turn: `answer` `""`, no citations, `decline_code`/`decline_message` set. The fixed no-chunks answer is a kept turn with its text and no citations.
- Stored per turn: `turn_id` (identity, the order), `thread_id` (FK `threads` ON DELETE CASCADE), `user_id` (the thread's owner), `question`, `answer`, `citations` JSONB list of `{"n", "document_id", "chunk_id", "page"}`, `decline_code`, `decline_message`, `created_at`. **No** document title, chunk text, token, prompt, or any user id other than the owner column. **No** foreign key to `documents`.
- Reads go through owner-scoped SQL: `WHERE thread_id = :thread AND user_id = :owner`. Another learner's or an unknown thread is `404 "Conversation not found"`; a malformed id is `422` (FastAPI's UUID path check).
- Citation at read time: the learner's display title and `archived` from `DocumentService.documents_by_id`; a document that no longer exists → `document_title` `"Deleted document"`, `deleted: true`, `archived: false`.
- Copy (verbatim): "Conversation not found" (heading), "This conversation doesn't exist, or it isn't yours." (body), "Back to Chat" (link to `/chat`), "This conversation couldn't be loaded. Reload the page to try again." (load failure), "Archived" (badge inside a history chip).
- The web calls the API only through `src/api/`; regenerate `web/src/api/` after the route lands: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Build UI with existing components and tokens; never paste prototype HTML/CSS.
- Out of scope: multi-turn model context (US-4); how questions are asked stays as today, so an unlimited follow-up still starts a new conversation (and moves to its new URL).
- **Integration tests must not touch the developer's Compose database** (`smart_tutor`, shared with the main checkout; migration 0014 would leave it at a revision `main` doesn't know). Run them against a scratch database:
  ```bash
  docker exec smart-tutor-postgres-1 psql -U smart_tutor -d postgres -c "CREATE DATABASE smart_tutor_it187" || true
  cd backend && SMART_TUTOR_DATABASE_URL=postgresql+psycopg://smart_tutor:smart_tutor@localhost:10400/smart_tutor_it187 uv run pytest -m integration tests/integration/tutoring -v
  ```
- Backend checks (from `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Line length 120, mypy strict. Web (from `web/`): `npx vitest run && npm run build`.
- Commits: imperative subject, body says why, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A citation the agent sent malformed** (missing `document_id`, a non-UUID `document_id`, `n` not an int, `page` a string): that citation is skipped with one warning and the rest of the turn is kept; the stream the learner sees is unchanged. A non-UUID id must never reach `documents_by_id`. Pinned in Task 3 ("a malformed citation is skipped and the turn is kept").
2. **The learner navigates to another conversation (Back, or the Chat nav) while an answer streams**: the old stream's later events must not land in the newly shown conversation. Pinned in Task 4 ("leaving for another conversation mid-answer drops the old stream's events").
3. **Reload of `/chat/<id>` for a conversation whose only document was deleted, or a learner with no ready documents left**: the history still shows (no "Upload a document first" take-over while a conversation is open from its URL). Pinned in Task 4 ("a reopened conversation shows its history even with no ready documents").
4. **Two turns cite the same chunk** (same `chunk_id` in different turns): React keys and the "shown" chip must stay per turn, so opening one chip highlights only that chip. Pinned in Task 4 ("the same passage cited in two turns highlights only the clicked chip").
5. **Owner scoping in SQL, not just the service check**: `turns(thread_id, other_user)` returns `[]` even for an existing thread. Pinned in Task 2 (integration) and Task 3 (isolation route test).

---

### Task 1: Turn domain, repository port, fake, and ConversationService

**Files:**
- Create: `backend/src/smart_tutor/tutoring/domain/turn.py`
- Modify: `backend/src/smart_tutor/tutoring/ports/thread_repository.py`
- Modify: `backend/src/smart_tutor/tutoring/application/conversation_service.py` (replace `record_answer` with `record_turn`; add `turns`)
- Modify: `backend/src/smart_tutor/tutoring/application/__init__.py` (export new names)
- Modify: `backend/tests/fakes/tutoring.py` (`add_turn`, `turns`)
- Modify: `backend/src/smart_tutor/tutoring/adapters/sql_threads.py` — only add stubs raising `NotImplementedError` for `add_turn` and `turns` so the ABC still instantiates (Task 2 implements them)
- Test: `backend/tests/unit/tutoring/test_conversation_service.py`, `backend/tests/unit/tutoring/test_turns_fake.py`

**Interfaces:**
- Produces (domain, all frozen dataclasses in `tutoring/domain/turn.py`, exported from `smart_tutor.tutoring.application`):
  - `TurnCitation(n: int, document_id: DocumentId, chunk_id: str, page: int | None)`
  - `Decline(code: str, message: str)`
  - `Turn(thread_id: ThreadId, user_id: UserId, question: str, answer: str, citations: tuple[TurnCitation, ...], decline: Decline | None, created_at: datetime)`
  - `AnsweredTurn(question: str, answer: str = "", citations: tuple[TurnCitation, ...] = (), decline: Decline | None = None, document_ids: tuple[DocumentId, ...] = ())`
  - `CitationView(n: int, document_id: DocumentId, chunk_id: str, page: int | None, title: str, archived: bool, deleted: bool)`
  - `TurnView(question: str, answer: str, citations: tuple[CitationView, ...], decline: Decline | None, created_at: datetime)`
- Produces (port `ThreadRepository`): `add_turn(turn: Turn, document_ids: Sequence[DocumentId]) -> None`; `turns(thread_id: ThreadId, user_id: UserId) -> list[Turn]`.
- Produces (service): `ConversationService.record_turn(thread_id: ThreadId, user_id: UserId, turn: AnsweredTurn) -> None`; `ConversationService.turns(thread_id: ThreadId, user_id: UserId) -> list[TurnView]` (raises `ThreadNotFoundError` "Conversation not found").
- Removes: `ConversationService.record_answer` (its only caller, the thread routes, moves to `record_turn` in Task 3; until then update that one call site to `record_turn(tid, user_id, AnsweredTurn("", document_ids=tuple(DocumentId(d) for d in document_ids)))` so the suite stays green — Task 3 replaces it properly). Keep the `_FailingRecord` test in `test_thread_routes.py` compiling by renaming its override to `record_turn(self, thread_id, user_id, turn: AnsweredTurn)`.

- [ ] **Step 1: Write the domain file**

```python
"""A kept turn of a thread (PRD §9.4 Thread turn, US-13): the question, then the answer and its citations, or the
decline. Only a turn whose answer ended with `done` is kept (US-4b). Citations are ids and a page; titles resolve at
read time, so a deleted document's citation reads "Deleted document"."""

from dataclasses import dataclass
from datetime import datetime

from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId


@dataclass(frozen=True)
class TurnCitation:
    """What an answer's [n] marker points at."""

    n: int
    document_id: DocumentId
    chunk_id: str
    page: int | None


@dataclass(frozen=True)
class Decline:
    code: str
    message: str


@dataclass(frozen=True)
class Turn:
    thread_id: ThreadId
    user_id: UserId  # the thread's owner; reads are scoped by it
    question: str
    answer: str  # empty for a decline
    citations: tuple[TurnCitation, ...]
    decline: Decline | None
    created_at: datetime


@dataclass(frozen=True)
class AnsweredTurn:
    """What the learner saw of one answer that ended with `done`, and the documents it drew on."""

    question: str
    answer: str = ""
    citations: tuple[TurnCitation, ...] = ()
    decline: Decline | None = None
    document_ids: tuple[DocumentId, ...] = ()


@dataclass(frozen=True)
class CitationView:
    """A kept citation as the learner sees it now: display title, or "Deleted document"."""

    n: int
    document_id: DocumentId
    chunk_id: str
    page: int | None
    title: str
    archived: bool
    deleted: bool


@dataclass(frozen=True)
class TurnView:
    question: str
    answer: str
    citations: tuple[CitationView, ...]
    decline: Decline | None
    created_at: datetime
```

- [ ] **Step 2: Add the port methods** to `ThreadRepository`:

```python
    @abstractmethod
    def add_turn(self, turn: Turn, document_ids: Sequence[DocumentId]) -> None:
        """Keep the turn and add `document_ids` to the thread's documents used at `turn.created_at`, as
        `add_documents_used` does, in one transaction (committed when this returns). (Callers check ownership first.)"""

    @abstractmethod
    def turns(self, thread_id: ThreadId, user_id: UserId) -> list[Turn]:
        """The thread's kept turns, oldest first; empty unless the thread is this learner's (scoped by owner)."""
```

- [ ] **Step 3: Write failing fake tests** in `backend/tests/unit/tutoring/test_turns_fake.py`:

```python
"""InMemoryThreads keeps turns per owner, oldest first, with the documents of each turn."""

from datetime import UTC, datetime

from fakes import InMemoryThreads
from smart_tutor.shared.domain.ids import DocumentId, ThreadId, UserId
from smart_tutor.tutoring.application import Decline, Thread, Turn, TurnCitation

T0 = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
ADA, BOB = UserId("ada"), UserId("bob")
D1 = DocumentId("00000000-0000-4000-8000-000000000001")


def started() -> tuple[InMemoryThreads, ThreadId]:
    threads = InMemoryThreads()
    thread = Thread.start(ThreadId("00000000-0000-4000-8000-0000000000a1"), ADA, T0, title="Q1")
    threads.add(thread)
    return threads, ThreadId(thread.thread_id)


def test_turns_are_kept_oldest_first_for_the_owner_only() -> None:
    threads, t = started()
    first = Turn(t, ADA, "Q1", "A1 [1].", (TurnCitation(1, D1, "c1", 3),), None, T0)
    second = Turn(t, ADA, "Q2", "", (), Decline("limited", "These documents don't cover this."), T0)
    threads.add_turn(first, [D1])
    threads.add_turn(second, [])

    assert threads.turns(t, ADA) == [first, second]
    assert threads.turns(t, BOB) == []
    assert [row.document_id for row in threads.documents_used(t)] == [D1]
```

- [ ] **Step 4: Run** `cd backend && uv run pytest tests/unit/tutoring/test_turns_fake.py -v` — Expected: FAIL (`ImportError` for `Decline`/`Turn`, or abstract methods).

- [ ] **Step 5: Implement the fake** in `backend/tests/fakes/tutoring.py` (add `self.turn_rows: list[Turn] = []` in `__init__`):

```python
    def add_turn(self, turn: Turn, document_ids: Sequence[DocumentId]) -> None:
        self.turn_rows.append(turn)
        self.add_documents_used(turn.thread_id, document_ids, turn.created_at)

    def turns(self, thread_id: ThreadId, user_id: UserId) -> list[Turn]:
        return [t for t in self.turn_rows if t.thread_id == thread_id and t.user_id == user_id]
```

Add stubs to `SqlThreadRepository` (`raise NotImplementedError("Task 2")`) so it still instantiates; export the six domain classes from `tutoring/application/__init__.py` (keep `__all__` sorted).

- [ ] **Step 6: Write failing service tests** in `test_conversation_service.py`. First add a helper next to `service(...)` and move every existing `svc.record_answer(t, u, [a, b])` call to `svc.record_turn(t, u, answered(a, b))` (same assertions; `record_turn` keeps the documents-used behavior, including dedupe and the ownership 404):

```python
def answered(*document_ids: DocumentId) -> AnsweredTurn:
    return AnsweredTurn("What is attention?", "It weighs tokens.", document_ids=document_ids)
```

Then add:

```python
def test_record_turn_keeps_the_turn_with_its_time_and_owner() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    doc = DocumentId(ingest_ready(library, "ada", "Attention weighs tokens."))
    svc = service(library, threads, clock)
    thread = svc.start_thread(LEARNER, "What is attention?")
    citation = TurnCitation(1, doc, "c1", 3)

    svc.record_turn(ThreadId(thread.thread_id), LEARNER, AnsweredTurn("What is attention?", "It weighs [1].", (citation,), document_ids=(doc, doc)))

    [kept] = threads.turn_rows
    assert kept == Turn(ThreadId(thread.thread_id), LEARNER, "What is attention?", "It weighs [1].", (citation,), None, clock.now())
    assert [row.document_id for row in threads.documents_used(ThreadId(thread.thread_id))] == [doc]


def test_record_turn_in_another_learners_thread_is_not_found_and_keeps_nothing() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention weighs tokens.")
    svc = service(library, threads, clock)
    thread = svc.start_thread(LEARNER, "Q")

    with pytest.raises(ThreadNotFoundError):
        svc.record_turn(ThreadId(thread.thread_id), OTHER, AnsweredTurn("Q", "A"))
    assert threads.turn_rows == []


def test_turns_resolve_citations_now_archived_and_deleted() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    kept_doc = DocumentId(ingest_ready(library, "ada", "Attention weighs tokens."))
    gone = DocumentId("00000000-0000-4000-8000-000000000999")
    svc = service(library, threads, clock)
    t = ThreadId(svc.start_thread(LEARNER, "Q1").thread_id)
    svc.record_turn(t, LEARNER, AnsweredTurn("Q1", "A [1] [2].", (TurnCitation(1, kept_doc, "c1", 3), TurnCitation(2, gone, "c9", None))))
    svc.record_turn(t, LEARNER, AnsweredTurn("Q2", decline=Decline("limited", "These documents don't cover this.")))
    library.state.documents[kept_doc].archived = True

    first, second = svc.turns(t, LEARNER)

    title = library.state.documents[kept_doc].file_name  # the display title before extraction
    assert first.question == "Q1" and first.answer == "A [1] [2]." and first.decline is None
    assert first.citations == (
        CitationView(1, kept_doc, "c1", 3, title, archived=True, deleted=False),
        CitationView(2, gone, "c9", None, DELETED_DOCUMENT, archived=False, deleted=True),
    )
    assert second.answer == "" and second.citations == ()
    assert second.decline == Decline("limited", "These documents don't cover this.")


def test_turns_of_another_learners_thread_are_not_found() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention weighs tokens.")
    svc = service(library, threads, clock)
    t = ThreadId(svc.start_thread(LEARNER, "Q").thread_id)

    with pytest.raises(ThreadNotFoundError):
        svc.turns(t, OTHER)
```

(Check how existing tests in this file read a document's display title — if they use a helper or `view.title`, use the same; `LEARNER`/`OTHER` are the file's existing constants.)

- [ ] **Step 7: Run** `uv run pytest tests/unit/tutoring -v` — Expected: FAIL (`record_turn`/`turns` missing).

- [ ] **Step 8: Implement** in `ConversationService` (remove `record_answer`):

```python
    def record_turn(self, thread_id: ThreadId, user_id: UserId, turn: AnsweredTurn) -> None:
        """Keep a turn whose answer ended with `done` (US-13) with the documents it drew on (US-4b), together.
        A decline draws on none."""
        self._owned(thread_id, user_id)
        kept = Turn(thread_id, user_id, turn.question, turn.answer, turn.citations, turn.decline, self._clock.now())
        self._threads.add_turn(kept, list(dict.fromkeys(turn.document_ids)))

    def turns(self, thread_id: ThreadId, user_id: UserId) -> list[TurnView]:
        """The thread's turns, oldest first, citations resolved now: display title and archived, or "Deleted
        document" for one that no longer exists."""
        self._owned(thread_id, user_id)
        kept = self._threads.turns(thread_id, user_id)
        views = self._documents.documents_by_id(
            user_id, list(dict.fromkeys(c.document_id for t in kept for c in t.citations))
        )
        return [
            TurnView(
                t.question,
                t.answer,
                tuple(_citation(c, views.get(c.document_id)) for c in t.citations),
                t.decline,
                t.created_at,
            )
            for t in kept
        ]
```

and a module-level helper (import `DocumentView` the way `_views` already gets it — via `documents_by_id`'s return type from `smart_tutor.knowledge.application`; if it isn't exported there, type the parameter with the attributes used through a small `Protocol` or reuse whatever `_views` uses):

```python
def _citation(c: TurnCitation, view: DocumentView | None) -> CitationView:
    if view is None:
        return CitationView(c.n, c.document_id, c.chunk_id, c.page, DELETED_DOCUMENT, archived=False, deleted=True)
    return CitationView(c.n, c.document_id, c.chunk_id, c.page, view.title, archived=view.archived, deleted=False)
```

Update the one call in `apps/api/routes/threads.py` (`_recorder`) to `conversations.record_turn(tid, user_id, AnsweredTurn("", document_ids=tuple(DocumentId(d) for d in document_ids)))` (temporary; Task 3 replaces it), and the `_FailingRecord` override in `test_thread_routes.py` to `def record_turn(self, thread_id: ThreadId, user_id: UserId, turn: AnsweredTurn) -> None:`.

- [ ] **Step 9: Run** the full backend checks (Global Constraints). Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add backend/src/smart_tutor/tutoring backend/src/smart_tutor/apps/api/routes/threads.py backend/tests
git commit -m "Keep a conversation's turns in tutoring and read them back resolved

Reopening a conversation needs what the learner saw: each question, its answer and
citations, or the decline (#187). The service stores a done turn together with the
documents it drew on and resolves citation titles at read time.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `thread_turns` table and SQL repository

**Files:**
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0014_thread_turns.py`
- Modify: `backend/src/smart_tutor/tutoring/adapters/sql_threads.py` (table, `add_turn`, `turns`; factor the documents-used upsert into a helper both `add_documents_used` and `add_turn` use)
- Test: `backend/tests/integration/tutoring/test_sql_threads.py`

**Interfaces:**
- Consumes: `Turn`, `TurnCitation`, `Decline` (Task 1); port methods `add_turn`, `turns`.
- Produces: table `thread_turns`; `SqlThreadRepository.add_turn` / `.turns`.

- [ ] **Step 1: Write the migration**

```python
"""Thread turns: what a conversation's learner saw, for reopening it (PRD §9.4 Thread turn, US-13; ADR 0015).

Only turns whose answer ended with `done`. Citations are (n, document_id, chunk_id, page); titles resolve at read
time. No foreign key to documents, so turns outlive a deleted document. `user_id` is the thread's owner, for
owner-scoped reads.

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "thread_turns",
        sa.Column("turn_id", sa.BigInteger, sa.Identity(always=True), primary_key=True),
        sa.Column(
            "thread_id",
            sa.Uuid(as_uuid=False),
            sa.ForeignKey("threads.thread_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("question", sa.Text, nullable=False),
        sa.Column("answer", sa.Text, nullable=False),
        sa.Column("citations", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("decline_code", sa.Text),
        sa.Column("decline_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("(decline_code IS NULL) = (decline_message IS NULL)", name="thread_turns_decline_pair"),
    )
    op.create_index("thread_turns_thread_idx", "thread_turns", ["thread_id", "turn_id"])


def downgrade() -> None:
    op.drop_table("thread_turns")
```

- [ ] **Step 2: Write failing integration tests** (append to `test_sql_threads.py`; import `thread_turns` too):

```python
def test_turns_round_trip_oldest_first_for_the_owner_only(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC), title="Q1")
    repo.add(thread)
    doc = DocumentId(str(uuid.uuid4()))  # no row in documents: turns don't reference it
    t0 = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
    first = Turn(thread.thread_id, owner, "Q1", "A [1].", (TurnCitation(1, doc, "c1", 3), TurnCitation(2, doc, "c2", None)), None, t0)
    second = Turn(thread.thread_id, owner, "Q2", "", (), Decline("limited", "These documents don't cover this."), t0)

    repo.add_turn(first, [doc])
    repo.add_turn(second, [])

    assert repo.turns(thread.thread_id, owner) == [first, second]
    assert repo.turns(thread.thread_id, UserId("bob")) == []
    assert [row.document_id for row in repo.documents_used(thread.thread_id)] == [doc]


def test_a_turn_row_holds_no_title_or_text_beyond_what_the_learner_saw(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC))
    repo.add(thread)
    doc = DocumentId(str(uuid.uuid4()))
    repo.add_turn(Turn(thread.thread_id, owner, "Q", "A [1].", (TurnCitation(1, doc, "c1", 3),), None, datetime.now(UTC)), [doc])

    columns = {c["name"] for c in inspect(engine).get_columns("thread_turns")}
    assert columns == {"turn_id", "thread_id", "user_id", "question", "answer", "citations", "decline_code", "decline_message", "created_at"}
    with engine.connect() as conn:
        [citations] = conn.execute(select(thread_turns.c.citations).where(thread_turns.c.thread_id == thread.thread_id)).scalars()
    assert citations == [{"n": 1, "document_id": doc, "chunk_id": "c1", "page": 3}]
```

- [ ] **Step 3: Run** the integration tests against the scratch database (Global Constraints). Expected: FAIL (`NotImplementedError` / missing table).

- [ ] **Step 4: Implement** in `sql_threads.py` (update the module docstring to list migration 0014; import `JSONB` from `sqlalchemy.dialects.postgresql`):

```python
thread_turns = Table(
    "thread_turns",
    threads.metadata,
    Column("turn_id", BigInteger, Identity(always=True), primary_key=True),
    Column("thread_id", Uuid(as_uuid=False)),
    Column("user_id", Text),
    Column("question", Text),
    Column("answer", Text),
    Column("citations", JSONB),
    Column("decline_code", Text),
    Column("decline_message", Text),
    Column("created_at", DateTime(timezone=True)),
)


def _add_documents_used(conn: Connection, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
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


def _turn(row: Any) -> Turn:
    decline = Decline(row.decline_code, row.decline_message) if row.decline_code is not None else None
    citations = tuple(TurnCitation(c["n"], DocumentId(c["document_id"]), c["chunk_id"], c["page"]) for c in row.citations)
    return Turn(ThreadId(str(row.thread_id)), UserId(row.user_id), row.question, row.answer, citations, decline, row.created_at)
```

In the class: `add_documents_used` becomes `if not document_ids: return` + `with self._engine.begin() as conn: _add_documents_used(conn, thread_id, document_ids, at)`, and:

```python
    def add_turn(self, turn: Turn, document_ids: Sequence[DocumentId]) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                thread_turns.insert().values(
                    thread_id=turn.thread_id,
                    user_id=turn.user_id,
                    question=turn.question,
                    answer=turn.answer,
                    citations=[
                        {"n": c.n, "document_id": c.document_id, "chunk_id": c.chunk_id, "page": c.page}
                        for c in turn.citations
                    ],
                    decline_code=turn.decline.code if turn.decline else None,
                    decline_message=turn.decline.message if turn.decline else None,
                    created_at=turn.created_at,
                )
            )
            _add_documents_used(conn, turn.thread_id, document_ids, turn.created_at)

    def turns(self, thread_id: ThreadId, user_id: UserId) -> list[Turn]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(thread_turns)
                .where(thread_turns.c.thread_id == thread_id, thread_turns.c.user_id == user_id)
                .order_by(thread_turns.c.turn_id)
            ).all()
        return [_turn(r) for r in rows]
```

- [ ] **Step 5: Run** the integration tests against the scratch database, then the backend checks. Expected: PASS.

- [ ] **Step 6: Commit** — subject "Store conversation turns in thread_turns", body: why (owner-scoped table, no FK to documents so turns outlive a delete, turn and documents used in one transaction).

---

### Task 3: Keep turns from the SSE relay; `GET /threads/{id}/turns`; regenerate the web client

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py`
- Test: `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py`
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`

**Interfaces:**
- Consumes: `ConversationService.record_turn`, `.turns`, `AnsweredTurn`, `TurnCitation`, `Decline`, `TurnView`, `CitationView` (Task 1).
- Produces (HTTP): `GET /threads/{thread_id}/turns`, operation `list_thread_turns`, `200 list[TurnResponse]`, `404` "Conversation not found", `422` malformed id, `401` no token.
  - `TurnResponse { question: str, answer: str, citations: list[TurnCitationResponse], decline: TurnDeclineResponse | null, created_at: datetime }`
  - `TurnCitationResponse { n: int, chunk_id: str, document_id: str, document_title: str, page: int | null, archived: bool, deleted: bool }`
  - `TurnDeclineResponse { code: str, message: str }`
- Produces (web, generated): `listThreadTurns`, `getThread`, types `TurnResponse`, `TurnCitationResponse`, `TurnDeclineResponse`, `ThreadResponse`.

- [ ] **Step 1: Write failing route tests** (append to `test_thread_routes.py`; reuse `ask_with`, `sources`, `DELTA`, `DONE`, `AGENT_ERROR`, `UNAVAILABLE_EVENT`):

```python
def cite(n: int, document_id: str, chunk_id: str = "c1", page: int | None = 3, title: str = "a.pdf") -> dict[str, Any]:
    return {"n": n, "chunk_id": chunk_id, "document_id": document_id, "document_title": title, "page": page}


def citations_event(*items: object) -> bytes:
    return f"event: citations\ndata: {json.dumps({'citations': list(items)})}\n\n".encode()


def turns_of(client: TestClient, threads: InMemoryThreads) -> list[dict[str, Any]]:
    [thread] = threads.threads.values()
    response = client.get(f"/threads/{thread.thread_id}/turns", headers=AUTH)
    assert response.status_code == 200
    body: list[dict[str, Any]] = response.json()
    return body


def test_a_done_answer_is_kept_as_a_turn_with_its_citations() -> None:
    two_deltas = b'event: delta\ndata: {"text": "It weighs "}\n\nevent: delta\ndata: {"text": "tokens [1]."}\n\n'
    client, library, threads, ids = ask_with(lambda ids: two_deltas + sources(ids[0]) + citations_event(cite(1, ids[0])) + DONE)

    client.post("/threads", json=QUESTION, headers=AUTH)

    [turn] = turns_of(client, threads)
    title = library.state.documents[ids[0]].file_name
    assert turn["question"] == "What is attention?" and turn["answer"] == "It weighs tokens [1]." and turn["decline"] is None
    assert turn["citations"] == [
        {"n": 1, "chunk_id": "c1", "document_id": ids[0], "document_title": title, "page": 3, "archived": False, "deleted": False}
    ]
    assert set(turn) == {"question", "answer", "citations", "decline", "created_at"}


def test_a_decline_is_kept_as_a_turn() -> None:
    decline = b'event: decline\ndata: {"code": "limited", "message": "These documents don\'t cover this."}\n\n'
    client, _, threads, _ = ask_with(lambda ids: decline + DONE)

    client.post("/threads", json=QUESTION, headers=AUTH)

    [turn] = turns_of(client, threads)
    assert turn["answer"] == "" and turn["citations"] == []
    assert turn["decline"] == {"code": "limited", "message": "These documents don't cover this."}


@pytest.mark.parametrize(
    "tail", [AGENT_ERROR, b"", b'event: citations\ndata: {"cit'], ids=["error", "clean-end", "inside-an-event"]
)
def test_an_answer_that_doesnt_end_with_done_keeps_no_turn(tail: bytes) -> None:
    client, _, threads, _ = ask_with(lambda ids: DELTA + sources(*ids) + tail)

    client.post("/threads", json=QUESTION, headers=AUTH)

    assert turns_of(client, threads) == []


def test_a_malformed_citation_is_skipped_and_the_turn_is_kept(caplog: pytest.LogCaptureFixture) -> None:
    bad = [
        {"n": 2, "chunk_id": "c2", "document_title": "x", "page": 1},  # no document_id
        cite(3, "not-a-uuid"),
        {**cite(4, str(uuid.uuid4())), "n": "4"},
        {**cite(5, str(uuid.uuid4())), "page": "5"},
    ]
    client, _, threads, ids = ask_with(lambda ids: DELTA + citations_event(cite(1, ids[0]), *bad) + DONE)

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.text.endswith(DONE.decode())
    [turn] = turns_of(client, threads)
    assert [c["n"] for c in turn["citations"]] == [1]
    assert "the agent's citations were partly malformed" in caplog.text


def test_turns_list_oldest_first_and_resolve_archived_and_deleted() -> None:
    gone = UNKNOWN_DOCUMENT
    client, library, threads, ids = ask_with(lambda ids: DELTA + citations_event(cite(1, ids[0]), cite(2, gone, "c9", None)) + DONE)
    client.post("/threads", json=QUESTION, headers=AUTH)
    [thread] = threads.threads.values()
    client.post(f"/threads/{thread.thread_id}/questions", json={"question": "And then?"}, headers=AUTH)
    library.state.documents[ids[0]].archived = True

    first, second = turns_of(client, threads)

    assert [first["question"], second["question"]] == ["What is attention?", "And then?"]
    archived, deleted = first["citations"]
    assert archived["archived"] is True and archived["deleted"] is False
    assert deleted == {"n": 2, "chunk_id": "c9", "document_id": gone, "document_title": "Deleted document", "page": None, "archived": False, "deleted": True}


def test_turns_of_an_unknown_thread_are_404_and_a_malformed_id_is_422() -> None:
    client, _, _ = setup()
    assert client.get(f"/threads/{uuid.uuid4()}/turns", headers=AUTH).status_code == 404
    assert client.get("/threads/not-a-uuid/turns", headers=AUTH).status_code == 422


def test_turns_need_a_token() -> None:
    client, _, _ = setup()
    assert client.get(f"/threads/{uuid.uuid4()}/turns").status_code == 401


def test_openapi_names_the_turns_list() -> None:
    client, _, _ = setup()
    op = client.get("/openapi.json").json()["paths"]["/threads/{thread_id}/turns"]["get"]
    assert op["operationId"] == "list_thread_turns"


def test_a_kept_turn_holds_no_token() -> None:
    client, _, threads, ids = ask_with(lambda ids: DELTA + citations_event(cite(1, ids[0])) + DONE)
    client.post("/threads", json=QUESTION, headers=AUTH)
    [turn] = threads.turn_rows
    assert "t-ada" not in repr(turn) and turn.user_id == "ada"
```

Also update existing tests: rename `test_a_decline_records_nothing` (it has no `sources`, so it records no documents — keep its assertion, rename to `test_an_answer_without_sources_records_no_documents`); `test_a_failed_record_still_ends_with_done` now checks `"keeping the turn failed" in caplog.text` and that `turns_of(...) == []` and documents are empty; `test_a_limited_decline_is_relayed_and_records_nothing` keeps its documents assertion and is renamed `..._and_records_no_documents`.

Isolation, in `backend/tests/isolation/test_threads.py`:

```python
def test_only_the_owner_reads_a_threads_turns() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    services = api_services(library, threads=threads, agent=fake_agent(answers))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [thread] = threads.threads.values()

    mine = client.get(f"/threads/{thread.thread_id}/turns", headers=A)
    theirs = client.get(f"/threads/{thread.thread_id}/turns", headers=B)

    assert [t["question"] for t in mine.json()] == ["What is attention?"]
    assert theirs.status_code == 404 and theirs.json() == {"detail": "Conversation not found"}
    assert threads.turns(ThreadId(thread.thread_id), UserId("learner-b")) == []
```

Update the module docstring of the isolation test to mention `GET /threads/{id}/turns`.

- [ ] **Step 2: Run** `uv run pytest tests/unit/apps/api/test_thread_routes.py tests/isolation/test_threads.py -v` — Expected: FAIL.

- [ ] **Step 3: Implement the relay.** In `threads.py`, replace `RecordAnswer` and the `sources`-only bookkeeping:

```python
@dataclass
class _Seen:
    """What the learner saw of one answer; kept as a turn when it ends with `done`."""

    answer: str = ""
    citations: tuple[TurnCitation, ...] = ()
    decline: Decline | None = None
    document_ids: tuple[DocumentId, ...] = ()


# Keeps the answer as a turn of the thread that started, with its documents used; never raises.
RecordAnswer = Callable[[_Seen], Awaitable[None]]
```

Parsers (each logs a warning and returns the empty value for malformed data; `_document_ids` now returns `tuple[DocumentId, ...]`, `()` when malformed):

```python
def _is_uuid(value: object) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return isinstance(value, str)


def _citation(item: object) -> TurnCitation | None:
    if not isinstance(item, dict):
        return None
    n, chunk_id, document_id, page = item.get("n"), item.get("chunk_id"), item.get("document_id"), item.get("page")
    if not isinstance(n, int) or isinstance(n, bool) or not isinstance(chunk_id, str) or not _is_uuid(document_id):
        return None
    if page is not None and (not isinstance(page, int) or isinstance(page, bool)):
        return None
    return TurnCitation(n, DocumentId(str(document_id)), chunk_id, page)


def _citations(data: object) -> tuple[TurnCitation, ...]:
    """The well-formed citations of a `citations` event; the learner already has the event as sent."""
    items = data.get("citations") if isinstance(data, dict) else None
    if not isinstance(items, list):
        logger.warning("the agent's citations event was malformed")
        return ()
    kept = tuple(c for c in map(_citation, items) if c is not None)
    if len(kept) != len(items):
        logger.warning("the agent's citations were partly malformed")
    return kept


def _decline(data: object) -> Decline | None:
    code = data.get("code") if isinstance(data, dict) else None
    message = data.get("message") if isinstance(data, dict) else None
    if not isinstance(code, str) or not isinstance(message, str):
        logger.warning("the agent's decline event was malformed")
        return None
    return Decline(code, message)


def _delta(data: object) -> str:
    text = data.get("text") if isinstance(data, dict) else None
    return text if isinstance(text, str) else ""
```

In `_relay`'s loop, replace the `document_ids` variable with `seen = _Seen()` and:

```python
            parsed = _event(event)
            name = parsed[0] if parsed else None
            if parsed and name == "sources":
                seen.document_ids = _document_ids(parsed[1])
            else:
                if parsed and name == "delta":
                    seen.answer += _delta(parsed[1])
                elif parsed and name == "citations":
                    seen.citations = _citations(parsed[1])
                elif parsed and name == "decline":
                    seen.decline = _decline(parsed[1])
                if name == "done" and started:
                    await record(seen)
                ended = name in ("done", "error")
                yield event
```

Update `_relay`'s docstring ("on `done`, if the thread started, the turn and its documents are kept before `done` is forwarded"). `_recorder` takes the question:

```python
def _recorder(
    conversations: Conversations, user_id: UserId, question: str, thread_id: Callable[[], ThreadId | None]
) -> RecordAnswer:
    """Keeps an answer as a turn of the thread `thread_id()` gives (None: none started, so nothing to keep)."""

    async def record(seen: _Seen) -> None:
        tid = thread_id()
        if tid is None:
            return
        turn = AnsweredTurn(question, seen.answer, seen.citations, seen.decline, seen.document_ids)
        try:
            await run_in_threadpool(conversations.record_turn, tid, user_id, turn)
        except Exception:
            # The learner already has the answer: log it and still end the stream with `done`.
            logger.exception("keeping the turn failed")

    return record
```

Both ask routes pass `body.question` (the stripped question) to `_recorder`. Update the module docstring (turns are kept and listed per thread).

- [ ] **Step 4: Add the read route**

```python
class TurnCitationResponse(BaseModel):
    n: int
    chunk_id: str
    document_id: str
    document_title: str
    page: int | None
    archived: bool
    deleted: bool


class TurnDeclineResponse(BaseModel):
    code: str
    message: str


class TurnResponse(BaseModel):
    question: str
    answer: str
    citations: list[TurnCitationResponse]
    decline: TurnDeclineResponse | None
    created_at: datetime


def _turn_response(t: TurnView) -> TurnResponse:
    return TurnResponse(
        question=t.question,
        answer=t.answer,
        citations=[
            TurnCitationResponse(
                n=c.n,
                chunk_id=c.chunk_id,
                document_id=c.document_id,
                document_title=c.title,
                page=c.page,
                archived=c.archived,
                deleted=c.deleted,
            )
            for c in t.citations
        ],
        decline=TurnDeclineResponse(code=t.decline.code, message=t.decline.message) if t.decline else None,
        created_at=t.created_at,
    )


@router.get(
    "/threads/{thread_id}/turns",
    operation_id="list_thread_turns",
    responses={404: {"description": "Not the caller's conversation."}},
)
def list_thread_turns(
    thread_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations
) -> list[TurnResponse]:
    """The conversation's turns, oldest first: each question with its answer and citations, or its decline (PRD
    US-13). Citations resolve now: display title, archived, or "Deleted document"."""
    try:
        turns = conversations.turns(ThreadId(str(thread_id)), principal.user_id)
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    return [_turn_response(t) for t in turns]
```

- [ ] **Step 5: Run** the route and isolation tests, then the full backend checks. Expected: PASS except `test_openapi_snapshot`.

- [ ] **Step 6: Regenerate the web client** (Global Constraints command). Then `cd backend && uv run pytest tests/unit/apps/api/test_openapi_snapshot.py` → PASS, and `cd web && npm run build` → PASS.

- [ ] **Step 7: Commit** — subject "Keep each finished answer as a turn and list a conversation's turns", body: why (US-13 open with history; only `done` turns; malformed citations skipped so the learner's stream is never affected).

---

### Task 4: Web — conversation URL, reopen with history, not found

**Files:**
- Modify: `web/src/api/chat.ts` (types, `loadConversation`, `ConversationNotFoundError`)
- Test: `web/src/api/chat.test.ts`
- Modify: `web/src/app/routes.tsx` (`chat/:threadId?`), `web/src/app/routes.test.tsx`
- Modify: `web/src/features/chat/ChatPage.tsx`, `web/src/features/chat/ChatPage.module.css`
- Test: `web/src/features/chat/ChatPage.test.tsx`

**Interfaces:**
- Consumes (generated, Task 3): `getThread`, `listThreadTurns`, `ThreadResponse`, `TurnResponse`.
- Produces: `export type Conversation = { thread: ThreadResponse; turns: TurnResponse[] }`; `export class ConversationNotFoundError extends Error`; `export async function loadConversation(threadId: string, apiClient?: Client): Promise<Conversation>`; `ChatCitation` gains optional `archived?: boolean; deleted?: boolean`; `ChatPage` prop `loadConversation?: (threadId: string) => Promise<Conversation>`.

- [ ] **Step 1: API client test, then code.** In `chat.test.ts`, following the file's existing pattern for faking the client, test: (a) 200 for both → `{ thread, turns }`; (b) 404 on either → rejects with `ConversationNotFoundError`; (c) 422 → `ConversationNotFoundError`; (d) 401 → `SessionExpiredError`; (e) 500 → plain `Error`. Implement:

```ts
export type { ThreadResponse, TurnResponse };
export type Conversation = { thread: ThreadResponse; turns: TurnResponse[] };

/** 404 (unknown, or another learner's) or 422 (not a conversation id) from a conversation's URL. */
export class ConversationNotFoundError extends Error {
  constructor() {
    super("Conversation not found");
    this.name = "ConversationNotFoundError";
  }
}

// A conversation at its URL: its title and scope, and its turns oldest first (owner only).
export async function loadConversation(threadId: string, apiClient: Client = client): Promise<Conversation> {
  const path = { thread_id: threadId };
  const [thread, turns] = await Promise.all([
    getThread({ client: apiClient, path, throwOnError: false }),
    listThreadTurns({ client: apiClient, path, throwOnError: false }),
  ]);
  for (const { error, response } of [thread, turns]) {
    if (sessionOver(error, response)) throw new SessionExpiredError();
    if (response?.status === 404 || response?.status === 422) throw new ConversationNotFoundError();
  }
  if (!thread.data || !turns.data) throw new Error(`GET /threads/${threadId} failed (${thread.response?.status ?? turns.response?.status ?? "no response"})`);
  return { thread: thread.data, turns: turns.data };
}
```

and extend `ChatCitation` with `archived?: boolean; deleted?: boolean` (set only by history; a live citation has neither).

- [ ] **Step 2: Route.** In `routes.tsx` change the chat route to `{ path: "chat/:threadId?", element: <ChatPage />, handle: { bleed: true } }` (one route, so moving from `/chat` to `/chat/<id>` keeps the page mounted while the answer streams). In `routes.test.tsx` add: rendering `/chat/t1` shows the chat page inside the shell and the "Chat" nav entry is the current page (mirror the existing `/chat` test's assertions; `loadConversation` reaches the mocked network — mock `../api/chat`'s `loadConversation` like the file mocks `../api/documents`).

- [ ] **Step 3: Update the ChatPage test harness** so `useParams` sees the route, and expose the location:

```tsx
function Location() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname + location.search}</output>;
}

function renderChat(props: ComponentProps<typeof ChatPage> = {}, entry = "/chat") {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <Routes>
        <Route path="/chat/:threadId?" element={<ChatPage loadDocs={async () => [doc("ready")]} loadUsed={async () => []} {...props} />} />
      </Routes>
      <Location />
      <Link to="/chat">Chat</Link>
    </MemoryRouter>,
  );
}
```

Move the existing `Location`/`startChatAt` helpers to use this (one `Location`). All existing tests must still pass unchanged.

- [ ] **Step 4: Write the failing ChatPage tests** (new `describe("a conversation at its URL")`):

```tsx
const turn = (over: Partial<TurnResponse> = {}): TurnResponse => ({
  question: "What is attention?",
  answer: "It weighs tokens [1].",
  citations: [{ n: 1, chunk_id: "c1", document_id: "d1", document_title: "a.pdf", page: 3, archived: false, deleted: false }],
  decline: null,
  created_at: "2026-10-10T09:00:00Z",
  ...over,
});
const conversation = (turns: TurnResponse[], over: Partial<ThreadResponse> = {}) =>
  vi.fn(async () => ({ thread: { thread_id: "t1", title: "Attention basics", search_scope: "library" as const, ...over }, turns }));
const usedDoc: ThreadDocumentResponse = { document_id: "d1", title: "a.pdf", authors: [], year: null, archived: false, deleted: false, added_by: "answer", used: true };
```

Tests:
1. **"opens a conversation at its URL with its title, history, documents used, and scope"** — `renderChat({ loadConversation: conversation([turn(), turn({ question: "And in RAG?", answer: "", citations: [], decline: { code: "limited", message: "These documents don't cover this." } })], { search_scope: "listed" }), loadUsed: async () => [usedDoc] }, "/chat/t1")`. Expect: `loadConversation` called with `"t1"`; the title button "Attention basics. Edit title"; both "You asked:" bubbles in order; "It weighs tokens [1]."; the decline text; one Sources list with `[1] a.pdf · p. 3`; the scope line "Searching 1 document"; the welcome section is absent.
2. **"a history citation opens the document beside the conversation at its page"** — with `viewerDeps={fakeViewerDeps(...)}` as the existing chip test does, click the chip; expect the document pane (same assertions the existing Sources-chip test uses) and the chip `aria-current="true"`.
3. **"a deleted document's history citation reads Deleted document with no link"** — citation `{ ..., document_title: "Deleted document", deleted: true }`: text `[1] Deleted document`, no button for it.
4. **"an archived document's history citation says Archived and still opens"** — `archived: true`: the chip button's accessible name contains "Archived" and the chip shows the text "Archived"; clicking opens the pane.
5. **"an unknown conversation shows Conversation not found with a way back to Chat"** — `loadConversation: vi.fn(async () => { throw new ConversationNotFoundError(); })` at `/chat/nope`: heading "Conversation not found", the body copy, link "Back to Chat" with `href="/chat"`; no composer.
6. **"a conversation that can't be loaded says so"** — rejects with `new Error("boom")`: "This conversation couldn't be loaded. Reload the page to try again."
7. **"a new conversation moves to its URL when its thread is created, and keeps streaming"** — `controlledStream` as in the existing param test: ask at `/chat`, push `thread t1` → location `/chat/t1`; push a delta → it renders; `loadConversation` was never called.
8. **"an unlimited question in a reopened conversation starts a new conversation at a new URL"** — open `/chat/t1` (scope library, one turn); ask "Next?" with `ask` yielding `thread t2`, delta, done → location `/chat/t2`; the old turn's text is gone; only "Next?" is shown; `ask` (not `askIn`) was called.
9. **"a question in a limited conversation adds a turn under the history"** — open `/chat/t1` with `search_scope: "listed"`, `loadUsed` → `[usedDoc]`; ask "More?" with `askIn` yielding `thread t1`, delta "More.", done → both questions shown in order, "It weighs tokens [1]." and "More." both present; location stays `/chat/t1`; `askIn` called with `("t1", "More?")`.
10. **"the Chat link starts a new conversation"** — open `/chat/t1`, click the test's `Chat` link → welcome "Ask about your documents" shows, history gone, title "New conversation".
11. **"leaving for another conversation mid-answer drops the old stream's events"** — at `/chat`, ask with a `controlledStream`, push `thread t1` (location `/chat/t1`), click the `Chat` link; push `delta "Late."` → "Late." never appears (`expect(screen.queryByText("Late.")).not.toBeInTheDocument()` after `await act(async () => {})`).
12. **"a reopened conversation shows its history even with no ready documents"** — `loadDocs: async () => []`, at `/chat/t1` with one turn: the history shows, no "Upload a document first" heading.
13. **"the same passage cited in two turns highlights only the clicked chip"** — two turns citing `chunk_id: "c1"`; click the second turn's chip → only that chip has `aria-current="true"`.

Run `npx vitest run src/features/chat src/api/chat.test.ts src/app` — Expected: the new tests FAIL.

- [ ] **Step 5: Implement ChatPage.** Keep everything else as is; the changes:

(a) **Turns instead of one exchange.** `const [turns, setTurns] = useState<Exchange[]>([])`. A new thread replaces: `setTurns([{ question: text, answer: "", citations: [], declined: null }])`; a question in a thread appends. Event handlers update the last turn through one helper:

```ts
const updateLast = (change: (e: Exchange) => Exchange) =>
  setTurns((list) => (list.length === 0 ? list : [...list.slice(0, -1), change(list[list.length - 1]!)]));
```

`exchange` references become `turns.length > 0` (welcome) and `last = turns.at(-1)` (decline actions, `searchAll(threadId, last.question)`). Render one block per turn (key = index) with the existing question / answer / decline / Sources markup; the decline card's actions ("Add documents", "Search all my documents") and the `problem` line render only for the last turn; earlier declined turns show only their message. The `aria-live` answer region wraps only the last turn's answer (history must not be announced). The "shown" chip: store `shownCitation: { turn: number; chunkId: string } | null` alongside the viewer (set in `openCitation`, cleared when a panel row opens a document or the viewer closes), and compare both turn index and chunk id.

(b) **Citations from history.** `Exchange.citations` stays `ChatCitation[]` (now with optional `archived`/`deleted`). A chip is "deleted" when `c.deleted || deletedIds.has(c.document_id)`. An archived chip adds, after the page, a badge `<span className={styles.sourceBadge}>Archived</span>` and its accessible name reads `` `${title}, ${pageText}, archived. ${shown ? "Shown beside the conversation" : "Open beside the conversation"}` ``. CSS (`ChatPage.module.css`), matching DESIGN.md's archived look:

```css
.sourceBadge {
  margin-left: var(--space-1);
  padding: 0 var(--space-1);
  border: 1px dashed var(--border-strong);
  border-radius: var(--radius-sm);
  background: var(--surface-2);
  color: var(--text-2);
  font-size: var(--text-xs);
}
```

(use the token names that exist in `web/src/styles/tokens.css` — check them; don't invent new tokens).

(c) **URL ↔ conversation.** `const { threadId: routeThreadId } = useParams(); const navigate = useNavigate();` and a ref `shown = useRef<string | null>(null)` holding the conversation the page shows (by URL or just created). On a `thread` event while asking in a **new** thread: `shown.current = event.thread_id; navigate(`/chat/${event.thread_id}`)` (a push, so Back returns to the previous conversation) — do this before `setThreadId`. Then:

```ts
// The URL names the conversation. A change the page made itself (a new thread's URL) is already shown; any other
// change (reload, Back, a pasted link, the Chat nav) opens that conversation, or a new one at /chat.
useEffect(() => {
  const target = routeThreadId ?? null;
  if (target === shown.current) return;
  shown.current = target;
  if (target === null) startOver();
  else void openConversation(target);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- runs only when the URL changes
}, [routeThreadId]);
```

`startOver()` and the start of `openConversation()` share a `reset()` that does what `answer()` does today for a new thread (`++turn.current`, clear used/usedFailed/threadId/firstQuestion/renamed/answered/picker/scope, close the viewer) plus `setTurns([])`, `setProblem(null)`, `setOpened({ status: "none" })`. New state: `type Opened = { status: "none" | "loading" | "not-found" | "failed" }`.

```ts
async function openConversation(id: string) {
  reset();
  const forTurn = turn.current;
  setOpened({ status: "loading" });
  try {
    const { thread, turns } = await loadConversation(id);
    if (!alive.current || turn.current !== forTurn) return;
    setThreadId(thread.thread_id);
    setFirstQuestion(thread.title ?? null);
    setScope(thread.search_scope);
    setTurns(turns.map((t) => ({ question: t.question, answer: t.answer, citations: t.citations, declined: t.decline?.message ?? null })));
    setAnswered(turns.length > 0);
    setOpened({ status: "none" });
    void showDocumentsUsed(thread.thread_id, forTurn);
  } catch (error) {
    if (!alive.current || turn.current !== forTurn || error instanceof SessionExpiredError) return;
    setOpened({ status: error instanceof ConversationNotFoundError ? "not-found" : "failed" });
  }
}
```

`showDocumentsUsed` must not override the scope set from the thread: it calls `showList`, which only turns the scope off for an empty list — the same rule the server applies, so it agrees.

(d) **Stale streams.** In `run()`, stop reading when the page has moved on: `if (!alive.current || turn.current !== thisTurn) break;` at the top of the loop, and guard the post-loop `setProblem`/`setAnswered`/`showDocumentsUsed` and the `catch` the same way. (A question in the same thread keeps `turn.current`, so it is unaffected.)

(e) **Library and take-overs.** `loadDocs` success always sets `library` ready and sets `noDocuments` when none is ready. The "Upload a document first" take-over shows only when no conversation is open from the URL: `if (noDocuments && routeThreadId === undefined)`. In `run()`'s `catch`, a `NoDocumentsError` inside a reopened conversation shows `setProblem({ message: error.message })` instead of the take-over. Order of early returns: library `ended` → `null`; `opened.status === "not-found"` → the not-found view; `opened.status === "failed"` → the header "Conversation" plus the failure line (reuse the `fallback`/`problem` markup used for a failed library load); then the existing library loading/failed fallback; then the page. While `opened.status === "loading"`, render the page with an empty history (no welcome) — the welcome shows only when `turns.length === 0 && routeThreadId === undefined`.

Not-found view (existing components only):

```tsx
<div className={styles.fallback}>
  <div className={styles.column}>
    <EmptyState
      icon={MessageSquareX}
      title="Conversation not found"
      actions={
        <LinkButton to="/chat" variant="primary" icon={MessageSquare}>
          Back to Chat
        </LinkButton>
      }
    >
      This conversation doesn't exist, or it isn't yours.
    </EmptyState>
  </div>
</div>
```

(check `EmptyState` renders `title` as a heading, as the "Upload a document first" test expects).

- [ ] **Step 6: Run** `cd web && npx vitest run && npm run build` — Expected: PASS (all old and new tests).

- [ ] **Step 7: Look at it.** Render the mockup (`conversations-open`) and compare with the running page's structure in a test render if no dev stack is up; the stacked turns use the existing question/answer/Sources styles. Fix spacing between turns with the existing spacing tokens only (e.g. a `.turn + .turn { margin-top: var(--space-6) }` rule using an existing token).

- [ ] **Step 8: Commit** — subject "Open a conversation at its own URL with its history", body: why (US-13 reopen; a new conversation moves to its URL on `thread`; one route keeps the page mounted while streaming).

---

### Task 5: Docs — PRD, ADR, module README, CONTEXT

**Files:**
- Modify: `sdd/prd.md` (status line v2.34 → v2.35, new "Changes from v2.34" row, §9.4 new row "Thread turn" right after "Thread document", §9.2 step 4 one clause)
- Create: `sdd/adr/0015-conversation-history-in-tutoring-table.md`
- Modify: `sdd/adr/README.md` (index row, if it lists ADRs)
- Modify: `backend/src/smart_tutor/tutoring/README.md` (Built so far: turns, `record_turn`, `turns`)
- Modify: `AGENTS.md` (ADR range `0001–0014` → `0001–0015`; PRD version `v2.34` → `v2.35`)

- [ ] **Step 1: PRD.** §9.4 row:

`| Thread turn | PostgreSQL `thread_turns` | `turn_id` (identity; the order) | `thread_id`, `user_id` (the thread's owner; reads are scoped by it), `question`, `answer` (empty for a decline), `citations` (JSONB list of `n`, `document_id`, `chunk_id`, `page`; titles resolve at read time), `decline_code` and `decline_message` (a declined turn), `created_at`. Only turns whose answer ended with `done` (US-4b). No foreign key to `documents`, so turns outlive a deleted document; deleted with their thread. Read by the API to reopen a conversation (US-13) and, with US-4, as the capped history (ADR 0015). |`

"Changes from v2.34" row: `Reopen a conversation (#187, US-13): each turn whose answer ends with `done` is kept in `thread_turns` (question, answer, citations as ids and page, or the decline); `error` or a dropped stream keeps nothing. `GET /threads/{id}/turns` (operation `list_thread_turns`) returns the owner's turns oldest first with citations resolved now (display title, `archived`, or "Deleted document" with `deleted`); another learner's thread is `404`. The web opens a conversation at `/chat/<thread_id>`: a new conversation moves to its URL once its thread starts; reload, Back, or a pasted link shows its title, history, documents used, and search scope; an unknown or another learner's conversation shows "Conversation not found" with "Back to Chat". History lives in tutoring, not the LangGraph checkpointer (ADR 0015).` Bump the status line to `Draft v2.35`.

- [ ] **Step 2: ADR 0015** (follow the format of `sdd/adr/0011-per-learner-contents.md`: Status, Context, Decision, Consequences). Content: *Context* — US-13 needs a conversation's history; the ask graph is single turn with no checkpointer (#31); US-4 multi-turn will read capped history. *Decision* — history lives in a tutoring-owned PostgreSQL table `thread_turns`, written by the API when an answer ends with `done`, read through owner-scoped SQL; the LangGraph checkpointer is not used for history. *Why* — the API already sees every event and owns the thread, so one place enforces "only saved turns count" (US-4b) and `can_read`-style owner scoping in SQL; checkpoints hold graph state (retrieved chunk text) that PRD §9.2 says must not be kept, are keyed by thread without an owner column, and are opaque to SQL listing, filtering, and retention; citations stay ids so deletes need no rewrite. *Consequences* — multi-turn chat (US-4) passes the last N turns from this table to the agent in the ask request (capped), still without a checkpointer; a new table to migrate; turns are deleted only with their thread (threads are kept).

- [ ] **Step 3: README / AGENTS.md** updates as listed. tutoring README "Built so far" gains: "conversation history: `ConversationService.record_turn` keeps a turn whose answer ended with `done` (question, answer, citations as ids and page, or the decline) with its documents used in one transaction, as `Turn` rows (`thread_turns`); `turns` reads them oldest first through owner-scoped SQL and resolves citations now (title, archived, or "Deleted document")". Add "Turn" to the Key classes line.

- [ ] **Step 4: Commit** — subject "Record conversation history in the PRD and ADR 0015".

---

## Self-review notes

- Spec coverage: keep turns (Tasks 1–3), read history 404/owner SQL (Tasks 1–3), URL + reload + not found + history citations open the pane (Task 4), PRD + ADR (Task 5), isolation test (Task 3), no token stored (Task 2 columns test, Task 3 token test), regenerate client (Task 3), web reload-and-open and not-found tests (Task 4).
- Type names used across tasks: `TurnCitation`, `Decline`, `Turn`, `AnsweredTurn`, `CitationView`, `TurnView`, `record_turn`, `turns`, `add_turn`, `list_thread_turns`, `TurnResponse`, `loadConversation`, `ConversationNotFoundError`.

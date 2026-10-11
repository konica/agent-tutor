# List my conversations (#188) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Conversations page lists the learner's active conversations, newest activity first (title, subjects of the documents used, number of documents, last activity); a row opens the conversation at `/chat/<id>`, and the side nav shows the three most recent.

**Architecture:** Backend: `ThreadRepository` gains an owner-scoped `list_owned` (newest last activity first), a batched `documents_used_by_thread`, and `set_last_learner_message_at`; `ConversationService.list_threads` builds `ThreadSummary` values whose subjects are the `subject_id`s of the thread's listed documents that still exist (archived included, deleted excluded; D11, Q63 L1), resolved to names in the route through `SubjectNames.names_for` (the personal-name seam). A question asked in an existing thread now updates `last_learner_message_at` (`ConversationService.note_question`), so "last activity" moves. `GET /threads` (operation `list_threads`) returns the list. Web: the app shell owns one conversations list (context, reloaded on every navigation and on demand) that feeds both the side nav's recent conversations and the new Conversations page; Chat asks it to refresh after a rename and after an answer finishes.

**Tech Stack:** FastAPI, SQLAlchemy Core (PostgreSQL), React 19 + TypeScript, react-router, Vitest + Testing Library, CSS modules with `DESIGN.md` tokens.

**Spec:** GitHub issue #188 (parent #23 US-13); PRD v2.36 §8 US-13 ("List conversations (title, subjects of its documents used, last activity), newest first"), D11 (a conversation's subjects are those of its documents used that still exist, archived included, read at query time), Q63 L1 (a deleted document's subjects no longer count), §9.4 Thread (`last_learner_message_at`); design brief §6.7; mockups `design-v0.10` states `conversations-active`, `conversations-empty`. Render: `cd web && npm run design:shots -- --states "conversations-active,conversations-empty" --round v0.10 --theme both` (PNGs in `.design-shots/v0.10/`).

## Global Constraints

- **Owner only, in SQL:** `list_owned` filters `threads.user_id = :owner`; another learner's threads never appear, even with shared subjects or the same uploaded file (US-12).
- **Active only** for now: `status = 'active'`. No Archived tab, no filters, no search, no note indicator, no answer preview in this slice (each is its own slice; the mockup's preview text is not in the brief or the ticket: note the difference in the PR).
- **Last activity** = `last_learner_message_at`, falling back to `created_at` when null. Order: last activity descending, then `created_at` descending, then `thread_id` ascending (stable).
- `last_learner_message_at` is set when a thread starts (already) **and** now each time `POST /threads/{id}/questions` passes its checks (owner, not archived, has ready documents), before the agent is called.
- **Subjects of a row:** the `subject_id`s of the thread's listed documents (`thread_documents`, in list order) that still exist for the learner (archived included), de-duplicated in first-seen order. A deleted document contributes none. Names resolve at read time via `SubjectNames.names_for(user_id, ids)`; an id with no name is skipped. The API returns all of them; the web shows at most two chips, then "+N".
- **Documents of a row:** the number of rows in the thread's document list (what the conversation panel lists, deleted ones included).
- **Title:** the stored title (the first question until renamed); it may be `null` (a thread started without a question): the web shows "Untitled conversation".
- Copy (verbatim): page title "Conversations"; count "1 conversation" / "N conversations"; info "Your past conversations."; header action "New conversation" (goes to `/chat`); column headers "Conversation", "Subjects of documents used", "Documents", "Last activity"; empty state heading "No conversations yet", body "Ask a question about your documents. Every conversation is saved here so you can come back to it.", action "Start a conversation" (goes to `/chat`); load failure "Can't load your conversations. Reload the page to try again."; no subjects "None yet"; side-nav list label "Recent conversations" (exists).
- Last activity format, in the app time zone `Asia/Ho_Chi_Minh` (`APP_TIME_ZONE`), 24-hour: today → "Today, 09:48"; yesterday → "Yesterday, 16:20"; this year → "30 Sep"; other years → "30 Sep 2025" (`en-GB`).
- The web calls the API only through `src/api/`. Regenerate the client after the route lands: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Build UI with `src/components/` and tokens from `DESIGN.md` (read it before writing UI); never paste prototype HTML/CSS.
- **Integration tests must not touch the developer's Compose database** (`smart_tutor`). Use a scratch database:
  ```bash
  docker exec smart-tutor-postgres-1 psql -U smart_tutor -d postgres -c "CREATE DATABASE smart_tutor_it188" || true
  cd backend && SMART_TUTOR_DATABASE_URL=postgresql+psycopg://smart_tutor:smart_tutor@localhost:10400/smart_tutor_it188 uv run pytest -m integration tests/integration/tutoring -v
  ```
- Backend checks (from `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Line length 120, mypy strict. Web checks (from `web/`): `npx vitest run && npm run build`. Windows Git Bash: `PYTHONUTF8=1` for lint-imports.
- Commits: imperative subject, body says why, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A thread's only document was deleted; another is archived:** the deleted one's subjects drop out, the archived one's stay, and the documents count still includes both. Pinned in Task 1 ("deleted documents' subjects don't count; archived ones do").
2. **Two documents share a subject:** one chip, not two. Pinned in Task 1 ("a subject shared by two documents appears once").
3. **A later question in an old conversation:** that conversation moves to the top. Pinned in Task 3 ("asking in a thread makes it the newest").
4. **Stale reload in the shell:** a slow earlier load must not overwrite a newer one (rename, then navigate). Pinned in Task 4 ("a stale load doesn't overwrite a newer one").
5. **A thread with no title (null):** the row and the side nav read "Untitled conversation" and still open it. Pinned in Task 5 ("an untitled conversation reads Untitled conversation").

---

## File Structure

Backend
- Create `backend/src/smart_tutor/tutoring/domain/thread_summary.py` — `ThreadSummary` (one row of the list).
- Modify `backend/src/smart_tutor/tutoring/domain/thread.py` — `Thread.last_activity`, `Thread.ask(now)`.
- Modify `backend/src/smart_tutor/tutoring/ports/thread_repository.py` — `list_owned`, `documents_used_by_thread`, `set_last_learner_message_at`.
- Modify `backend/src/smart_tutor/tutoring/application/conversation_service.py` — `list_threads`, `note_question`.
- Modify `backend/src/smart_tutor/tutoring/application/__init__.py` — export `ThreadSummary`.
- Modify `backend/tests/fakes/tutoring.py` — fake implementations.
- Modify `backend/src/smart_tutor/tutoring/adapters/sql_threads.py` — SQL implementations.
- Modify `backend/src/smart_tutor/apps/api/routes/threads.py` — `GET /threads`; `ask_in_thread` calls `note_question`.
- Tests: `backend/tests/unit/tutoring/test_thread.py`, `test_conversation_service.py`, `backend/tests/integration/tutoring/test_sql_threads.py`, `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py`; OpenAPI snapshot via `test_openapi_snapshot.py` (regenerate as that test's docstring says).

Web
- Regenerate `web/src/api/openapi.json`, `web/src/api/generated/*`.
- Create `web/src/api/conversations.ts` (+ `.test.ts`) — `listConversations()`.
- Create `web/src/app/conversations.tsx` (+ `.test.tsx`) — the shell's list: context, hook, `recentConversations`, `conversationTitle`.
- Modify `web/src/components/AppShell/AppShell.tsx` — provide the context, feed `SideNav recent`.
- Modify `web/src/features/chat/ChatPage.tsx` — refresh the list after a rename and after an answer finishes.
- Create `web/src/features/conversations/lastActivity.ts` (+ `.test.ts`), `ConversationTable.tsx` + `.module.css` (+ `.test.tsx`), `ConversationsPage.tsx` + `.module.css` (+ `.test.tsx`).
- Modify `web/src/app/routes.tsx` (+ `routes.test.tsx`) — the `conversations` route.

Docs
- `sdd/prd.md` (v2.37), `backend/src/smart_tutor/tutoring/README.md`.

---

### Task 1: List threads and note questions in the tutoring domain and service

**Files:**
- Create: `backend/src/smart_tutor/tutoring/domain/thread_summary.py`
- Modify: `backend/src/smart_tutor/tutoring/domain/thread.py`, `backend/src/smart_tutor/tutoring/ports/thread_repository.py`, `backend/src/smart_tutor/tutoring/application/conversation_service.py`, `backend/src/smart_tutor/tutoring/application/__init__.py`, `backend/tests/fakes/tutoring.py`
- Test: `backend/tests/unit/tutoring/test_thread.py`, `backend/tests/unit/tutoring/test_conversation_service.py`

**Interfaces:**
- Produces:
  - `ThreadSummary(thread_id: ThreadId, title: str | None, subject_ids: tuple[SubjectId, ...], documents: int, last_activity: datetime)` (frozen dataclass), exported from `smart_tutor.tutoring.application`.
  - `Thread.last_activity -> datetime` (property: `last_learner_message_at or created_at`); `Thread.ask(now: datetime) -> None` (sets `last_learner_message_at`; raises `ThreadArchivedError("An archived conversation is read-only. Restore it first.")` when archived).
  - Port: `list_owned(user_id: UserId, status: ThreadStatus) -> list[Thread]` (newest last activity first, then `created_at` desc, then `thread_id` asc); `documents_used_by_thread(thread_ids: Sequence[ThreadId]) -> dict[ThreadId, list[ThreadDocument]]` (each list in the order of `documents_used`; threads with no rows may be absent); `set_last_learner_message_at(thread_id: ThreadId, at: datetime) -> None` (committed).
  - `ConversationService.list_threads(user_id: UserId) -> list[ThreadSummary]`; `ConversationService.note_question(thread_id: ThreadId, user_id: UserId) -> None` (raises `ThreadNotFoundError` / `ThreadArchivedError`).

- [ ] **Step 1: Write the failing domain tests** (append to `test_thread.py`, matching its imports):

```python
def test_last_activity_is_the_last_learner_message_or_the_start() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    assert Thread(ThreadId("t"), UserId("ada"), start).last_activity == start
    later = start + timedelta(hours=2)
    assert Thread(ThreadId("t"), UserId("ada"), start, last_learner_message_at=later).last_activity == later


def test_asking_moves_the_last_learner_message() -> None:
    start = datetime(2026, 10, 1, tzinfo=UTC)
    thread = Thread.start(ThreadId("t"), UserId("ada"), start)
    thread.ask(start + timedelta(minutes=5))
    assert thread.last_learner_message_at == start + timedelta(minutes=5)


def test_an_archived_thread_takes_no_question() -> None:
    thread = Thread(ThreadId("t"), UserId("ada"), datetime(2026, 10, 1, tzinfo=UTC), status=ThreadStatus.ARCHIVED)
    with pytest.raises(ThreadArchivedError):
        thread.ask(datetime(2026, 10, 2, tzinfo=UTC))
```

- [ ] **Step 2: Write the failing service tests** (append to `test_conversation_service.py`; reuse its `service(...)` helper; `FixedClock` has `advance(...)` or settable `now` — check `tests/fakes/clock.py` and use what exists; `SubjectId` from `smart_tutor.shared.domain.ids`; archive/delete a document through `DocumentService`/the library the way existing tests in this file do (search the file for `archive` and `delete`)):

```python
S1, S2, S3 = (SubjectId(f"00000000-0000-4000-8000-00000000000{i}") for i in (1, 2, 3))


def test_lists_the_learners_active_threads_newest_activity_first() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")
    svc = service(library, threads, clock)
    first = svc.start_thread(UserId("ada"), "First?")
    clock.advance(timedelta(minutes=1))
    second = svc.start_thread(UserId("ada"), "Second?")
    clock.advance(timedelta(minutes=1))
    svc.note_question(ThreadId(first.thread_id), UserId("ada"))  # first is now the newest

    listed = svc.list_threads(UserId("ada"))

    assert [(s.thread_id, s.title) for s in listed] == [(first.thread_id, "First?"), (second.thread_id, "Second?")]
    assert listed[0].last_activity == clock.now()


def test_lists_no_archived_and_no_one_elses_threads() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")
    ingest_ready(library, "bob", "Attention is all you need.")
    svc = service(library, threads, clock)
    kept = svc.start_thread(UserId("ada"), "Mine?")
    archived = svc.start_thread(UserId("ada"), "Old?")
    threads.threads[archived.thread_id].status = ThreadStatus.ARCHIVED
    svc.start_thread(UserId("bob"), "Theirs?")

    assert [s.thread_id for s in svc.list_threads(UserId("ada"))] == [kept.thread_id]


def test_deleted_documents_subjects_dont_count_archived_ones_do() -> None:
    # One live document (S1), one archived (S2), one deleted (S3): subjects S1, S2; documents 3.
    ...  # build three ready documents with subject_ids=[S1], [S2], [S3]; start a thread; record a turn with all
    # three document_ids (svc.record_turn with AnsweredTurn(..., document_ids=(d1, d2, d3))); archive d2 and delete d3
    # the way this file's existing archive/delete tests do; then:
    # [row] = svc.list_threads(UserId("ada"))
    # assert row.subject_ids == (S1, S2) and row.documents == 3


def test_a_subject_shared_by_two_documents_appears_once() -> None:
    # Two ready documents, subject_ids=[S1, S2] and [S2, S3]; a turn uses both → subject_ids == (S1, S2, S3).
    ...


def test_a_thread_with_no_documents_lists_none() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")
    svc = service(library, threads, clock)
    svc.start_thread(UserId("ada"), "Hi?")
    [row] = svc.list_threads(UserId("ada"))
    assert row.subject_ids == () and row.documents == 0


def test_noting_a_question_needs_the_owners_active_thread() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.")
    svc = service(library, threads, clock)
    thread = svc.start_thread(UserId("ada"), "Hi?")
    with pytest.raises(ThreadNotFoundError):
        svc.note_question(ThreadId(thread.thread_id), UserId("bob"))
    threads.threads[thread.thread_id].status = ThreadStatus.ARCHIVED
    with pytest.raises(ThreadArchivedError):
        svc.note_question(ThreadId(thread.thread_id), UserId("ada"))
```

The two `...` tests must be written out in full by the implementer following the comments (the setup helpers differ per file; copy the exact calls from neighbouring tests). They are required, not optional.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/tutoring -q`
Expected: FAIL (`AttributeError`/`ImportError` for `last_activity`, `ask`, `list_threads`, `note_question`).

- [ ] **Step 4: Implement**

`thread_summary.py`:

```python
"""One row of the learner's conversations list (PRD §8 US-13)."""

from dataclasses import dataclass
from datetime import datetime

from smart_tutor.shared.domain.ids import SubjectId, ThreadId


@dataclass(frozen=True)
class ThreadSummary:
    thread_id: ThreadId
    title: str | None  # the first question until renamed
    subject_ids: tuple[SubjectId, ...]  # of its listed documents that still exist, archived included (D11)
    documents: int  # rows in its document list, deleted ones included
    last_activity: datetime
```

`thread.py` additions on `Thread`:

```python
    @property
    def last_activity(self) -> datetime:
        """The learner's last question in it, or when it started (US-13)."""
        return self.last_learner_message_at or self.created_at

    def ask(self, now: datetime) -> None:
        """The learner asks in it now; an archived thread is read-only."""
        if self.status is ThreadStatus.ARCHIVED:
            raise ThreadArchivedError("An archived conversation is read-only. Restore it first.")
        self.last_learner_message_at = now
```

Port (`thread_repository.py`, import `ThreadStatus`):

```python
    @abstractmethod
    def list_owned(self, user_id: UserId, status: ThreadStatus) -> list[Thread]:
        """The learner's threads in this status, newest last activity first (then newest started; scoped by owner)."""

    @abstractmethod
    def documents_used_by_thread(self, thread_ids: Sequence[ThreadId]) -> dict[ThreadId, list[ThreadDocument]]:
        """Each thread's document list as `documents_used` orders it; a thread with none may be absent.
        (Callers pass ids of the learner's own threads.)"""

    @abstractmethod
    def set_last_learner_message_at(self, thread_id: ThreadId, at: datetime) -> None:
        """Store when the learner last asked in the thread (committed). (Callers check ownership first.)"""
```

Service (`conversation_service.py`):

```python
    def list_threads(self, user_id: UserId) -> list[ThreadSummary]:
        """The learner's active conversations, newest last activity first (US-13). A row's subjects are those of its
        listed documents that still exist, archived included, read now (D11); a deleted document adds none."""
        threads = self._threads.list_owned(user_id, ThreadStatus.ACTIVE)
        rows = self._threads.documents_used_by_thread([ThreadId(t.thread_id) for t in threads])
        views = self._documents.documents_by_id(
            user_id, list(dict.fromkeys(r.document_id for listed in rows.values() for r in listed))
        )
        summaries: list[ThreadSummary] = []
        for t in threads:
            listed = rows.get(ThreadId(t.thread_id), [])
            subject_ids = dict.fromkeys(
                s for r in listed if (view := views.get(r.document_id)) is not None for s in view.subject_ids
            )
            summaries.append(
                ThreadSummary(ThreadId(t.thread_id), t.title, tuple(subject_ids), len(listed), t.last_activity)
            )
        return summaries

    def note_question(self, thread_id: ThreadId, user_id: UserId) -> None:
        """A question asked in the thread now is its latest activity (US-13)."""
        thread = self._get(thread_id, user_id)
        now = self._clock.now()
        thread.ask(now)
        self._threads.set_last_learner_message_at(thread_id, now)
```

Fake (`tests/fakes/tutoring.py`, import `ThreadStatus`):

```python
    def list_owned(self, user_id: UserId, status: ThreadStatus) -> list[Thread]:
        mine = [copy.deepcopy(t) for t in self.threads.values() if t.user_id == user_id and t.status is status]
        mine.sort(key=lambda t: t.thread_id)
        mine.sort(key=lambda t: (t.last_activity, t.created_at), reverse=True)
        return mine

    def documents_used_by_thread(self, thread_ids: Sequence[ThreadId]) -> dict[ThreadId, list[ThreadDocument]]:
        return {tid: list(self.documents_used_rows[tid]) for tid in thread_ids if self.documents_used_rows.get(tid)}

    def set_last_learner_message_at(self, thread_id: ThreadId, at: datetime) -> None:
        self.threads[thread_id].last_learner_message_at = at
```

Export `ThreadSummary` in `application/__init__.py` (import and `__all__`, alphabetical).

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/tutoring -q && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: PASS. (`SqlThreadRepository` is now abstract-incomplete; mypy reports it only if instantiated in typed code — if mypy or any test fails on it, add the three methods with `raise NotImplementedError` and replace them in Task 2.)

- [ ] **Step 6: Commit**

```bash
git add backend/src/smart_tutor/tutoring backend/tests/fakes/tutoring.py backend/tests/unit/tutoring
git commit -m "List a learner's active threads with their subjects and note each question"
```
(body: why — US-13 lists conversations by last activity; later questions must move it; D11/L1 subjects.)

---

### Task 2: SQL adapter for listing threads and noting questions

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/adapters/sql_threads.py`
- Test: `backend/tests/integration/tutoring/test_sql_threads.py`

**Interfaces:**
- Consumes: the three port methods from Task 1.
- Produces: `SqlThreadRepository.list_owned`, `.documents_used_by_thread`, `.set_last_learner_message_at`.

- [ ] **Step 1: Write the failing integration tests** (append; same imports plus `timedelta`, `ThreadStatus`):

```python
def test_list_owned_is_the_owners_threads_newest_activity_first(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner, other = UserId(f"ada-{uuid.uuid4()}"), UserId(f"bob-{uuid.uuid4()}")
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    older = Thread.start(ThreadId(str(uuid.uuid4())), owner, t0, title="Older")
    newer = Thread.start(ThreadId(str(uuid.uuid4())), owner, t0 + timedelta(hours=1), title="Newer")
    archived = Thread(ThreadId(str(uuid.uuid4())), owner, t0, status=ThreadStatus.ARCHIVED)
    theirs = Thread.start(ThreadId(str(uuid.uuid4())), other, t0 + timedelta(hours=2))
    for t in (older, newer, archived, theirs):
        repo.add(t)

    assert [t.thread_id for t in repo.list_owned(owner, ThreadStatus.ACTIVE)] == [newer.thread_id, older.thread_id]

    repo.set_last_learner_message_at(older.thread_id, t0 + timedelta(hours=3))
    listed = repo.list_owned(owner, ThreadStatus.ACTIVE)
    assert [t.thread_id for t in listed] == [older.thread_id, newer.thread_id]
    assert listed[0].last_learner_message_at == t0 + timedelta(hours=3)
    assert [t.thread_id for t in repo.list_owned(owner, ThreadStatus.ARCHIVED)] == [archived.thread_id]


def test_a_thread_with_no_learner_message_sorts_by_its_start(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    quiet = Thread(ThreadId(str(uuid.uuid4())), owner, t0 + timedelta(hours=2))  # last_learner_message_at None
    asked = Thread.start(ThreadId(str(uuid.uuid4())), owner, t0 + timedelta(hours=1))
    repo.add(quiet)
    repo.add(asked)
    assert [t.thread_id for t in repo.list_owned(owner, ThreadStatus.ACTIVE)] == [quiet.thread_id, asked.thread_id]


def test_documents_used_by_thread_groups_each_threads_list_in_order(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    now = datetime.now(UTC)
    a = Thread.start(ThreadId(str(uuid.uuid4())), owner, now)
    b = Thread.start(ThreadId(str(uuid.uuid4())), owner, now)
    empty = Thread.start(ThreadId(str(uuid.uuid4())), owner, now)
    for t in (a, b, empty):
        repo.add(t)
    d1, d2, d3 = (DocumentId(str(uuid.uuid4())) for _ in range(3))
    repo.add_documents_used(a.thread_id, [d2, d1], now)
    repo.add_documents(b.thread_id, [d3], now)

    grouped = repo.documents_used_by_thread([a.thread_id, b.thread_id, empty.thread_id])

    assert [r.document_id for r in grouped[a.thread_id]] == [d2, d1]
    assert [r.document_id for r in grouped[b.thread_id]] == [d3]
    assert grouped.get(empty.thread_id, []) == []
    assert repo.documents_used_by_thread([]) == {}
```

- [ ] **Step 2: Run them to verify they fail** (scratch database, Global Constraints). Expected: FAIL (`TypeError: Can't instantiate abstract class` or `AttributeError`).

- [ ] **Step 3: Implement** in `SqlThreadRepository` (import `ThreadStatus`; `func` is already imported):

```python
    def list_owned(self, user_id: UserId, status: ThreadStatus) -> list[Thread]:
        last_activity = func.coalesce(threads.c.last_learner_message_at, threads.c.created_at)
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(threads)
                .where(threads.c.user_id == user_id, threads.c.status == status.value)
                .order_by(last_activity.desc(), threads.c.created_at.desc(), threads.c.thread_id)
            ).all()
        return [_thread(r) for r in rows]

    def documents_used_by_thread(self, thread_ids: Sequence[ThreadId]) -> dict[ThreadId, list[ThreadDocument]]:
        if not thread_ids:
            return {}
        with self._engine.connect() as conn:
            rows = conn.execute(
                select(thread_documents)
                .where(thread_documents.c.thread_id.in_(thread_ids))
                .order_by(thread_documents.c.thread_id, thread_documents.c.added_at, thread_documents.c.seq)
            ).all()
        grouped: dict[ThreadId, list[ThreadDocument]] = {}
        for r in rows:
            grouped.setdefault(ThreadId(str(r.thread_id)), []).append(_thread_document(r))
        return grouped

    def set_last_learner_message_at(self, thread_id: ThreadId, at: datetime) -> None:
        with self._engine.begin() as conn:
            conn.execute(threads.update().where(threads.c.thread_id == thread_id).values(last_learner_message_at=at))
```

Extract the existing row→`ThreadDocument` conversion in `documents_used` into a module function `_thread_document(r: Any) -> ThreadDocument` and use it in both. Update the module docstring only if it lists methods (it lists migrations; no new migration is needed: the existing `threads_user_created` index covers the owner filter at Release 1 sizes).

- [ ] **Step 4: Run** the integration tests on the scratch database, then `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy`. Expected: PASS.

- [ ] **Step 5: Commit** — `git commit -m "List a learner's threads and documents used in Postgres"` (body: owner-scoped, ordered by coalesced last activity; one query for all threads' documents to avoid N+1).

---

### Task 3: `GET /threads`, activity on each question, isolation, and the regenerated client

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py`
- Test: `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py`, OpenAPI snapshot (`backend/tests/unit/apps/api/test_openapi_snapshot.py` — read its docstring for how to refresh the snapshot)
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`

**Interfaces:**
- Consumes: `ConversationService.list_threads`, `.note_question`, `ThreadSummary`; `Subjects` dependency (`SubjectNames`) from `smart_tutor.apps.api.deps`; `SubjectResponse` from `smart_tutor.apps.api.routes.knowledge`.
- Produces: `GET /threads` operation `list_threads` → `list[ThreadSummaryResponse]` with `thread_id: str`, `title: str | None`, `subjects: list[SubjectResponse]` (`subject_id`, `name`), `documents: int`, `last_activity: datetime`. Generated web SDK function `listThreads`, type `ThreadSummaryResponse`.

- [ ] **Step 1: Write the failing route tests** in `test_thread_routes.py` (follow that file's client/fixture helpers: search it for `api_services(` and `TestClient(`; use `ingest_ready(..., subject_ids=[...])` and a `catalog`/`names` that knows the subjects — `tests/isolation/test_subjects.py` shows a `SubjectNames` subclass returning personal names; reuse that idea):

```python
def test_lists_the_callers_threads_with_subject_names_newest_first() -> None:
    # learner-a: document with subjects [IR] (personal name "My IR notes" via a SubjectNames subclass); two threads,
    # the first one used the document (fake agent emits a `sources` event naming it), the second didn't.
    # GET /threads → 200, newest first:
    # [{"thread_id": second, "title": "Second?", "subjects": [], "documents": 0, "last_activity": ...},
    #  {"thread_id": first, "title": "First?", "subjects": [{"subject_id": IR, "name": "My IR notes"}],
    #   "documents": 1, "last_activity": ...}]
    ...


def test_asking_in_a_thread_makes_it_the_newest() -> None:
    # Two threads started at clock t and t+1min; advance the clock; POST /threads/{first}/questions → 200;
    # GET /threads lists first before second, and its last_activity equals the advanced clock (ISO string).
    ...


def test_an_archived_thread_is_refused_and_keeps_its_activity() -> None:
    # Mark a thread archived in InMemoryThreads; POST /threads/{id}/questions → 409; last_learner_message_at unchanged.
    ...


def test_listing_needs_a_token() -> None:
    # GET /threads without Authorization → 401.
    ...
```

Write each test out in full from the comments (copy the setup calls from neighbouring tests in the same file).

- [ ] **Step 2: Write the failing isolation test** (append to `backend/tests/isolation/test_threads.py`; update its module docstring to mention `GET /threads`):

```python
def test_each_learner_lists_only_their_own_threads() -> None:
    """Two learners sharing a subject and the same uploaded file each list only their own threads."""
    library, threads = InMemoryLibrary(), InMemoryThreads()
    same_text = "Attention weighs tokens."
    a_document = ingest_ready(library, "learner-a", same_text, subject_ids=[SHARED])
    b_document = ingest_ready(library, "learner-b", same_text, subject_ids=[SHARED])

    def answers_from(document_id: str) -> httpx.MockTransport:  # adapt to how fake_agent takes a handler
        ...

    # Each learner asks once; their agent's `sources` names their own document.
    # A GET /threads → exactly A's thread, subjects [SHARED], documents 1; B likewise with B's thread.
    # No thread_id from one learner's list appears in the other's.
    ...
```

Write it in full; build each learner's answer with a `sources` event for that learner's own document id (see `test_only_the_owner_lists_a_threads_documents_used` above it for the body format), using one `fake_agent` whose handler picks the document by the request's bearer token, or two sequential clients.

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && uv run pytest tests/unit/apps/api/test_thread_routes.py tests/isolation/test_threads.py -q`
Expected: FAIL (404/405 on `GET /threads`; ordering test fails because activity doesn't move).

- [ ] **Step 4: Implement** in `routes/threads.py` (update the module docstring: it now also lists the learner's conversations):

```python
from smart_tutor.apps.api.deps import Agent, BearerToken, Conversations, CurrentPrincipal, Subjects
from smart_tutor.apps.api.routes.knowledge import SubjectResponse
...

class ThreadSummaryResponse(BaseModel):
    thread_id: str
    title: str | None
    subjects: list[SubjectResponse]  # of its documents used that still exist, by the learner's names (D11)
    documents: int
    last_activity: datetime


@router.get("/threads", operation_id="list_threads")
def list_threads(
    principal: CurrentPrincipal, conversations: Conversations, subjects: Subjects
) -> list[ThreadSummaryResponse]:
    """The learner's active conversations, newest last activity first (PRD US-13): title, subjects of the documents
    used (deleted ones excluded), number of documents, last activity."""
    summaries = conversations.list_threads(principal.user_id)
    names = subjects.names_for(principal.user_id, {s for t in summaries for s in t.subject_ids})
    return [
        ThreadSummaryResponse(
            thread_id=t.thread_id,
            title=t.title,
            subjects=[SubjectResponse(subject_id=s, name=names[s]) for s in t.subject_ids if s in names],
            documents=t.documents,
            last_activity=t.last_activity,
        )
        for t in summaries
    ]
```

Place it before `get_thread`. In `ask_in_thread`, inside the existing `try` after `require_documents`:

```python
        await run_in_threadpool(conversations.note_question, tid, principal.user_id)
```

(`ThreadArchivedError` and `ThreadNotFoundError` are already mapped by that `try`.) If importing `SubjectResponse` from `routes.knowledge` creates an import cycle, move `SubjectResponse` to a new `apps/api/routes/schemas.py` and import it from there in both routes.

- [ ] **Step 5: Run the tests, refresh the OpenAPI snapshot, regenerate the web client**

```bash
cd backend && uv run pytest tests/unit/apps/api/test_thread_routes.py tests/isolation/test_threads.py -q
# refresh the snapshot as test_openapi_snapshot.py's docstring says, then:
uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json
cd ../web && npm --prefix tools/api-gen ci && npm run api:generate
cd ../backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest -q
```
Expected: PASS; `web/src/api/generated/sdk.gen.ts` exports `listThreads`; `types.gen.ts` has `ThreadSummaryResponse`.

- [ ] **Step 6: Commit** — `git commit -m "List the learner's conversations at GET /threads"` (body: US-13; a later question now moves last activity; isolation with shared subject and same file; regenerated client).

---

### Task 4: The shell's conversations list feeds the side nav

**Files:**
- Create: `web/src/api/conversations.ts`, `web/src/api/conversations.test.ts`, `web/src/app/conversations.tsx`, `web/src/app/conversations.test.tsx`
- Modify: `web/src/components/AppShell/AppShell.tsx`, `web/src/features/chat/ChatPage.tsx`
- Test: existing AppShell/SideNav tests (search `web/src` for tests that render `AppShell`), `web/src/features/chat/ChatPage.test.tsx`

**Interfaces:**
- Consumes: generated `listThreads`, type `ThreadSummaryResponse`; `sessionOver` from `./documents`; `RecentConversation` from `app/nav.ts`.
- Produces:
  - `listConversations(apiClient?: Client): Promise<ThreadSummaryResponse[]>` (throws `SessionExpiredError` on session over; `Error` otherwise); re-exports `type ThreadSummaryResponse`.
  - `type ConversationsList = { list: ThreadSummaryResponse[] | null; failed: boolean; refresh: () => void }`; `ConversationsContext`; `useConversations()`; `useConversationsState(load: () => Promise<ThreadSummaryResponse[]>, key: string): ConversationsList`; `conversationTitle(t: ThreadSummaryResponse): string` (`t.title ?? "Untitled conversation"`); `recentConversations(list: ThreadSummaryResponse[] | null): RecentConversation[]` (first three, `{ id, title: conversationTitle(t), path: \`/chat/${t.thread_id}\` }`).
  - `AppShell` prop `loadConversations?: () => Promise<ThreadSummaryResponse[]>` (default `listConversations`).

- [ ] **Step 1: Write the failing tests**

`api/conversations.test.ts` — follow `api/documents.test.ts`'s pattern for a fake client (search it for how it builds a client with a stub `fetch`): a 200 returns the array; a 401 throws `SessionExpiredError`; a 500 throws an `Error` mentioning `GET /threads`.

`app/conversations.test.tsx` (render a probe component with `renderHook` or a tiny component using `useConversationsState`):

```tsx
it("loads the list for each key and refreshes on demand", async () => { /* load resolves [a]; key "x" → list [a];
   change key to "y" → load called again; refresh() → called again */ });
it("a stale load doesn't overwrite a newer one", async () => {
  // first load returns a deferred promise P1, refresh() starts P2; resolve P2 with [b], then P1 with [a] → list stays [b]
});
it("a failed first load sets failed and keeps list null; a later success clears failed", async () => { ... });
it("recentConversations keeps three, newest first as given, with chat paths and untitled fallback", () => {
  expect(recentConversations([t1, t2, { ...t3, title: null }, t4])).toEqual([
    { id: t1.thread_id, title: t1.title, path: `/chat/${t1.thread_id}` },
    { id: t2.thread_id, title: t2.title, path: `/chat/${t2.thread_id}` },
    { id: t3.thread_id, title: "Untitled conversation", path: `/chat/${t3.thread_id}` },
  ]);
});
```

AppShell test (add to the existing file that renders `AppShell`, passing `loadConversations`): with two conversations, the side nav's "Recent conversations" list shows both titles as links to `/chat/<id>`; with none, the list is absent.

ChatPage test: render `ChatPage` inside `ConversationsContext.Provider` with a `refresh` spy; after a successful rename (existing rename test flow), `refresh` was called; after an answer stream ends with `done`, `refresh` was called.

Write every test body in full, reusing helpers already in those files.

- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run src/api/conversations.test.ts src/app/conversations.test.tsx src/components src/features/chat` → FAIL.

- [ ] **Step 3: Implement**

`api/conversations.ts`:

```ts
import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { listThreads } from "./generated/sdk.gen";
import type { ThreadSummaryResponse } from "./generated/types.gen";
import { sessionOver } from "./documents";

export type { ThreadSummaryResponse };

// The learner's active conversations, newest last activity first (owner only).
export async function listConversations(apiClient: Client = client): Promise<ThreadSummaryResponse[]> {
  const { data, error, response } = await listThreads({ client: apiClient, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /threads failed (${response?.status ?? "no response"})`);
  return data;
}
```

`app/conversations.tsx`:

```tsx
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import type { ThreadSummaryResponse } from "../api/conversations";
import type { RecentConversation } from "./nav";

export type ConversationsList = { list: ThreadSummaryResponse[] | null; failed: boolean; refresh: () => void };
export const ConversationsContext = createContext<ConversationsList>({ list: null, failed: false, refresh: () => {} });
export const useConversations = () => useContext(ConversationsContext);

export const conversationTitle = (t: ThreadSummaryResponse) => t.title ?? "Untitled conversation";

export const recentConversations = (list: ThreadSummaryResponse[] | null): RecentConversation[] =>
  (list ?? []).slice(0, 3).map((t) => ({ id: t.thread_id, title: conversationTitle(t), path: `/chat/${t.thread_id}` }));

// The learner's conversations (PRD US-13), for the side nav's recent ones and the Conversations page. The shell reloads
// it on every navigation; Chat refreshes it after a rename or an answer. Only the latest load's result is kept.
export function useConversationsState(load: () => Promise<ThreadSummaryResponse[]>, key: string): ConversationsList {
  const [list, setList] = useState<ThreadSummaryResponse[] | null>(null);
  const [failed, setFailed] = useState(false);
  const loadRef = useRef(load);
  const latest = useRef(0);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);
  const refresh = useCallback(() => {
    const call = ++latest.current;
    loadRef.current().then(
      (items) => {
        if (call !== latest.current) return;
        setList(items);
        setFailed(false);
      },
      () => {
        if (call === latest.current) setFailed(true); // a failure keeps the last list
      },
    );
  }, []);
  useEffect(() => {
    refresh();
  }, [key, refresh]);
  useEffect(() => () => {
    latest.current++; // unmounted: ignore loads still running
  }, []);
  return useMemo(() => ({ list, failed, refresh }), [list, failed, refresh]);
}
```

(If the project's eslint/TS config forbids the unmount effect shape, keep the behaviour — ignore results after unmount — in whatever form passes `npm run build`.)

`AppShell.tsx`: add prop `loadConversations = listConversations`; `const conversations = useConversationsState(loadConversations, pathname);`; wrap children in `<ConversationsContext.Provider value={conversations}>`; replace `recent={[]}` and its comment with `recent={recentConversations(conversations.list)}`.

`ChatPage.tsx`: `const conversations = useConversations();` — call `conversations.refresh()` right after `rename(threadId, newTitle)` resolves successfully (around line 577), and once when an answer's stream ends with `done` (where `done = true` is set, around line 410; call it after the loop when `done` is true so it runs once per answer).

- [ ] **Step 4: Run** — `cd web && npx vitest run && npm run build` → PASS.

- [ ] **Step 5: Commit** — `git commit -m "Show the three most recent conversations in the side nav"` (body: one list in the shell, reloaded on navigation and after a rename or an answer, so the nav stays current; stale loads are ignored).

---

### Task 5: The Conversations page

**Files:**
- Create: `web/src/features/conversations/lastActivity.ts`, `lastActivity.test.ts`, `ConversationTable.tsx`, `ConversationTable.module.css`, `ConversationTable.test.tsx`, `ConversationsPage.tsx`, `ConversationsPage.module.css`, `ConversationsPage.test.tsx`
- Modify: `web/src/app/routes.tsx`, `web/src/app/routes.test.tsx`

**Interfaces:**
- Consumes: `useConversations`, `conversationTitle` (Task 4); `ThreadSummaryResponse`; components `PageHeader`, `EmptyState`, `Button`, `SubjectChip`; `APP_TIME_ZONE` from `src/time.ts`; `NAV` description for Conversations.
- Produces: `lastActivity(iso: string, now?: Date): string`; `ConversationTable({ conversations }: { conversations: ThreadSummaryResponse[] })`; `ConversationsPage()`; route `conversations` (handle `{ wide: true }`).

Read `DESIGN.md` (Components → list/table, chips, empty states; tokens) and look at `.design-shots/v0.10/conversations-active.{light,dark}.png` and `conversations-empty.{light,dark}.png` before writing CSS. Mirror `features/library/DocumentTable.module.css` for the table (header row, row height, borders, truncation) using the same tokens; do not copy prototype CSS.

- [ ] **Step 1: Write the failing tests**

`lastActivity.test.ts` (fix `now` to `2026-10-11T05:00:00Z` = 12:00 in GMT+7):

```ts
const now = new Date("2026-10-11T05:00:00Z");
it("today", () => expect(lastActivity("2026-10-11T02:48:00Z", now)).toBe("Today, 09:48"));
it("yesterday in the app time zone", () => expect(lastActivity("2026-10-10T09:20:00Z", now)).toBe("Yesterday, 16:20"));
it("crosses midnight in GMT+7, not UTC", () => expect(lastActivity("2026-10-10T17:30:00Z", now)).toBe("Today, 00:30"));
it("this year", () => expect(lastActivity("2026-09-30T03:00:00Z", now)).toBe("30 Sep"));
it("another year", () => expect(lastActivity("2025-09-30T03:00:00Z", now)).toBe("30 Sep 2025"));
```

`ConversationTable.test.tsx` (render inside a `MemoryRouter` with a `Routes` that shows a marker at `/chat/:threadId`):
- columns "Conversation", "Subjects of documents used", "Documents", "Last activity";
- a row's title is a link to `/chat/<id>`; clicking the row (not the link, e.g. its documents cell) navigates there too;
- three subjects → two chips plus "+1" whose accessible name lists the hidden one (e.g. `aria-label="1 more: Reinforcement Learning"`) and `title` the same names;
- no subjects → "None yet";
- documents count shown as a number; last activity rendered in a `<time dateTime={iso}>`;
- "an untitled conversation reads Untitled conversation" (title `null`) and links to its chat.

`ConversationsPage.test.tsx` (render inside `ConversationsContext.Provider` and a router):
- list with two → header "Conversations", count "2 conversations", both rows; count "1 conversation" for one;
- `list: []` → "No conversations yet", the body copy, and "Start a conversation" navigates to `/chat`;
- `list: null, failed: true` → "Can't load your conversations. Reload the page to try again.";
- `list: null, failed: false` → no table, no empty state (still loading);
- "New conversation" navigates to `/chat`;
- a renamed conversation: re-render the provider with a new `list` where the title changed → the row shows the new title.

`routes.test.tsx`: `/conversations` renders the Conversations page heading (not the placeholder). Follow the file's existing pattern for `/library`.

- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run src/features/conversations src/app` → FAIL.

- [ ] **Step 3: Implement**

`lastActivity.ts`:

```ts
import { APP_TIME_ZONE } from "../../time";

const day = (d: Date) => d.toLocaleDateString("en-CA", { timeZone: APP_TIME_ZONE }); // YYYY-MM-DD in GMT+7
const time = (d: Date) => d.toLocaleTimeString("en-GB", { timeZone: APP_TIME_ZONE, hour: "2-digit", minute: "2-digit", hourCycle: "h23" });

// When the learner last asked in a conversation, in the app time zone (PRD D27): "Today, 09:48", "Yesterday, 16:20",
// "30 Sep", or "30 Sep 2025" in another year.
export function lastActivity(iso: string, now = new Date()): string {
  const at = new Date(iso);
  const yesterday = new Date(now.getTime() - 24 * 60 * 60 * 1000);
  if (day(at) === day(now)) return `Today, ${time(at)}`;
  if (day(at) === day(yesterday)) return `Yesterday, ${time(at)}`;
  const sameYear = day(at).slice(0, 4) === day(now).slice(0, 4);
  return at.toLocaleDateString("en-GB", { timeZone: APP_TIME_ZONE, day: "numeric", month: "short", ...(sameYear ? {} : { year: "numeric" }) });
}
```

(GMT+7 has no DST, so "now − 24h" is always yesterday's date there.)

`ConversationTable.tsx` — a `<table>` like `DocumentTable`: columns as above; row `onClick={() => navigate(path)}` with `className` giving `cursor: pointer` and hover background; the title cell holds `<Link to={path} className={styles.title} title={title}>{title}</Link>` (keyboard and screen readers use the link; `onClick` on the row ignores clicks whose target is inside an `<a>` to avoid double navigation). Subjects cell: `subjects.slice(0, 2).map(s => <SubjectChip key={s.subject_id} name={s.name} hueKey={s.subject_id} size="sm" truncate />)` then, when more, a `<span className={styles.more} title={rest} aria-label={\`${n} more: ${rest}\`}>+{n}</span>`; none → `<span className={styles.muted}>None yet</span>`. Documents cell: the number. Last activity: `<time dateTime={t.last_activity}>{lastActivity(t.last_activity)}</time>`, right-aligned, tabular numerals.

`ConversationsPage.tsx`:

```tsx
export function ConversationsPage() {
  const { list, failed } = useConversations();
  const navigate = useNavigate();
  const start = () => navigate("/chat");
  const description = NAV.find((item) => item.path === "/conversations")?.description;
  return (
    <>
      <PageHeader
        title="Conversations"
        count={list ? `${list.length} ${list.length === 1 ? "conversation" : "conversations"}` : undefined}
        description={description}
        actions={<Button variant="primary" icon={Plus} onClick={start}>New conversation</Button>}
      />
      {failed && list === null && <p className={styles.error}>Can't load your conversations. Reload the page to try again.</p>}
      {list?.length === 0 && (
        <EmptyState icon={MessageSquare} title="No conversations yet" actions={<Button variant="primary" icon={Plus} onClick={start}>Start a conversation</Button>}>
          <p>Ask a question about your documents. Every conversation is saved here so you can come back to it.</p>
        </EmptyState>
      )}
      {list && list.length > 0 && <ConversationTable conversations={list} />}
    </>
  );
}
```

Copy `styles.error` from `LibraryPage.module.css`'s `.error`. `routes.tsx`: add `{ path: "conversations", element: <ConversationsPage />, handle: { wide: true } }` after the chat route and exclude `"/conversations"` from the placeholder filter.

- [ ] **Step 4: Run** — `cd web && npx vitest run && npm run build` → PASS.

- [ ] **Step 5: Look at it.** With the backend unavailable you can still check layout: temporarily render `ConversationsPage` in a Vitest browser-free way is not visual — instead run the app (`make web` against a running API, README "Run the app") or, if no API is available, report that the visual check is left to the controller. Compare against the four PNGs in light and dark: header row, table header, row height, chip size, "+N" chip, right-aligned last activity, empty-state card.

- [ ] **Step 6: Commit** — `git commit -m "List conversations on the Conversations page"` (body: US-13 list in the Library's list layout; empty state starts a conversation; no preview, tabs or filters yet — their own slices).

---

### Task 6: Record the change in the PRD and the tutoring README

**Files:**
- Modify: `sdd/prd.md`, `backend/src/smart_tutor/tutoring/README.md`

- [ ] **Step 1:** `sdd/prd.md`: bump the status line to **Draft v2.37**; add a row at the top of the changes table: `| **Changes from v2.36** | List conversations (#188, US-13): \`GET /threads\` (operation \`list_threads\`) returns the owner's active threads, newest last activity first, each with \`title\`, \`subjects\` (of its listed documents that still exist, archived included, by the learner's names; D11, Q63 L1), \`documents\` (the number listed), and \`last_activity\` (\`last_learner_message_at\`, else \`created_at\`). A question in an existing thread now sets \`last_learner_message_at\`. The web's Conversations page lists them (at most two subject chips, then "+N"; empty state "No conversations yet" with "Start a conversation"), and the side nav shows the three most recent. Archived tab, filters, search, and the note indicator come in their own slices. |`. Check whether §9.4's Thread row or any API section needs `last_learner_message_at` wording ("set at the first question and each later one") and update it.
- [ ] **Step 2:** tutoring `README.md` "Built so far": add `ConversationService.list_threads` (active, owner-scoped, newest last activity first; `ThreadSummary` with subject ids of listed documents that still exist and the number listed) and `note_question` (a question in an existing thread updates `last_learner_message_at`).
- [ ] **Step 3: Commit** — `git commit -m "Record listing conversations in the PRD and tutoring README"`.

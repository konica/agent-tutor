# Archive and restore a conversation (#189) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A learner archives a conversation (from its row's More menu or the conversation panel), finds it under the Conversations page's Archived tab, reads it read-only, and restores it from the list or from the conversation's banner; it leaves and rejoins the side nav's recent list.

**Architecture:** Backend: `Thread.archive()` / `Thread.restore()` flip `status` (idempotent; nothing else changes); `ThreadRepository.set_status`; `ConversationService.archive_thread` / `restore_thread`, `list_threads(user_id, archived=...)`, and the archived guard extended to adding and removing documents. Routes `POST /threads/{id}/archive` (operation `archive_thread`) and `POST /threads/{id}/restore` (`restore_thread`) return `ThreadResponse`, which gains `status`; `GET /threads?archived=true` lists archived threads. Web: `src/api/conversations.ts` gains archive/restore and an `archived` list option; the Conversations page gets Active/Archived `Tabs`, a `RowMenu` per row, and its own archived list; Chat reads `thread.status` and, when archived, shows a banner with Restore, disables the composer, the title, and the panel's document and scope controls, and swaps the panel's "Archive conversation" for "Restore conversation".

**Tech Stack:** FastAPI, SQLAlchemy Core (PostgreSQL), pytest; React 19 + TypeScript, react-router, Vitest + Testing Library, CSS modules with `DESIGN.md` tokens, `lucide-react` icons.

**Spec:** GitHub issue #189 (parent #23 US-13); PRD v2.48 §8 US-13 ("archive and restore (archived = read-only)"; "An archived conversation can't be renamed until restored"), §9.4 Thread `status` (`active` / `archived`), Q62 (Archive lives in the conversation panel's Actions, no header menu); design brief §6.6 P1, §6.7; mockups `design-v0.10` states `conversations-archived`, `chat-archived`. Render: `cd web && npm run design:shots -- --states "conversations-archived,chat-archived,conversations-active" --round v0.10 --theme both` (PNGs in `.design-shots/v0.10/`). Prototype source at the tag: `git show design-v0.10:sdd/design/prototype/js/screens.js` (Conversations, lines 8–34) and `git show design-v0.10:sdd/design/prototype/js/chat.js` (panel Actions line 222, composer banner lines 234–240, actions 396–397).

## Global Constraints

- **No migration.** `threads.status` already exists (`active` / `archived`). Archive and restore change only `status`; title, search scope, `last_learner_message_at`, turns, documents used are untouched. Repeating either is harmless (200, same result).
- **Owner only:** every new route goes through `ConversationService._get` (owner-scoped `get_owned`); another learner's or an unknown id is `404 "Conversation not found"`. `GET /threads?archived=true` filters `threads.user_id = :owner` in SQL.
- **Archived = read-only (409, message from the domain):** asking (exists), renaming (exists), changing the search scope (exists), **adding documents and removing a document (new)**. Add/remove message: `"An archived conversation can't be changed. Restore it first."` Reading (`GET /threads/{id}`, `/turns`, `/documents`) works. **Rating a turn stays allowed** (it is feedback on an answer, not a change to the conversation; the mockup `chat-archived` shows the rating buttons; the ticket's 409 list doesn't include it) — say so in the PR.
- The archived list has the same order as the active one: last activity descending, then `created_at` descending, then `thread_id`.
- `ThreadResponse` gains `status: Literal["active", "archived"]`. Existing tests that compare the whole `ThreadResponse` JSON must add `"status": "active"`.
- No "note link" exists yet (Lesson Notes are US-7/US-13b, not built): nothing to keep beyond leaving rows alone; note it in the PR.
- Copy (verbatim):
  - Tabs: label "Conversations view"; tabs "Active" and "Archived", each with its count.
  - Row menu: label `Actions for <title>`; items "Open", then "Archive" (active rows) or "Restore" (archived rows). Icons `MessageSquare`, `Archive`, `ArchiveRestore`.
  - Archived tab notice (one line, under the tabs): "Archived conversations stay readable. Restore one to keep asking." (the ticket asks for a line; the mockup has none — record it in the PR).
  - Archived tab empty: title "No archived conversations", body "Conversations you archive appear here. You can restore them at any time." (icon `Archive`).
  - Active tab empty while archived ones exist: title "No active conversations", body "Start a new conversation, or restore one from Archived.", action "Start a conversation" (goes to `/chat`). Both lists empty: the existing "No conversations yet" state.
  - Page header count stays the **active** count ("1 conversation" / "N conversations").
  - Status after a list action: "<title> archived. Find it under Archived." / "<title> restored."; failure "Couldn't archive <title>. Try again." / "Couldn't restore <title>. Try again."
  - Chat banner (above the composer): Banner `variant="info"`, icon `Archive`, title "This conversation is archived.", text "Restore it to keep asking.", action primary small button "Restore" (icon `ArchiveRestore`).
  - Chat composer placeholder while archived: "Archived conversation".
  - Panel Actions: "Archive conversation" (icon `Archive`) on an active conversation, "Restore conversation" (icon `ArchiveRestore`) on an archived one. Status: "Conversation archived." / "Conversation restored."; failure (in the status region and as the page `problem`): "Couldn't archive this conversation. Try again." / "Couldn't restore this conversation. Try again."
- Web calls the API only through `src/api/`. Regenerate the client after the routes land (from repo root): `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Build UI with `src/components/` and tokens from `DESIGN.md` (read it before writing UI); never paste prototype HTML/CSS. Icons `strokeWidth={1.5}`, `aria-hidden="true"`.
- **Integration tests must not touch the developer's Compose database** (`smart_tutor`). Use a scratch database:
  ```bash
  docker exec smart-tutor-postgres-1 psql -U smart_tutor -d postgres -c "CREATE DATABASE smart_tutor_it189" || true
  cd backend && SMART_TUTOR_DATABASE_URL=postgresql+psycopg://smart_tutor:smart_tutor@localhost:10400/smart_tutor_it189 uv run pytest -m integration tests/integration/tutoring -v
  ```
- Backend checks (from `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Line length 120, mypy strict. Web checks (from `web/`): `npx vitest run && npm run build`.
- Commits: imperative subject, body says why, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Archive while an answer is streaming in Chat:** the panel's Archive button is disabled while `answering`, so a finishing answer never lands in an archived thread. Pinned in Task 4 ("archive is disabled while answering").
2. **Archive from the panel, then the side nav:** the conversation leaves the recent list without a reload (`conversations.refresh()` after archive and restore). Pinned in Task 4 ("archiving refreshes the shell list") and Task 3 ("archiving from the list refreshes the shell list").
3. **Restore from the banner:** composer, title editing, Add documents, remove buttons, and the scope switch all come back without a reload, and focus lands in the composer. Pinned in Task 4 ("restoring from the banner brings the controls back and focuses the composer").
4. **A limited-decline turn in an archived conversation:** its "Add documents" and "Search all my documents" buttons are disabled (they would change or ask in the conversation). Pinned in Task 4 ("an archived conversation's decline buttons are disabled").
5. **Another learner's thread id:** archive/restore are 404, and B's archived list never shows A's archived thread. Pinned in Task 2 (isolation test).

---

## File Structure

Backend
- Modify `backend/src/smart_tutor/tutoring/domain/thread.py` — `archive()`, `restore()`, `require_active()`.
- Modify `backend/src/smart_tutor/tutoring/ports/thread_repository.py` — `set_status`.
- Modify `backend/tests/fakes/tutoring.py` — `InMemoryThreads.set_status`.
- Modify `backend/src/smart_tutor/tutoring/adapters/sql_threads.py` — `set_status`.
- Modify `backend/src/smart_tutor/tutoring/application/conversation_service.py` — `archive_thread`, `restore_thread`, `list_threads(..., archived=)`, guards in `add_documents` / `remove_document`.
- Modify `backend/src/smart_tutor/apps/api/routes/threads.py` — `status` in `ThreadResponse`, `archived` query param, two routes, 409 on add/remove documents; module docstring.
- Tests: `backend/tests/unit/tutoring/test_thread.py`, `test_conversation_service.py`, `backend/tests/integration/tutoring/test_sql_threads.py`, `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py`; OpenAPI snapshot `web/src/api/openapi.json`.
- Modify `sdd/prd.md` — v2.49, Changes row.

Web
- Regenerate `web/src/api/openapi.json`, `web/src/api/generated/*`.
- Modify `web/src/api/conversations.ts` (+ `.test.ts`) — `listConversations({ archived })`, `archiveConversation`, `restoreConversation`.
- Modify `web/src/features/conversations/ConversationTable.tsx` (+ `.module.css`, `.test.tsx`) — actions column with `RowMenu`.
- Modify `web/src/features/conversations/ConversationsPage.tsx` (+ `.module.css`, `.test.tsx`) — tabs, archived list, notice, empty states, status region.
- Modify `web/src/components/Banner/Banner.tsx` (+ test) — optional `icon` override.
- Modify `web/src/features/chat/ConversationPanel.tsx` (+ test) — `archived`, `onArchive`, `onRestore`, `busy`; read-only document controls.
- Modify `web/src/features/chat/ChatPage.tsx` (+ `.module.css`, `.test.tsx`) — `archived` state, banner, disabled composer/title/decline buttons, archive/restore handlers, injectable `archive`/`restore` props.
- Modify `web/src/features/chat/ThreadTitle.tsx` — only its `editable` doc comment ("or while it is archived" is now real).

---

### Task 1: Archive and restore in the domain, repository, and service

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/domain/thread.py`
- Modify: `backend/src/smart_tutor/tutoring/ports/thread_repository.py`
- Modify: `backend/tests/fakes/tutoring.py`
- Modify: `backend/src/smart_tutor/tutoring/adapters/sql_threads.py`
- Modify: `backend/src/smart_tutor/tutoring/application/conversation_service.py`
- Test: `backend/tests/unit/tutoring/test_thread.py`, `backend/tests/unit/tutoring/test_conversation_service.py`, `backend/tests/integration/tutoring/test_sql_threads.py`

**Interfaces:**
- Produces:
  - `Thread.archive() -> None`, `Thread.restore() -> None` (idempotent, status only), `Thread.require_active(message: str) -> None` (raises `ThreadArchivedError(message)` when archived).
  - `ThreadRepository.set_status(thread_id: ThreadId, status: ThreadStatus) -> None` (committed; callers check ownership first).
  - `ConversationService.archive_thread(thread_id: ThreadId, user_id: UserId) -> Thread`, `ConversationService.restore_thread(thread_id: ThreadId, user_id: UserId) -> Thread` (raise `ThreadNotFoundError("Conversation not found")` for unknown/foreign).
  - `ConversationService.list_threads(user_id: UserId, *, archived: bool = False) -> list[ThreadSummary]`.
  - `ConversationService.add_documents` / `remove_document` raise `ThreadArchivedError("An archived conversation can't be changed. Restore it first.")` for an archived thread, before any change.

- [ ] **Step 1: Write the failing domain tests** (append to `backend/tests/unit/tutoring/test_thread.py`, using the file's existing imports/helpers for building a `Thread`; add imports `ThreadStatus`, `ThreadArchivedError` if missing)

```python
def test_archive_and_restore_change_only_the_status() -> None:
    thread = Thread.start(ThreadId("t1"), UserId("ada"), NOW, title="What is attention?")
    thread.limit_search(SearchScope.LIBRARY, 0)
    before = dataclasses.replace(thread)

    thread.archive()
    assert thread.status is ThreadStatus.ARCHIVED
    assert dataclasses.replace(thread, status=ThreadStatus.ACTIVE) == before

    thread.restore()
    assert thread == before


def test_archive_and_restore_are_idempotent() -> None:
    thread = Thread.start(ThreadId("t1"), UserId("ada"), NOW)
    thread.archive()
    thread.archive()
    assert thread.status is ThreadStatus.ARCHIVED
    thread.restore()
    thread.restore()
    assert thread.status is ThreadStatus.ACTIVE


def test_require_active_refuses_an_archived_thread() -> None:
    thread = Thread.start(ThreadId("t1"), UserId("ada"), NOW)
    thread.require_active("nope")
    thread.archive()
    with pytest.raises(ThreadArchivedError, match="nope"):
        thread.require_active("nope")
```

(If the file has no `NOW` constant, use `datetime(2026, 10, 11, 9, 0, tzinfo=UTC)`; import `dataclasses`.)

- [ ] **Step 2: Run them to verify they fail**

Run: `cd backend && uv run pytest tests/unit/tutoring/test_thread.py -v`
Expected: FAIL with `AttributeError: 'Thread' object has no attribute 'archive'`.

- [ ] **Step 3: Implement in `thread.py`** — add to `Thread`, and make `ask`, `rename`, `limit_search` use `require_active` with their existing messages (behaviour unchanged):

```python
    def archive(self) -> None:
        """The learner archives it (US-13): read-only until restored; history, documents used, and title stay."""
        self.status = ThreadStatus.ARCHIVED

    def restore(self) -> None:
        """The learner restores it: it can be asked in, renamed, and changed again."""
        self.status = ThreadStatus.ACTIVE

    def require_active(self, message: str) -> None:
        """An archived thread is read-only (US-13)."""
        if self.status is ThreadStatus.ARCHIVED:
            raise ThreadArchivedError(message)
```

e.g. `ask` becomes `self.require_active("An archived conversation is read-only. Restore it first.")` then `self.last_learner_message_at = now`.

- [ ] **Step 4: Run the domain tests** — `uv run pytest tests/unit/tutoring/test_thread.py -v` → PASS.

- [ ] **Step 5: Write the failing service tests** (append to `test_conversation_service.py`; `service(...)`, `ingest_ready`, `FixedClock` exist there)

```python
def test_archive_and_restore_keep_history_documents_and_title() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    doc = ingest_ready(library, "ada", "Attention is all you need.")
    conversations = service(library, threads, clock)
    thread = conversations.start_thread(UserId("ada"), "What is attention?", doc)
    tid = ThreadId(thread.thread_id)
    conversations.record_turn(tid, UserId("ada"), AnsweredTurn("What is attention?", "It weighs tokens.", (), None, (doc,), None))

    archived = conversations.archive_thread(tid, UserId("ada"))

    assert archived.status is ThreadStatus.ARCHIVED and archived.title == "What is attention?"
    assert threads.threads[tid].status is ThreadStatus.ARCHIVED
    assert [t.answer for t in conversations.turns(tid, UserId("ada"))] == ["It weighs tokens."]
    assert [d.document_id for d in conversations.documents_used(tid, UserId("ada"))] == [doc]
    assert conversations.archive_thread(tid, UserId("ada")).status is ThreadStatus.ARCHIVED  # idempotent

    restored = conversations.restore_thread(tid, UserId("ada"))
    assert restored.status is ThreadStatus.ACTIVE and threads.threads[tid].status is ThreadStatus.ACTIVE
    assert conversations.restore_thread(tid, UserId("ada")).status is ThreadStatus.ACTIVE  # idempotent


@pytest.mark.parametrize("action", ["archive_thread", "restore_thread"])
def test_archive_and_restore_another_learners_thread_is_not_found(action: str) -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    conversations = service(library, threads, clock)
    thread = conversations.start_thread(UserId("ada"), "Q")

    with pytest.raises(ThreadNotFoundError, match="Conversation not found"):
        getattr(conversations, action)(ThreadId(thread.thread_id), UserId("bob"))
    assert threads.threads[thread.thread_id].status is ThreadStatus.ACTIVE


def test_the_list_shows_active_or_archived_threads() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    conversations = service(library, threads, clock)
    kept = conversations.start_thread(UserId("ada"), "Kept")
    clock.advance(timedelta(minutes=1))
    gone = conversations.start_thread(UserId("ada"), "Archived")
    conversations.archive_thread(ThreadId(gone.thread_id), UserId("ada"))

    assert [t.thread_id for t in conversations.list_threads(UserId("ada"))] == [kept.thread_id]
    assert [t.thread_id for t in conversations.list_threads(UserId("ada"), archived=True)] == [gone.thread_id]


def test_an_archived_thread_can_neither_add_nor_remove_documents() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    listed = ingest_ready(library, "ada", "Attention is all you need.")
    other = ingest_ready(library, "ada", "Gradient descent.")
    conversations = service(library, threads, clock)
    thread = conversations.start_thread(UserId("ada"), "Q", listed)
    tid = ThreadId(thread.thread_id)
    conversations.archive_thread(tid, UserId("ada"))

    with pytest.raises(ThreadArchivedError, match="An archived conversation can't be changed. Restore it first."):
        conversations.add_documents(tid, UserId("ada"), [other])
    with pytest.raises(ThreadArchivedError):
        conversations.remove_document(tid, UserId("ada"), listed)
    assert [r.document_id for r in threads.documents_used(tid)] == [listed]
```

Check `FixedClock` for its advance method name (`advance` or similar) and `AnsweredTurn`'s field order (`question, answer, citations, decline, document_ids, run_id`) before running; adjust to what exists.

- [ ] **Step 6: Run them to verify they fail** — `uv run pytest tests/unit/tutoring/test_conversation_service.py -v -k "archive or archived or active_or"` → FAIL (`AttributeError: ... 'archive_thread'`).

- [ ] **Step 7: Implement port, fake, SQL, service**

Port (`thread_repository.py`, after `set_title`):
```python
    @abstractmethod
    def set_status(self, thread_id: ThreadId, status: ThreadStatus) -> None:
        """Store the thread's status (committed when this returns). (Callers check ownership first.)"""
```

Fake (`tests/fakes/tutoring.py`, `InMemoryThreads`):
```python
    def set_status(self, thread_id: ThreadId, status: ThreadStatus) -> None:
        self.threads[thread_id].status = status
```

SQL (`sql_threads.py`):
```python
    def set_status(self, thread_id: ThreadId, status: ThreadStatus) -> None:
        with self._engine.begin() as conn:
            conn.execute(threads.update().where(threads.c.thread_id == thread_id).values(status=status.value))
```

Service (`conversation_service.py`):
```python
    def archive_thread(self, thread_id: ThreadId, user_id: UserId) -> Thread:
        """The learner archives the conversation (US-13): it leaves the active list and is read-only; its history,
        documents used, and title stay. Archiving an archived one changes nothing."""
        thread = self._get(thread_id, user_id)
        thread.archive()
        self._threads.set_status(thread_id, thread.status)
        return thread

    def restore_thread(self, thread_id: ThreadId, user_id: UserId) -> Thread:
        """The learner restores the conversation: active again; restoring an active one changes nothing."""
        thread = self._get(thread_id, user_id)
        thread.restore()
        self._threads.set_status(thread_id, thread.status)
        return thread
```

`list_threads` gets `*, archived: bool = False` and passes `ThreadStatus.ARCHIVED if archived else ThreadStatus.ACTIVE`; update its docstring ("The learner's active conversations, or archived ones, newest last activity first ...").

`add_documents`: replace `self._owned(thread_id, user_id)` with
```python
        self._get(thread_id, user_id).require_active(CHANGE_ARCHIVED)
```
`remove_document`: after `thread = self._get(...)`, add `thread.require_active(CHANGE_ARCHIVED)`. Define at module top: `CHANGE_ARCHIVED = "An archived conversation can't be changed. Restore it first."`. Also use it in `Thread.limit_search`'s message? No — `thread.py` keeps its own literal (domain owns its messages); put `CHANGE_ARCHIVED` in `thread.py` as a module constant and use it both in `limit_search` and from the service (`from smart_tutor.tutoring.domain.thread import CHANGE_ARCHIVED, ...`).

- [ ] **Step 8: Run unit tests** — `uv run pytest tests/unit/tutoring -v` → PASS.

- [ ] **Step 9: Write the failing integration test** (append to `backend/tests/integration/tutoring/test_sql_threads.py`, using its existing fixtures for a repository and threads; mirror how existing tests there build and `add` a `Thread`)

```python
def test_set_status_archives_and_the_lists_follow(repo: SqlThreadRepository) -> None:
    active = Thread.start(ThreadId(str(uuid.uuid4())), UserId("ada"), NOW, title="Active")
    archived = Thread.start(ThreadId(str(uuid.uuid4())), UserId("ada"), NOW, title="Archived")
    other = Thread.start(ThreadId(str(uuid.uuid4())), UserId("bob"), NOW, title="Bob's")
    for t in (active, archived, other):
        repo.add(t)

    repo.set_status(ThreadId(archived.thread_id), ThreadStatus.ARCHIVED)
    repo.set_status(ThreadId(other.thread_id), ThreadStatus.ARCHIVED)

    assert [t.thread_id for t in repo.list_owned(UserId("ada"), ThreadStatus.ACTIVE)] == [active.thread_id]
    assert [t.thread_id for t in repo.list_owned(UserId("ada"), ThreadStatus.ARCHIVED)] == [archived.thread_id]
    got = repo.get_owned(ThreadId(archived.thread_id), UserId("ada"))
    assert got is not None and got.status is ThreadStatus.ARCHIVED and got.title == "Archived"

    repo.set_status(ThreadId(archived.thread_id), ThreadStatus.ACTIVE)
    assert repo.list_owned(UserId("ada"), ThreadStatus.ARCHIVED) == []
```

(Use the file's actual fixture name and user-id scheme — existing tests may use unique user ids per test to avoid cross-test rows; follow that.)

- [ ] **Step 10: Run the integration tests on the scratch database** (commands in Global Constraints) → PASS.

- [ ] **Step 11: Full backend checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest
git add backend
git commit -m "Archive and restore a thread in tutoring

A learner tidies their conversation list by archiving; an archived thread is
read-only, so adding or removing documents is now refused like asking,
renaming, and limiting the search (#189).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: API routes, isolation tests, client regeneration, PRD

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py`
- Test: `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py`
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`
- Modify: `sdd/prd.md`

**Interfaces:**
- Consumes: Task 1's `archive_thread`, `restore_thread`, `list_threads(..., archived=)`, `ThreadArchivedError` from add/remove.
- Produces (HTTP, and the generated web SDK functions `archiveThread`, `restoreThread`, `listThreads({ query: { archived } })`):
  - `POST /threads/{thread_id}/archive` → 200 `ThreadResponse`; 404 "Conversation not found".
  - `POST /threads/{thread_id}/restore` → 200 `ThreadResponse`; 404.
  - `GET /threads?archived=true|false` (default false) → `list[ThreadSummaryResponse]`.
  - `ThreadResponse = {thread_id: str, title: str | None, search_scope: "library"|"listed", status: "active"|"archived"}` (also from `GET /threads/{id}` and `PATCH`).
  - `POST /threads/{id}/documents` and `DELETE /threads/{id}/documents/{document_id}` → 409 with the domain message when archived.

- [ ] **Step 1: Write failing route tests** (append to `test_thread_routes.py`; `started_thread()` returns `(client, threads, thread)` with an active thread owned by the `AUTH` learner)

```python
def test_archive_and_restore_return_the_thread_and_change_only_its_status() -> None:
    client, threads, thread = started_thread()

    response = client.post(f"/threads/{thread.thread_id}/archive", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {
        "thread_id": thread.thread_id,
        "title": "What is attention?",
        "search_scope": "library",
        "status": "archived",
    }
    assert client.post(f"/threads/{thread.thread_id}/archive", headers=AUTH).json()["status"] == "archived"
    assert client.get("/threads", headers=AUTH).json() == []
    assert [t["thread_id"] for t in client.get("/threads?archived=true", headers=AUTH).json()] == [thread.thread_id]
    assert client.get(f"/threads/{thread.thread_id}", headers=AUTH).json()["status"] == "archived"

    response = client.post(f"/threads/{thread.thread_id}/restore", headers=AUTH)
    assert response.status_code == 200 and response.json()["status"] == "active"
    assert [t["thread_id"] for t in client.get("/threads", headers=AUTH).json()] == [thread.thread_id]
    assert client.get("/threads?archived=true", headers=AUTH).json() == []


@pytest.mark.parametrize("action", ["archive", "restore"])
def test_archiving_or_restoring_an_unknown_thread_is_404(action: str) -> None:
    client, _, _ = setup()
    response = client.post(f"/threads/{uuid.uuid4()}/{action}", headers=AUTH)
    assert response.status_code == 404 and response.json() == {"detail": "Conversation not found"}


def test_an_archived_thread_cant_add_or_remove_documents() -> None:
    client, threads, thread = started_thread()
    # Use the file's existing way of getting a ready document id for the AUTH learner (e.g. ingest_ready on the
    # library behind `client`); list one in the thread first through POST /threads/{id}/documents.
    ...
```

For the last test, follow the existing add/remove documents tests in this file (search `add_thread_documents` / `"/documents"`) to obtain a ready document and list it, then set `threads.threads[thread.thread_id].status = ThreadStatus.ARCHIVED` and assert:
```python
    added = client.post(f"/threads/{thread.thread_id}/documents", json={"document_ids": [other]}, headers=AUTH)
    assert added.status_code == 409
    assert added.json() == {"detail": "An archived conversation can't be changed. Restore it first."}
    removed = client.delete(f"/threads/{thread.thread_id}/documents/{listed}", headers=AUTH)
    assert removed.status_code == 409
    assert [d["document_id"] for d in client.get(f"/threads/{thread.thread_id}/documents", headers=AUTH).json()] == [listed]
```

Also update every existing assertion that compares a whole `ThreadResponse` body (e.g. the rename test asserting `{"thread_id", "title", "search_scope"}`) to include `"status": "active"`. Search: `grep -n '"search_scope":' backend/tests`.

- [ ] **Step 2: Run them to verify they fail** — `cd backend && uv run pytest tests/unit/apps/api/test_thread_routes.py -v` → new tests FAIL (404/405 from missing routes; missing `status`).

- [ ] **Step 3: Implement the routes** in `threads.py`:

```python
class ThreadResponse(BaseModel):
    thread_id: str
    title: str | None
    search_scope: Literal["library", "listed"]
    status: Literal["active", "archived"]


def _thread_response(thread: Thread) -> ThreadResponse:
    return ThreadResponse(
        thread_id=thread.thread_id,
        title=thread.title,
        search_scope=thread.search_scope.value,
        status=thread.status.value,
    )
```

`list_threads` gains `archived: bool = False` (FastAPI query param) and calls `conversations.list_threads(principal.user_id, archived=archived)`; docstring: "The learner's active conversations, or with `archived=true` the archived ones, newest last activity first ...".

```python
@router.post(
    "/threads/{thread_id}/archive",
    operation_id="archive_thread",
    responses={404: {"description": "Not the caller's conversation."}},
)
def archive_thread(thread_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations) -> ThreadResponse:
    """Archive the learner's conversation (PRD US-13): it leaves the active list and becomes read-only; its history,
    documents used, and title stay. Archiving an archived one changes nothing."""
    try:
        return _thread_response(conversations.archive_thread(ThreadId(str(thread_id)), principal.user_id))
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None


@router.post(
    "/threads/{thread_id}/restore",
    operation_id="restore_thread",
    responses={404: {"description": "Not the caller's conversation."}},
)
def restore_thread(thread_id: uuid.UUID, principal: CurrentPrincipal, conversations: Conversations) -> ThreadResponse:
    """Restore the learner's archived conversation: active again; restoring an active one changes nothing."""
    try:
        return _thread_response(conversations.restore_thread(ThreadId(str(thread_id)), principal.user_id))
    except ThreadNotFoundError as e:
        raise HTTPException(404, str(e)) from None
```

`add_thread_documents` and `remove_thread_document`: add `except ThreadArchivedError as e: raise HTTPException(409, str(e)) from None`, and add `409: {"description": "The conversation is archived."}` to both `responses`. Update the module docstring: "... The learner archives and restores a conversation; an archived one is read-only (US-13)."

- [ ] **Step 4: Run route tests** → PASS.

- [ ] **Step 5: Write the isolation test** (append to `backend/tests/isolation/test_threads.py`; update its module docstring to mention archive/restore and the archived list)

```python
def test_another_learner_cant_archive_restore_or_list_an_archived_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    services = api_services(library, threads=threads, agent=fake_agent(answers))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [thread] = threads.threads.values()

    assert client.post(f"/threads/{thread.thread_id}/archive", headers=B).status_code == 404
    assert threads.threads[thread.thread_id].status.value == "active"

    assert client.post(f"/threads/{thread.thread_id}/archive", headers=A).status_code == 200
    assert client.get("/threads?archived=true", headers=B).json() == []
    assert client.post(f"/threads/{thread.thread_id}/restore", headers=B).status_code == 404
    assert threads.threads[thread.thread_id].status.value == "archived"
    assert [t["thread_id"] for t in client.get("/threads?archived=true", headers=A).json()] == [thread.thread_id]
```

Run: `uv run pytest tests/isolation/test_threads.py -v` → PASS.

- [ ] **Step 6: Regenerate the OpenAPI snapshot and the web client** (from repo root)

```bash
cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate
```
Then `cd web && npm run build` must still pass (the new `status` field is required on `ThreadResponse`: fix any web test fixture that builds a `ThreadResponse` literal by adding `status: "active"`; run `npx vitest run` to find them).

- [ ] **Step 7: Update the PRD** — in `sdd/prd.md` bump the status line to `Draft v2.49` and add a row directly under the status row:

```markdown
| **Changes from v2.48** | Archive and restore a conversation (#189, US-13): `POST /threads/{id}/archive` and `POST /threads/{id}/restore` (operations `archive_thread`, `restore_thread`) change only the owner's thread `status` and return it (repeating either is harmless); `GET /threads?archived=true` lists archived threads in the same order; `ThreadResponse` carries `status`. An archived thread is read-only: asking, renaming, changing the search scope, and adding or removing documents return `409`; its history, documents used, citations, and ratings still read, and a turn can still be rated. The web's Conversations page has Active and Archived tabs with Archive / Restore in each row's More menu; an archived conversation shows "This conversation is archived." with Restore above a disabled composer, its title can't be edited, its panel's document and scope controls are off, and the panel's Actions offer "Restore conversation". It leaves the side nav's recent list until restored. |
```
Keep `AGENTS.md`'s PRD version reference (`sdd/prd.md` (v2.44)) as is unless it already tracks the latest version (check `git log -p -1 -- AGENTS.md`; if earlier slices bumped it, bump it to v2.49).

- [ ] **Step 8: Full checks and commit**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest
cd ../web && npx vitest run && npm run build
git add backend web/src/api sdd/prd.md
git commit -m "Add archive and restore routes for a conversation

The web needs to archive a conversation, list the archived ones, and know
whether an opened one is archived (#189); adding or removing documents in an
archived conversation is now a 409 like the other changes.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Conversations page — Active and Archived tabs, row Archive / Restore

**Files:**
- Modify: `web/src/api/conversations.ts`, `web/src/api/conversations.test.ts`
- Modify: `web/src/features/conversations/ConversationTable.tsx`, `ConversationTable.module.css`, `ConversationTable.test.tsx`
- Modify: `web/src/features/conversations/ConversationsPage.tsx`, `ConversationsPage.module.css`, `ConversationsPage.test.tsx`

**Interfaces:**
- Consumes: generated `listThreads`, `archiveThread`, `restoreThread`, types `ThreadSummaryResponse`, `ThreadResponse`; `useConversations()` (`{ list, failed, refresh }`, the shell's **active** list); components `Tabs`, `RowMenu`, `EmptyState`, `Button`, `PageHeader`.
- Produces:
  - `listConversations(options?: { archived?: boolean }, apiClient?: Client): Promise<ThreadSummaryResponse[]>` (existing callers pass nothing → active).
  - `archiveConversation(threadId: string, apiClient?: Client): Promise<ThreadResponse>`; `restoreConversation(threadId: string, apiClient?: Client): Promise<ThreadResponse>`. Both throw `SessionExpiredError` on 401, `Error` otherwise. Re-export `ThreadResponse` type from this module.
  - `ConversationTable` props: `{ conversations: ThreadSummaryResponse[]; archived: boolean; onArchive: (t) => void; onRestore: (t) => void; busy?: ReadonlySet<string> }`.
  - `ConversationsPage` props (for tests): `{ loadArchived?: () => Promise<ThreadSummaryResponse[]>; archive?: (id: string) => Promise<unknown>; restore?: (id: string) => Promise<unknown> }`, defaulting to the API functions.

- [ ] **Step 1: API client tests first** — in `conversations.test.ts`, mirroring the existing `listConversations` tests there (they stub the client's fetch): `listConversations({ archived: true })` requests `/threads?archived=true`; `archiveConversation("t1")` POSTs `/threads/t1/archive` and returns the body; `restoreConversation` POSTs `/threads/t1/restore`; a 401 throws `SessionExpiredError`; a 404 throws `Error`. Run `cd web && npx vitest run src/api/conversations.test.ts` → FAIL.

- [ ] **Step 2: Implement** in `conversations.ts`:

```ts
import { archiveThread, listThreads, restoreThread } from "./generated/sdk.gen";
import type { ThreadResponse, ThreadSummaryResponse } from "./generated/types.gen";

export type { ThreadResponse, ThreadSummaryResponse };

// The learner's active conversations, or archived ones, newest last activity first (owner only).
export async function listConversations({ archived = false }: { archived?: boolean } = {}, apiClient: Client = client): Promise<ThreadSummaryResponse[]> {
  const { data, error, response } = await listThreads({ client: apiClient, query: archived ? { archived: true } : undefined, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /threads failed (${response?.status ?? "no response"})`);
  return data;
}

// Archive or restore the learner's conversation (US-13); repeating either is harmless.
export async function archiveConversation(threadId: string, apiClient: Client = client): Promise<ThreadResponse> {
  const { data, error, response } = await archiveThread({ client: apiClient, path: { thread_id: threadId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`Archiving failed (${response?.status ?? "no response"})`);
  return data;
}

export async function restoreConversation(threadId: string, apiClient: Client = client): Promise<ThreadResponse> {
  const { data, error, response } = await restoreThread({ client: apiClient, path: { thread_id: threadId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`Restoring failed (${response?.status ?? "no response"})`);
  return data;
}
```
Check the existing caller of `listConversations` (the app shell passes it as `load`); `listConversations` called with no args still works. If the shell passes it directly as a function reference that receives arguments, wrap it: `() => listConversations()`. Run the API tests → PASS.

- [ ] **Step 3: ConversationTable tests first** (add to `ConversationTable.test.tsx`, following its render helper with a `MemoryRouter`):
  - "an active row's menu offers Open and Archive": click the button named `Actions for <title>`; menu items are exactly `["Open", "Archive"]`; clicking Archive calls `onArchive` with that row; the row's click-to-open does **not** navigate when the menu button or an item is clicked.
  - "an archived row's menu offers Open and Restore": with `archived`, items `["Open", "Restore"]`; Restore calls `onRestore`.
  - "Open navigates to the conversation": `/chat/<id>`.
  - "a busy row's menu is disabled": `busy={new Set([id])}` → menu button disabled.
  Run → FAIL.

- [ ] **Step 4: Implement ConversationTable** — add a fifth, header-less column (`<th scope="col"><span className="visually-hidden">Actions</span></th>`) and per row:

```tsx
<td className={styles.actions}>
  <RowMenu
    label={`Actions for ${title}`}
    disabled={busy?.has(t.thread_id)}
    items={[
      { label: "Open", icon: MessageSquare, onSelect: () => navigate(path) },
      archived
        ? { label: "Restore", icon: ArchiveRestore, onSelect: () => onRestore(t) }
        : { label: "Archive", icon: Archive, onSelect: () => onArchive(t) },
    ]}
  />
</td>
```
The row's `onClick` ignores clicks inside links, buttons, and menus: `if (!(event.target as HTMLElement).closest("a, button, [role='menu']")) navigate(path);`. CSS: `.actions { width: 40px; text-align: right; }` (match the Library table's actions column in `DocumentTable.module.css` for width and padding; use tokens only). Run → PASS.

- [ ] **Step 5: ConversationsPage tests first** (extend `ConversationsPage.test.tsx`, which already renders the page inside a `ConversationsContext.Provider`; inject `loadArchived`, `archive`, `restore` as `vi.fn()`):
  - "tabs show active and archived counts": context list of 2, `loadArchived` resolves 1 → tabs "Active 2", "Archived 1"; Active selected; header count "2 conversations".
  - "the Archived tab lists archived conversations with the notice": select Archived → row of the archived one; text "Archived conversations stay readable. Restore one to keep asking."; Active rows not shown.
  - "an empty Archived tab": `loadArchived` resolves `[]` → "No archived conversations" and its body.
  - "Active empty while archived exist": context list `[]`, archived 1 → "No active conversations", action "Start a conversation".
  - "both empty": "No conversations yet" (existing test still passes; tabs may be shown).
  - "archiving from the list refreshes the shell list": choose Archive on a row → `archive` called with its id; then the context's `refresh` called and `loadArchived` called again; status text "<title> archived. Find it under Archived."
  - "restoring from the Archived tab": Restore → `restore` called; `refresh` and `loadArchived` called; status "<title> restored."
  - "a failed archive says so": `archive` rejects `new Error("x")` → status "Couldn't archive <title>. Try again."; a `SessionExpiredError` rejection says nothing.
  Run → FAIL.

- [ ] **Step 6: Implement ConversationsPage**:

```tsx
type View = "active" | "archived";
const ARCHIVED_NOTICE = "Archived conversations stay readable. Restore one to keep asking.";

export function ConversationsPage({ loadArchived = defaultLoadArchived, archive = archiveConversation, restore = restoreConversation }: Props) {
  const { list, failed, refresh } = useConversations();
  const [view, setView] = useState<View>("active");
  const [archived, setArchived] = useState<ThreadSummaryResponse[] | null>(null);
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [status, setStatus] = useState("");
  const statusRegion = useRef<HTMLParagraphElement>(null);
  // ... reloadArchived(): latest-call-wins like useConversationsState; a failure keeps the last list.
  // useEffect(() => void reloadArchived(), []) on mount.

  async function change(t: ThreadSummaryResponse, archiving: boolean) {
    const title = conversationTitle(t);
    setBusy((s) => new Set(s).add(t.thread_id));
    try {
      await (archiving ? archive : restore)(t.thread_id);
      setStatus(archiving ? `${title} archived. Find it under Archived.` : `${title} restored.`);
    } catch (error) {
      if (!(error instanceof SessionExpiredError)) setStatus(`Couldn't ${archiving ? "archive" : "restore"} ${title}. Try again.`);
    }
    refresh(); // the shell's active list: the page's Active tab and the side nav's recent ones
    await reloadArchived();
    setBusy((s) => { const n = new Set(s); n.delete(t.thread_id); return n; });
    statusRegion.current?.focus(); // the row left this list, and its menu with it
  }
  ...
}
```
Render order: `PageHeader` (unchanged, active count) → `<p role="status" tabIndex={-1} ref={statusRegion} className="visually-hidden">{status}</p>` → when `list !== null` (or `archived !== null`): `Tabs label="Conversations view"` with `{ value: "active", label: "Active", count: list?.length }`, `{ value: "archived", label: "Archived", count: archived?.length }` → in Archived view the notice paragraph (copy the Library's `.notice` style: `Info` icon, `var(--info)`; put the class in `ConversationsPage.module.css`) → the empty states from Global Constraints → `ConversationTable` with `archived={view === "archived"}`, `onArchive={(t) => void change(t, true)}`, `onRestore={(t) => void change(t, false)}`, `busy={busy}`. The tabs' bottom border and spacing follow the Library toolbar (look at `LibraryPage.module.css .toolbar`) with tokens. Run → PASS.

- [ ] **Step 7: Look at it** — run the app or render the page in both themes and compare with `.design-shots/v0.10/conversations-archived.{light,dark}.png` and `conversations-active.*`. Known, intended differences to note in the PR: no filters/search/sort (own slices), no preview text, no Note badge, and the notice line under the Archived tab (asked by the ticket, absent from the mockup).

- [ ] **Step 8: Checks and commit**

```bash
cd web && npx vitest run && npm run build
git add web/src
git commit -m "Archive and restore conversations from the Conversations page

Learners tidy their list by archiving a conversation from its row and find it
again under an Archived tab, where Restore brings it back (#189).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: An archived conversation in Chat — banner, read-only controls, archive and restore

**Files:**
- Modify: `web/src/components/Banner/Banner.tsx`, `Banner.test.tsx`
- Modify: `web/src/features/chat/ConversationPanel.tsx`, `ConversationPanel.test.tsx`
- Modify: `web/src/features/chat/ChatPage.tsx`, `ChatPage.module.css`, `ChatPage.test.tsx`
- Modify: `web/src/features/chat/ThreadTitle.tsx` (doc comment of `editable` only)

**Interfaces:**
- Consumes: `archiveConversation`, `restoreConversation` (Task 3); `ThreadResponse.status` from `loadConversation` (Task 2); `useConversations().refresh`.
- Produces:
  - `Banner` gains optional `icon?: LucideIcon` overriding the variant's icon.
  - `ConversationPanel` gains props `archived?: boolean` (default false), `onArchive?: () => void`, `onRestore?: () => void`, `actionsDisabled?: boolean`. When `archived`: no remove buttons, no Add documents, the scope switch disabled, and Actions shows "Restore conversation" (calls `onRestore`) instead of "Archive conversation" (calls `onArchive`; was always disabled before). Both buttons carry `data-thread-action` and are disabled when `actionsDisabled`. The doc comment drops "Archive conversation (US-13) stay[s] disabled until their stories".
  - `ChatPage` gains props `archive?: (threadId: string) => Promise<unknown>` and `restore?: (threadId: string) => Promise<unknown>` (defaults `archiveConversation`, `restoreConversation`).

- [ ] **Step 1: Banner** — test: `render(<Banner variant="info" icon={Archive} title="t" />)` renders the given icon (assert via a `data-testid` is not available on lucide icons; assert the svg has class `lucide-archive`). Implement: `const Icon = icon ?? ICONS[variant];`. Run `npx vitest run src/components/Banner` → PASS.

- [ ] **Step 2: ConversationPanel tests first** (extend `ConversationPanel.test.tsx`, using its render helper with `threadId="t1"` and one listed document):
  - "an active conversation offers Archive conversation": the button is enabled; clicking it calls `onArchive`.
  - "an archived conversation is read-only and offers Restore conversation": `archived` → no button named `Remove <title> from this conversation`; no "Add documents"; the "Only search these documents" switch is disabled; "Restore conversation" calls `onRestore`; no "Archive conversation". The document row's open button still calls `onOpen`.
  - "actions are disabled while busy": `actionsDisabled` → "Archive conversation" disabled.
  Update the existing test that expected "Archive conversation" to be disabled. Run → FAIL.

- [ ] **Step 3: Implement ConversationPanel**: guard remove buttons with `onRemoveDocument && !archived`, Add documents with `!archived`, the switch's `disabled` with `|| archived`; Actions:

```tsx
{threadId !== null &&
  (archived ? (
    <Button variant="quiet" size="sm" icon={ArchiveRestore} className={styles.action} data-thread-action disabled={actionsDisabled} onClick={onRestore}>
      Restore conversation
    </Button>
  ) : (
    <Button variant="quiet" size="sm" icon={Archive} className={styles.action} data-thread-action disabled={actionsDisabled || !onArchive} onClick={onArchive}>
      Archive conversation
    </Button>
  ))}
```
Run → PASS.

- [ ] **Step 4: ChatPage tests first** (extend `ChatPage.test.tsx`; it already renders `ChatPage` at `/chat/<id>` with an injected `loadConversation` and a `ConversationsContext` whose `refresh` can be a `vi.fn()` — follow the existing "opens a conversation from its URL" tests). Use `thread: { thread_id: "t1", title: "What is attention?", search_scope: "library", status: "archived" }` with one kept turn that has a citation.
  - "an archived conversation shows the banner, a disabled composer, and a plain title": text "This conversation is archived." and "Restore it to keep asking."; the textbox "Your question" is disabled with placeholder "Archived conversation"; the Ask button disabled; no rename affordance (the title isn't a button — follow how existing tests check `editable={false}`); the history and its Sources chip render and the chip still opens the document (existing citation-open assertion pattern).
  - "the banner's Restore is keyboard-reachable": `await user.tab()` repeatedly (or `screen.getByRole("button", { name: "Restore" })` and `.focus()` then `user.keyboard("{Enter}")`) calls `restore("t1")`.
  - "restoring from the banner brings the controls back and focuses the composer": after `restore` resolves → banner gone, textbox enabled with placeholder "Ask about your documents", title editable, panel shows "Archive conversation", "Add documents" visible; `document.activeElement` is the textbox; `refresh` called; status region text "Conversation restored.".
  - "archiving from the panel makes it read-only": active conversation → click "Archive conversation" → `archive("t1")` called; banner appears; textbox disabled; `refresh` called (**"archiving refreshes the shell list"**); status "Conversation archived."; focus on the panel's "Restore conversation" button.
  - "a failed archive keeps the conversation active": `archive` rejects → no banner; textbox enabled; page problem text "Couldn't archive this conversation. Try again.".
  - "archive is disabled while answering": start an answer whose stream never ends (existing pattern for an in-flight answer) → "Archive conversation" disabled.
  - "an archived conversation's decline buttons are disabled": a kept last turn with decline `{ code: "limited", ... }` in an archived conversation → "Add documents" (in the decline card) and "Search all my documents" disabled.
  - "opening another conversation clears the archived state": navigate from an archived `/chat/t1` to an active `/chat/t2` → no banner.
  Run → FAIL.

- [ ] **Step 5: Implement ChatPage**:
  - State `const [archived, setArchived] = useState(false);` and `const [changingStatus, setChangingStatus] = useState(false);`; `reset()` sets both false; `openConversation` sets `setArchived(thread.status === "archived")`.
  - `canAsk` adds `&& !archived`; `submit()` returns early when `archived`.
  - Handlers:
```tsx
  // Archive or restore the conversation (US-13). Only its status changes; the history stays where it is.
  async function changeArchived(archiving: boolean) {
    if (threadId === null) return;
    const forTurn = turn.current;
    setChangingStatus(true);
    try {
      await (archiving ? archive : restore)(threadId);
      if (!alive.current || turn.current !== forTurn) return;
      setArchived(archiving);
      setProblem(null);
      setAnnouncement(archiving ? "Conversation archived." : "Conversation restored.");
      setFocusAfterStatus(archiving ? "action" : "composer");
    } catch (error) {
      if (!alive.current || turn.current !== forTurn || error instanceof SessionExpiredError) return;
      const message = `Couldn't ${archiving ? "archive" : "restore"} this conversation. Try again.`;
      setProblem({ message } as Problem); // match the Problem type's shape used elsewhere in this file
      setAnnouncement(message);
    } finally {
      if (alive.current) setChangingStatus(false);
      conversations.refresh(); // the side nav's recent list drops or regains it
    }
  }
```
    `focusAfterStatus` is a small state (`"action" | "composer" | null`) consumed by an effect after render: `"composer"` → `input.current?.focus()`; `"action"` → `pageRef.current?.querySelector<HTMLElement>("[data-thread-action]")?.focus()`; then reset to null. (If the panel is hidden, the action button doesn't exist: fall back to `toggleRef.current?.focus()`.) A page `problem` currently renders under the last turn; if there are no turns, render it above the composer instead — check how `problem` is shown and keep the message visible in both cases.
  - `ThreadTitle editable={threadId !== null && !archived}`.
  - Panel: pass `archived`, `onArchive={() => void changeArchived(true)}`, `onRestore={() => void changeArchived(false)}`, `actionsDisabled={answering || changingStatus}`; `onAddDocuments` and `onRemoveDocument` unchanged (the panel hides them when archived); `onSearchListedChange` unchanged (the panel disables the switch).
  - Decline buttons ("Add documents", "Search all my documents"): add `|| archived` to `disabled`. Also the "Change" link in the scope line: hide it when `archived`.
  - Above the composer (inside the `<form>` before `.composer`, after the scope line):
```tsx
{archived && (
  <Banner
    variant="info"
    icon={Archive}
    title="This conversation is archived."
    action={<Button variant="primary" size="sm" icon={ArchiveRestore} disabled={changingStatus} onClick={() => void changeArchived(false)}>Restore</Button>}
  >
    Restore it to keep asking.
  </Banner>
)}
```
    Check `Button`'s `size`/`variant` props for the exact names (`size="sm"` is used by the panel). Two-line banner as in the mockup (title on one line, text on the next): don't pass `inline`. Spacing between banner and composer: `margin-bottom: var(--space-2)` (use the token the scope line uses) via a class in `ChatPage.module.css` if `Banner` takes no `className`; wrap it in a `<div className={styles.archivedBanner}>`.
  - Textarea: `disabled={answering || archived}`, `placeholder={archived ? "Archived conversation" : "Ask about your documents"}`.
  - Update the component's header comment: an archived conversation is read-only (banner with Restore; composer, title, and the panel's document controls off); citations, documents, and ratings still work.
  Run → PASS.

- [ ] **Step 6: ThreadTitle** — change the `editable` doc comment to "Off while there is no conversation to rename yet, or while it is archived: the title is plain text."

- [ ] **Step 7: Look at it** — compare with `.design-shots/v0.10/chat-archived.{light,dark}.png` in both themes (the app, or Vitest browser screenshots if the repo has them; otherwise `make web` against the Compose stack, archive a conversation, and look). Note intended differences in the PR: the mockup keeps "Add documents" and the scope switch visible (the ticket says the panel can't change them: hidden / disabled here), and the token counter under the composer is not built.

- [ ] **Step 8: Checks and commit**

```bash
cd web && npx vitest run && npm run build
git add web/src
git commit -m "Show an archived conversation read-only with Restore

An archived conversation is read-only (US-13): its banner offers Restore, the
composer, title, and document controls are off, and the panel's Actions archive
or restore it without a reload (#189).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Whole-branch verification

- [ ] **Step 1:** All checks from repo root:
```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest
SMART_TUTOR_DATABASE_URL=postgresql+psycopg://smart_tutor:smart_tutor@localhost:10400/smart_tutor_it189 uv run pytest -m integration tests/integration/tutoring
cd ../web && npx vitest run && npm run build
```
- [ ] **Step 2:** Confirm `web/src/api/openapi.json` is current: `cd backend && uv run pytest tests/unit/apps/api/test_openapi_snapshot.py`.
- [ ] **Step 3:** Walk the acceptance criteria of #189 one by one and name the test that covers each in the PR description.

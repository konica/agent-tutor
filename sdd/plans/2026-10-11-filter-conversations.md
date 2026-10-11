# Filter Conversations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The learner narrows the Conversations list by last-activity date range, subject, and title search, combined, in owner-scoped SQL (#190, US-13, US-13b Q63).

**Architecture:** `GET /threads` gains `subject_id` (repeatable, any of), `active_from` / `active_to` (inclusive GMT+7 calendar days, D27) and `q` (case-insensitive title substring). `ConversationService.list_threads` turns subjects into the learner's document ids through `knowledge`'s `DocumentService` (archived included; a deleted document is gone, so its subjects no longer count, L1), turns days into datetimes in the app time zone, and passes one `ThreadFilter` to `ThreadRepository.list_owned`, whose SQL applies it under the owner scope. The web Conversations page adds a filter bar (Search titles, Subject, Date) built from the Library's `FilterBar`, `FilterField` and its date-range popover, loads filtered results itself (the shell's unfiltered list keeps feeding the side nav and the header count), and shows "No conversations match these filters" with Clear filters.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2.1 Core (Postgres), pytest; React 19 + TypeScript + Vite, Vitest + Testing Library; generated `@hey-api` client in `web/src/api/generated/`.

**Spec:** GitHub issue #190 (parent US-13 #23); PRD `sdd/prd.md` §8 US-13, US-13b, D11, D27, Q63; design round `design-v0.10` states `conversations-filtered`, `conversations-no-results` (prototype `sdd/design/prototype/js/screens.js` → `ST.conversationsView` at that tag).

## Global Constraints

- Every read stays owner-scoped in SQL: `threads.user_id = :user` in the same statement as the filter; tutoring never reads `knowledge` tables (backend AGENTS.md rule 2) — subject → documents goes through `DocumentService`.
- Dates are inclusive calendar days in the app time zone (`app-time-zone`, `Asia/Ho_Chi_Minh`, D27): `active_from` → `>= from 00:00`, `active_to` → `< (to + 1 day) 00:00`.
- Last activity is `coalesce(last_learner_message_at, created_at)` (same as the list's order and `Thread.last_activity`).
- Subject filter matches when any document **listed** for the thread (any `thread_documents` row) that still exists has the subject; archived documents count, deleted don't (D11, Q63 L1). Same rule as the chips.
- Title search: titles only, case-insensitive, `%`, `_` and `/` are literal; never searches turns/answers (Q63 N3). Blank or whitespace-only `q` means no filter. `q` max length 120 (MAX_TITLE).
- UI copy (prototype v0.10): search placeholder and label "Search titles"; subject select first option "All subjects"; date button "Date"; no-results title "No conversations match these filters", text "Try another subject, a wider date range or another search.", button "Clear filters"; bar count noun "conversation".
- Subject choices are the learner's subjects (`GET /me/subjects`, `loadMySubjects`), by their names.
- The Active/Archived tab (#189) and the sort select are not in this slice; filters apply to the active list.
- Commit subjects in the imperative mood; the body says why; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Windows Git Bash: run backend commands from `backend/` as `uv run ...`; integration tests need `uv run --env-file ../.env pytest -m integration ...` (Compose Postgres on :10400 is up).

## Review Focus

1. A search with `%`, `_` or `/` (e.g. "100%") matches only titles containing that literal text — pinned in Task 1 (SQL) and Task 2 (fake via `Thread.matches`).
2. A whitespace-only search box narrows nothing (and the web doesn't count it as an active filter) — pinned in Task 2 (service) and Task 5 (web).
3. A conversation last active at 00:30 GMT+7 (17:30 UTC the day before) belongs to the GMT+7 day, not the UTC day — pinned in Task 2.
4. Typing fast or changing filters quickly never shows an older response over a newer one, and the side nav keeps listing the three most recent unfiltered conversations — pinned in Task 5.
5. A subject that only a deleted document had, or a subject the learner has no document for, returns an empty list, not every thread (no `IN ()` crash, no dropped filter) — pinned in Task 1 (empty set) and Task 2.

---

## File map

| File | Responsibility |
|---|---|
| `backend/src/smart_tutor/tutoring/domain/thread.py` | `ThreadFilter`, `NO_THREAD_FILTER`, `Thread.matches` (twin of the SQL) |
| `backend/src/smart_tutor/tutoring/ports/thread_repository.py` | `list_owned(user_id, status, thread_filter=NO_THREAD_FILTER)` |
| `backend/src/smart_tutor/tutoring/adapters/sql_threads.py` | SQL `WHERE` for the filter |
| `backend/tests/fakes/tutoring.py` | fake `list_owned` uses `Thread.matches` |
| `backend/src/smart_tutor/knowledge/application/document_service.py` | `documents_with_subjects` |
| `backend/src/smart_tutor/tutoring/application/conversation_service.py` | `list_threads` filters; `time_zone` ctor arg |
| `backend/src/smart_tutor/apps/api/services.py`, `backend/tests/fakes/api.py` | pass the app time zone |
| `backend/src/smart_tutor/apps/api/routes/threads.py` | query params on `GET /threads` |
| `backend/tests/isolation/test_threads.py` | shared-subject filter isolation |
| `web/src/components/DateRangeFilter/` | date-range popover moved out of `features/library/UploadedFilter` |
| `web/src/api/conversations.ts` | `ConversationFilters`, `listConversations(filters)` |
| `web/src/features/conversations/ConversationFilters.tsx` | the bar: Search titles, Subject, Date |
| `web/src/features/conversations/useFilteredConversations.ts` | latest-wins load of the filtered list |
| `web/src/features/conversations/ConversationsPage.tsx` | bar, filtered rows, no-results state |
| `sdd/prd.md`, `backend/src/smart_tutor/tutoring/README.md` | v2.49 change line; README mention |

---

### Task 1: Thread filter in the domain, the port, SQL and the fake

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/domain/thread.py`
- Modify: `backend/src/smart_tutor/tutoring/ports/thread_repository.py`
- Modify: `backend/src/smart_tutor/tutoring/adapters/sql_threads.py` (`list_owned`)
- Modify: `backend/tests/fakes/tutoring.py` (`InMemoryThreads.list_owned`)
- Test: `backend/tests/unit/tutoring/test_thread.py`, `backend/tests/integration/tutoring/test_sql_threads.py`

**Interfaces:**
- Produces:
  ```python
  @dataclass(frozen=True)
  class ThreadFilter:
      document_ids: frozenset[DocumentId] | None = None
      active_from: datetime | None = None   # inclusive
      active_before: datetime | None = None # exclusive
      title: str | None = None              # case-insensitive substring
  NO_THREAD_FILTER = ThreadFilter()
  Thread.matches(self, thread_filter: ThreadFilter, listed: Collection[DocumentId]) -> bool
  ThreadRepository.list_owned(self, user_id: UserId, status: ThreadStatus, thread_filter: ThreadFilter = NO_THREAD_FILTER) -> list[Thread]
  ```

- [ ] **Step 1: Write failing domain tests** (append to `backend/tests/unit/tutoring/test_thread.py`; reuse its existing imports, add `ThreadFilter`, `DocumentId`, `timedelta` if missing)

```python
def test_no_filter_matches_every_thread() -> None:
    thread = Thread.start(ThreadId("t"), UserId("ada"), datetime(2026, 10, 1, tzinfo=UTC), title="Q?")
    assert thread.matches(ThreadFilter(), [])


def test_matches_by_last_activity_from_inclusive_and_before_exclusive() -> None:
    at = datetime(2026, 10, 1, 12, tzinfo=UTC)
    thread = Thread.start(ThreadId("t"), UserId("ada"), at)
    assert thread.matches(ThreadFilter(active_from=at, active_before=at + timedelta(seconds=1)), [])
    assert not thread.matches(ThreadFilter(active_from=at + timedelta(seconds=1)), [])
    assert not thread.matches(ThreadFilter(active_before=at), [])


def test_matches_when_any_listed_document_is_one_of_the_filters() -> None:
    thread = Thread.start(ThreadId("t"), UserId("ada"), datetime(2026, 10, 1, tzinfo=UTC))
    d1, d2 = DocumentId("d1"), DocumentId("d2")
    assert thread.matches(ThreadFilter(document_ids=frozenset({d2})), [d1, d2])
    assert not thread.matches(ThreadFilter(document_ids=frozenset({d2})), [d1])
    assert not thread.matches(ThreadFilter(document_ids=frozenset()), [d1])


def test_title_matches_case_insensitively_and_literally() -> None:
    thread = Thread.start(ThreadId("t"), UserId("ada"), datetime(2026, 10, 1, tzinfo=UTC), title="Is RAG 100% grounded?")
    assert thread.matches(ThreadFilter(title="rag"), [])
    assert thread.matches(ThreadFilter(title="100%"), [])
    assert not thread.matches(ThreadFilter(title="1_0"), [])
    untitled = Thread.start(ThreadId("u"), UserId("ada"), datetime(2026, 10, 1, tzinfo=UTC))
    assert not untitled.matches(ThreadFilter(title="rag"), [])
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/unit/tutoring/test_thread.py -q` — expect ImportError on `ThreadFilter`.

- [ ] **Step 3: Implement in `thread.py`** (add imports `from collections.abc import Collection`, `DocumentId`; put the filter above `class Thread`)

```python
@dataclass(frozen=True)
class ThreadFilter:
    """What the Conversations list narrows to (PRD US-13, US-13b); `None` puts no constraint on that part."""

    document_ids: frozenset[DocumentId] | None = None  # the thread lists any of them (a subject's documents)
    active_from: datetime | None = None  # last activity, inclusive
    active_before: datetime | None = None  # last activity, exclusive
    title: str | None = None  # a case-insensitive part of the title, taken literally (Q63: titles only)


NO_THREAD_FILTER = ThreadFilter()
```

and on `Thread`:

```python
    def matches(self, thread_filter: ThreadFilter, listed: Collection[DocumentId]) -> bool:
        """The Conversations filter (US-13); `listed` is the thread's document list. The SQL `WHERE` of
        `SqlThreadRepository.list_owned` is its twin."""
        f = thread_filter
        return (
            (f.document_ids is None or not f.document_ids.isdisjoint(listed))
            and (f.active_from is None or self.last_activity >= f.active_from)
            and (f.active_before is None or self.last_activity < f.active_before)
            and (f.title is None or (self.title is not None and f.title.lower() in self.title.lower()))
        )
```

- [ ] **Step 4: Port** — in `thread_repository.py` import `NO_THREAD_FILTER, ThreadFilter` and change:

```python
    @abstractmethod
    def list_owned(
        self, user_id: UserId, status: ThreadStatus, thread_filter: ThreadFilter = NO_THREAD_FILTER
    ) -> list[Thread]:
        """The learner's threads in this status that match the filter, newest last activity first (then newest
        started; scoped by owner)."""
```

- [ ] **Step 5: Fake** — `InMemoryThreads.list_owned` in `backend/tests/fakes/tutoring.py`:

```python
    def list_owned(
        self, user_id: UserId, status: ThreadStatus, thread_filter: ThreadFilter = NO_THREAD_FILTER
    ) -> list[Thread]:
        mine = [
            copy.deepcopy(t)
            for t in self.threads.values()
            if t.user_id == user_id
            and t.status is status
            and t.matches(thread_filter, [r.document_id for r in self.documents_used_rows.get(t.thread_id, [])])
        ]
        mine.sort(key=lambda t: t.thread_id)
        mine.sort(key=lambda t: (t.last_activity, t.created_at), reverse=True)
        return mine
```

- [ ] **Step 6: Run** the domain tests — PASS.

- [ ] **Step 7: Failing SQL integration tests** (append to `backend/tests/integration/tutoring/test_sql_threads.py`; import `ThreadFilter`, `DocumentId`)

```python
def test_list_owned_filters_by_last_activity_documents_and_title(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner, other = UserId(f"ada-{uuid.uuid4()}"), UserId(f"bob-{uuid.uuid4()}")
    t0 = datetime(2026, 10, 1, tzinfo=UTC)
    early = Thread.start(ThreadId(str(uuid.uuid4())), owner, t0, title="What is RAG?")
    late = Thread.start(ThreadId(str(uuid.uuid4())), owner, t0 + timedelta(days=2), title="Is it 100% grounded?")
    quiet = Thread(ThreadId(str(uuid.uuid4())), owner, t0 + timedelta(days=1), title="rag again")  # no question yet
    theirs = Thread.start(ThreadId(str(uuid.uuid4())), other, t0, title="What is RAG?")
    for t in (early, late, quiet, theirs):
        repo.add(t)
    doc, their_doc = DocumentId(str(uuid.uuid4())), DocumentId(str(uuid.uuid4()))
    repo.add_documents(early.thread_id, [doc], t0)
    repo.add_documents(theirs.thread_id, [doc, their_doc], t0)

    def ids(f: ThreadFilter) -> list[str]:
        return [t.thread_id for t in repo.list_owned(owner, ThreadStatus.ACTIVE, f)]

    assert ids(ThreadFilter()) == [late.thread_id, quiet.thread_id, early.thread_id]
    assert ids(ThreadFilter(active_from=t0 + timedelta(days=1))) == [late.thread_id, quiet.thread_id]
    assert ids(ThreadFilter(active_before=t0 + timedelta(days=1))) == [early.thread_id]
    assert ids(ThreadFilter(document_ids=frozenset({doc}))) == [early.thread_id]
    assert ids(ThreadFilter(document_ids=frozenset({their_doc}))) == []
    assert ids(ThreadFilter(document_ids=frozenset())) == []
    assert ids(ThreadFilter(title="RAG")) == [quiet.thread_id, early.thread_id]
    assert ids(ThreadFilter(title="100%")) == [late.thread_id]
    assert ids(ThreadFilter(title="%")) == [late.thread_id]
    assert ids(ThreadFilter(title="_s")) == []
    assert ids(ThreadFilter(title="rag", active_from=t0 + timedelta(hours=1))) == [quiet.thread_id]
```

- [ ] **Step 8: Run** `cd backend && uv run --env-file ../.env pytest -m integration tests/integration/tutoring/test_sql_threads.py -q` — expect TypeError (unexpected argument).

- [ ] **Step 9: SQL** — `SqlThreadRepository.list_owned` (import `exists`, `false` from sqlalchemy; `NO_THREAD_FILTER, ThreadFilter`):

```python
    def list_owned(
        self, user_id: UserId, status: ThreadStatus, thread_filter: ThreadFilter = NO_THREAD_FILTER
    ) -> list[Thread]:
        f = thread_filter
        last_activity = func.coalesce(threads.c.last_learner_message_at, threads.c.created_at)
        stmt = (
            select(threads)
            .where(threads.c.user_id == user_id, threads.c.status == status.value)
            .order_by(last_activity.desc(), threads.c.created_at.desc(), threads.c.thread_id)
        )
        # The twin of Thread.matches: each part applies only when set.
        if f.document_ids is not None:
            stmt = stmt.where(
                exists().where(
                    thread_documents.c.thread_id == threads.c.thread_id,
                    thread_documents.c.document_id.in_(list(f.document_ids)),
                )
                if f.document_ids
                else false()
            )
        if f.active_from is not None:
            stmt = stmt.where(last_activity >= f.active_from)
        if f.active_before is not None:
            stmt = stmt.where(last_activity < f.active_before)
        if f.title is not None:
            stmt = stmt.where(threads.c.title.icontains(f.title, autoescape=True))
        with self._engine.connect() as conn:
            rows = conn.execute(stmt).all()
        return [_thread(r) for r in rows]
```

- [ ] **Step 10: Run** the integration file and `uv run pytest tests/unit/tutoring -q` — all PASS. Then `uv run ruff check . && uv run ruff format --check . && uv run mypy`.

- [ ] **Step 11: Commit** — `Filter a learner's threads by last activity, documents, and title in SQL` (body: US-13 filters must run in owner-scoped SQL; `Thread.matches` is the fake's twin; title search escapes LIKE wildcards).

---

### Task 2: The service filters by subject, GMT+7 days, and title

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py` (add `documents_with_subjects`)
- Modify: `backend/src/smart_tutor/tutoring/application/conversation_service.py` (`__init__`, `list_threads`)
- Modify: `backend/src/smart_tutor/apps/api/services.py` (pass `time_zone=time_zone` to `ConversationService`)
- Modify: `backend/tests/fakes/api.py` (pass `time_zone=APP_TZ` to `ConversationService`)
- Test: `backend/tests/unit/knowledge/test_document_service.py`, `backend/tests/unit/tutoring/test_conversation_service.py`

**Interfaces:**
- Consumes: `ThreadFilter`, `ThreadRepository.list_owned(..., thread_filter)` from Task 1.
- Produces:
  ```python
  DocumentService.documents_with_subjects(self, user_id: UserId, subject_ids: Collection[SubjectId]) -> frozenset[DocumentId]
  ConversationService.__init__(..., *, history_turns=5, history_answer_chars=2000, time_zone: tzinfo = DEFAULT_TIME_ZONE)
  ConversationService.list_threads(
      self, user_id: UserId, *, subject_ids: Collection[SubjectId] = (), active_from: date | None = None,
      active_to: date | None = None, title: str | None = None,
  ) -> list[ThreadSummary]
  ```

- [ ] **Step 1: Failing knowledge test** (append to `backend/tests/unit/knowledge/test_document_service.py`; reuse that file's helpers for making ready documents with subjects — read its top first; the shape below uses `ingest_ready` from `fakes` as `test_conversation_service.py` does)

```python
def test_documents_with_subjects_are_the_learners_archived_included() -> None:
    library = InMemoryLibrary()
    s1, s2 = SubjectId("00000000-0000-4000-8000-000000000001"), SubjectId("00000000-0000-4000-8000-000000000002")
    live = ingest_ready(library, "ada", "Live.", subject_ids=[s1])
    archived = ingest_ready(library, "ada", "Archived.", subject_ids=[s1, s2])
    ingest_ready(library, "ada", "Other.", subject_ids=[s2])
    ingest_ready(library, "bob", "Theirs.", subject_ids=[s1])
    library.state.documents[archived].archived = True
    svc = DocumentService(library.unit_of_work, max_attempts=3)

    assert svc.documents_with_subjects(UserId("ada"), [s1]) == {live, archived}
    assert svc.documents_with_subjects(UserId("ada"), []) == frozenset()
```

- [ ] **Step 2: Implement** in `DocumentService` (after `documents_by_id`):

```python
    def documents_with_subjects(self, user_id: UserId, subject_ids: Collection[SubjectId]) -> frozenset[DocumentId]:
        """The learner's documents with any of these subjects, archived included and in any state; a deleted one is
        gone, so its subjects no longer count (PRD D11, Q63 L1)."""
        if not subject_ids:
            return frozenset()
        with self._uow() as tx:
            documents = tx.documents.list_readable_by(user_id, DocumentFilter(subject_ids=frozenset(subject_ids)))
        return frozenset(d.document_id for d in documents)
```

Run `uv run pytest tests/unit/knowledge/test_document_service.py -q` — PASS.

- [ ] **Step 3: Failing service tests** (append to `backend/tests/unit/tutoring/test_conversation_service.py`, near the other list tests; add imports `date`, `datetime`, `UTC`, `ZoneInfo` as needed; `service(...)` is that file's helper — extend it to accept `time_zone` if it doesn't forward kwargs)

```python
def test_filters_by_any_listed_documents_subject_and_a_deleted_documents_subjects_dont_count() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    d1 = ingest_ready(library, "ada", "Live paper.", subject_ids=[S1])
    d2 = ingest_ready(library, "ada", "Archived paper.", subject_ids=[S2])
    d3 = ingest_ready(library, "ada", "Deleted paper.", subject_ids=[S3])
    svc = service(library, threads, clock)
    live = svc.start_thread(UserId("ada"), "Live?")
    svc.record_turn(ThreadId(live.thread_id), UserId("ada"), answered(d1, d2))
    gone = svc.start_thread(UserId("ada"), "Gone?")
    svc.record_turn(ThreadId(gone.thread_id), UserId("ada"), answered(d3))
    library.state.documents[d2].archived = True
    del library.state.documents[d3]

    assert [s.thread_id for s in svc.list_threads(UserId("ada"), subject_ids=[S2])] == [live.thread_id]
    assert [s.thread_id for s in svc.list_threads(UserId("ada"), subject_ids=[S1, S3])] == [live.thread_id]
    assert svc.list_threads(UserId("ada"), subject_ids=[S3]) == []


def test_filters_by_last_activity_in_gmt7_calendar_days() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    clock = FixedClock(datetime(2026, 10, 1, 17, 30, tzinfo=UTC))  # 00:30 on 2 October in GMT+7
    ingest_ready(library, "ada", "Paper.")
    svc = service(library, threads, clock)
    thread = svc.start_thread(UserId("ada"), "Late?")

    def ids(**kw: date) -> list[str]:
        return [s.thread_id for s in svc.list_threads(UserId("ada"), **kw)]

    assert ids(active_from=date(2026, 10, 2), active_to=date(2026, 10, 2)) == [thread.thread_id]
    assert ids(active_to=date(2026, 10, 1)) == []
    assert ids(active_from=date(2026, 10, 3)) == []


def test_title_search_is_case_insensitive_ignores_answers_and_blank_means_all() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    d1 = ingest_ready(library, "ada", "Paper.")
    svc = service(library, threads, clock)
    rag = svc.start_thread(UserId("ada"), "What is RAG?")
    other = svc.start_thread(UserId("ada"), "Attention?")
    svc.record_turn(ThreadId(other.thread_id), UserId("ada"), AnsweredTurn("Attention?", "Unlike RAG, it...", (), document_ids=(d1,)))

    assert [s.thread_id for s in svc.list_threads(UserId("ada"), title="rag")] == [rag.thread_id]
    assert len(svc.list_threads(UserId("ada"), title="   ")) == 2


def test_filters_combine() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    d1 = ingest_ready(library, "ada", "Paper.", subject_ids=[S1])
    svc = service(library, threads, clock)
    both = svc.start_thread(UserId("ada"), "RAG and S1?")
    svc.record_turn(ThreadId(both.thread_id), UserId("ada"), answered(d1))
    svc.start_thread(UserId("ada"), "RAG only?")

    assert [s.thread_id for s in svc.list_threads(UserId("ada"), subject_ids=[S1], title="rag")] == [both.thread_id]
```

(Check `AnsweredTurn`'s real constructor and `answered(...)` helper in the test file and adapt the third test's `record_turn` line to them; the point is an answer text containing "RAG" on a thread whose title doesn't.)

- [ ] **Step 4: Run** — FAIL (unexpected keyword arguments).

- [ ] **Step 5: Implement** in `conversation_service.py`. Imports: `from datetime import date, datetime, time, timedelta, tzinfo`, `from collections.abc import Collection, Sequence`, `from smart_tutor.knowledge.application import DEFAULT_TIME_ZONE` (export it from `knowledge/application/__init__.py` if it isn't), `SubjectId`, `ThreadFilter`. Constructor: add keyword `time_zone: tzinfo = DEFAULT_TIME_ZONE` → `self._tz = time_zone`. Replace `list_threads`' signature and first line:

```python
    def list_threads(
        self,
        user_id: UserId,
        *,
        subject_ids: Collection[SubjectId] = (),
        active_from: date | None = None,
        active_to: date | None = None,
        title: str | None = None,
    ) -> list[ThreadSummary]:
        """The learner's active conversations, newest last activity first (US-13), narrowed by any subset of the
        filters: any of the subjects of its listed documents that still exist, archived included (D11, Q63 L1); last
        activity between two inclusive calendar days in the app time zone (D27); a case-insensitive part of the title,
        never of the answers (Q63 N3). A row's subjects are read now the same way; a deleted document adds none."""
        search = (title or "").strip()
        thread_filter = ThreadFilter(
            None if not subject_ids else self._documents.documents_with_subjects(user_id, subject_ids),
            None if active_from is None else datetime.combine(active_from, time(), tzinfo=self._tz),
            None if active_to is None else datetime.combine(active_to + timedelta(days=1), time(), tzinfo=self._tz),
            search or None,
        )
        threads = self._threads.list_owned(user_id, ThreadStatus.ACTIVE, thread_filter)
        # ... the rest of the existing body unchanged
```

- [ ] **Step 6: Wire the time zone** — `apps/api/services.py`: add `time_zone=time_zone,` to the `ConversationService(...)` call. `tests/fakes/api.py`: `ConversationService(threads, documents, clock, feedback=feedback, time_zone=APP_TZ)`.

- [ ] **Step 7: Run** `uv run pytest tests/unit -q` then `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports` — PASS.

- [ ] **Step 8: Commit** — `Narrow a learner's conversations by subject, GMT+7 days, and title` (body: subjects become the learner's own document ids through knowledge, so a deleted document's subjects stop counting; days are GMT+7 per D27; blank search narrows nothing).

---

### Task 3: `GET /threads` query parameters, isolation test, client, PRD

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py` (`list_threads` route, module docstring sentence about listing)
- Test: `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py`
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`
- Modify: `sdd/prd.md` (status line → v2.49, new "Changes from v2.48" row, US-13 bullet), `AGENTS.md` PRD version only if it names one that #188 bumped (it says v2.44 — leave unless the convention is to track; check `git log -p -1 -- AGENTS.md` of 8266d38 and follow it), `backend/src/smart_tutor/tutoring/README.md` (mention filters where it describes listing)

**Interfaces:**
- Consumes: `ConversationService.list_threads(user_id, *, subject_ids, active_from, active_to, title)` from Task 2.
- Produces: `GET /threads?subject_id=<uuid>&subject_id=…&active_from=YYYY-MM-DD&active_to=YYYY-MM-DD&q=<text>` (operation `list_threads`); the generated `listThreads` takes `query: { subject_id?: string[]; active_from?: string | null; active_to?: string | null; q?: string | null }`.

- [ ] **Step 1: Failing route tests** (append next to `test_lists_the_callers_threads_with_subject_names_newest_first`, reusing its `listing`, `sources`, `AGENT_ANSWER`, `AUTH`, `IR` helpers)

```python
def test_the_list_narrows_by_subject_date_and_title() -> None:
    answers: list[bytes] = []

    def answering(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=answers.pop(0), headers={"content-type": "text/event-stream"})

    client, _, clock, doc = listing(answering)
    answers += [sources(doc) + AGENT_ANSWER, AGENT_ANSWER]
    client.post("/threads", json={"question": "What is retrieval?"}, headers=AUTH)
    day = clock.current.astimezone(ZoneInfo("Asia/Ho_Chi_Minh")).date()
    clock.current += timedelta(days=3)
    client.post("/threads", json={"question": "Later question?"}, headers=AUTH)

    def titles(params: dict[str, str]) -> list[str]:
        response = client.get("/threads", params=params, headers=AUTH)
        assert response.status_code == 200
        return [t["title"] for t in response.json()]

    assert titles({"subject_id": IR}) == ["What is retrieval?"]
    assert titles({"active_from": day.isoformat(), "active_to": day.isoformat()}) == ["What is retrieval?"]
    assert titles({"q": "LATER"}) == ["Later question?"]
    assert titles({"q": "later", "subject_id": IR}) == []


def test_the_list_refuses_a_bad_filter() -> None:
    client, _, _, _ = listing()
    assert client.get("/threads", params={"active_from": "yesterday"}, headers=AUTH).status_code == 422
    assert client.get("/threads", params={"subject_id": "not-a-uuid"}, headers=AUTH).status_code == 422
    assert client.get("/threads", params={"q": "x" * 121}, headers=AUTH).status_code == 422
```

(Import `ZoneInfo` if absent. If `IR` is not a UUID string, adapt to the file's constant. The fake `api_services` uses `APP_TZ`; check it equals `Asia/Ho_Chi_Minh` in `tests/fakes/parameters.py` and use `APP_TZ` instead of a literal ZoneInfo if so.)

- [ ] **Step 2: Failing isolation test** (append to `backend/tests/isolation/test_threads.py`, reusing the setup of `test_each_learner_lists_only_their_own_threads`; factor that setup into a local helper only if it keeps both tests readable)

```python
def test_filtering_by_a_shared_subject_lists_only_the_callers_threads() -> None:
    """Two learners whose conversations used documents of the same shared subject each filter to only their own."""
    # same setup as test_each_learner_lists_only_their_own_threads: both learners ask once, each answer uses their
    # own document with subject SHARED; then:
    a_list = client.get("/threads", params={"subject_id": SHARED, "q": "attention"}, headers=A).json()
    b_list = client.get("/threads", params={"subject_id": SHARED}, headers=B).json()
    assert [t["thread_id"] for t in a_list] == [owned["learner-a"]]
    assert [t["thread_id"] for t in b_list] == [owned["learner-b"]]
```

(Write the full setup inline — copy the 20 lines from the existing test; the comment above stands for them in this plan only.)

- [ ] **Step 3: Run** `uv run pytest tests/unit/apps/api/test_thread_routes.py tests/isolation/test_threads.py -q` — FAIL.

- [ ] **Step 4: Route** — replace `list_threads` in `routes/threads.py` (imports `date`, `UUID`, `Query`, `SubjectId` as needed; `MAX_TITLE` from `smart_tutor.tutoring.domain.thread` is not importable from apps if import-linter forbids domain access — use `Query(max_length=120)` with a comment naming US-13's 120-character title):

```python
@router.get("/threads", operation_id="list_threads")
def list_threads(
    principal: CurrentPrincipal,
    conversations: Conversations,
    subjects: Subjects,
    subject_id: Annotated[list[UUID], Query(max_length=100)] = [],  # noqa: B006 - FastAPI copies the default
    active_from: date | None = None,
    active_to: date | None = None,
    q: Annotated[str | None, Query(max_length=120)] = None,  # a title is at most 120 characters (US-13)
) -> list[ThreadSummaryResponse]:
    """The learner's active conversations, newest last activity first (PRD US-13): title, subjects of the documents
    ...existing sentence...

    `subject_id` repeats; a conversation matches when any of its listed documents that still exist has any of them.
    `active_from` and `active_to` are inclusive calendar days of last activity in the app time zone (D27). `q` is a
    case-insensitive part of the title; answers are not searched (Q63). The filters combine; blank `q` is ignored.
    """
    summaries = conversations.list_threads(
        principal.user_id,
        subject_ids=[SubjectId(str(s)) for s in subject_id],
        active_from=active_from,
        active_to=active_to,
        title=q,
    )
    # ...rest unchanged
```

Keep the existing docstring's first sentence verbatim; check its current text before editing.

- [ ] **Step 5: Run** the two test files, then the full backend check: `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest` — PASS.

- [ ] **Step 6: Regenerate the client** — from repo root: `cd backend && uv run --env-file ../.env python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Confirm `web/src/api/generated/types.gen.ts` has `ListThreadsData` with the four query params.

- [ ] **Step 7: PRD** — status line `Draft v2.48` → `Draft v2.49`; insert above the v2.47 row:

```markdown
| **Changes from v2.48** | Filter conversations (#190, US-13, US-13b): `GET /threads` takes `subject_id` (repeats; a conversation matches when any of its listed documents that still exist has any of them, archived included; a deleted document's subjects no longer count, Q63 L1), `active_from` and `active_to` (inclusive calendar days of last activity in GMT+7, D27), and `q` (a case-insensitive part of the title; answers are not searched, Q63 N3), combined, in owner-scoped SQL. The Conversations page has Search titles, Subject (the learner's subjects), and Date filters with a result count and Clear filters; when nothing matches it shows "No conversations match these filters". The Archived tab and sort come in their own slices. |
```

US-13 bullet stays (it already says "filter by date range and subject"). Tutoring README: where it describes listing conversations, add "filtered by subject, last-activity days, and title".

- [ ] **Step 8: Commit** — `Filter GET /threads by subject, last-activity days, and title` (body: the API side of #190; isolation test with a shared subject; regenerated web client; PRD v2.49).

---

### Task 4: Move the Library's date-range popover into a shared component

**Files:**
- Create: `web/src/components/DateRangeFilter/DateRangeFilter.tsx`, `web/src/components/DateRangeFilter/DateRangeFilter.module.css` (git mv of `features/library/UploadedFilter.module.css`), `web/src/components/DateRangeFilter/DateRangeFilter.test.tsx`
- Delete: `web/src/features/library/UploadedFilter.tsx`
- Modify: `web/src/features/library/LibraryFilters.tsx`, `web/src/features/library/LibraryFilters.test.tsx` (the `describe("UploadedFilter")` block moves to the new test file; the import of `uploadedStyles` points to the new CSS module)

**Interfaces:**
- Produces:
  ```ts
  type DateRange = { from?: string; to?: string }; // YYYY-MM-DD, as the date inputs hold them; "" when cleared
  export function DateRangeFilter(props: { label: string; groupLabel: string; from?: string; to?: string; onChange: (range: DateRange) => void }): JSX.Element
  ```
  The button's visible text is `label`; its accessible name is `label` or `` `${label}: ${range}` `` when set; the popover group's accessible name is `groupLabel`; `onChange` reports only the changed key (`{ from }` or `{ to }`), exactly as `UploadedFilter` did.

- [ ] **Step 1:** `git mv web/src/features/library/UploadedFilter.tsx web/src/components/DateRangeFilter/DateRangeFilter.tsx` and the CSS module likewise. In the component: rename to `DateRangeFilter`, props `{ label, groupLabel, from, to, onChange }`, replace the literal "Uploaded" text/aria with `label`, "Upload dates" with `groupLabel`, and `onChange({ uploaded_from: v })` / `onChange({ uploaded_to: v })` with `onChange({ from: v })` / `onChange({ to: v })`. Update the header comment: "A date range in one popover, so the toolbar stays one row (DESIGN.md → Layout → Toolbar)."

- [ ] **Step 2:** `LibraryFilters.tsx`:

```tsx
<DateRangeFilter label="Uploaded" groupLabel="Upload dates" from={filters.uploaded_from} to={filters.uploaded_to} onChange={(r) => set({ ...("from" in r ? { uploaded_from: r.from } : {}), ...("to" in r ? { uploaded_to: r.to } : {}) })} />
```

- [ ] **Step 3:** Move the `describe("UploadedFilter", …)` tests into `DateRangeFilter.test.tsx`, rendering `<DateRangeFilter label="Uploaded" groupLabel="Upload dates" … />` directly with a `vi.fn()` `onChange`; add one test that a different label shows: `render(<DateRangeFilter label="Date" groupLabel="Last activity" from="2026-10-01" onChange={vi.fn()} />)` → button named `"Date: from 2026-10-01"`; opening it shows group `"Last activity"`; typing a To date calls `onChange({ to: "2026-10-05" })`. Keep LibraryFilters' own Uploaded tests passing unchanged except imports.

- [ ] **Step 4: Run** `cd web && npx vitest run src/components/DateRangeFilter src/features/library` — PASS; `npm run build` — PASS.

- [ ] **Step 5: Commit** — `Share the Library's date-range popover as DateRangeFilter` (body: Conversations filters by last-activity dates with the same control, #190).

---

### Task 5: Filter bar, filtered list, and no-results state on the Conversations page

**Files:**
- Modify: `web/src/api/conversations.ts`, `web/src/api/conversations.test.ts`
- Create: `web/src/features/conversations/ConversationFilters.tsx`, `ConversationFilters.module.css` (only if a style is needed; prefer none), `ConversationFilters.test.tsx`
- Create: `web/src/features/conversations/useFilteredConversations.ts`, `useFilteredConversations.test.tsx`
- Modify: `web/src/features/conversations/ConversationsPage.tsx`, `ConversationsPage.test.tsx`

**Interfaces:**
- Consumes: generated `listThreads` query from Task 3; `DateRangeFilter` from Task 4; `FilterBar`, `FilterField` (`web/src/components/FilterBar/FilterBar.tsx`); `loadMySubjects` (`web/src/api/subjects.ts`); `EmptyState`, `Button`; `useConversations` (shell list).
- Produces:
  ```ts
  export type ConversationFilters = { subject_id?: string; active_from?: string; active_to?: string; q?: string };
  export async function listConversations(filters?: ConversationFilters, apiClient?: Client): Promise<ThreadSummaryResponse[]>;
  export function hasConversationFilters(filters: ConversationFilters): boolean; // q counts only when non-blank
  export function useFilteredConversations(load: (f: ConversationFilters) => Promise<ThreadSummaryResponse[]>, filters: ConversationFilters, reloadKey: unknown): { list: ThreadSummaryResponse[] | null; failed: boolean };
  ConversationsPage(props: { loadConversations?: typeof listConversations; loadSubjects?: () => Promise<SubjectResponse[]> })
  ```

- [ ] **Step 1: API wrapper test** (`conversations.test.ts`, following its existing pattern of a fake `Client`/fetch): `listConversations({ subject_id: "s1", active_from: "2026-10-01", active_to: "2026-10-05", q: " rag " })` requests `/threads?subject_id=s1&active_from=2026-10-01&active_to=2026-10-05&q=rag`; `listConversations({ q: "  " })` requests `/threads` with no query string.

- [ ] **Step 2: Implement** in `conversations.ts`:

```ts
// What the Conversations list narrows by (PRD US-13); every field is optional and they combine. Dates are YYYY-MM-DD
// calendar days of last activity; `q` searches titles only.
export type ConversationFilters = { subject_id?: string; active_from?: string; active_to?: string; q?: string };

export const hasConversationFilters = (f: ConversationFilters) => Boolean(f.subject_id || f.active_from || f.active_to || f.q?.trim());

// The learner's active conversations, newest last activity first (owner only), narrowed by the filters.
export async function listConversations(filters: ConversationFilters = {}, apiClient: Client = client): Promise<ThreadSummaryResponse[]> {
  const q = filters.q?.trim();
  const query = {
    ...(filters.subject_id ? { subject_id: [filters.subject_id] } : {}),
    ...(filters.active_from ? { active_from: filters.active_from } : {}),
    ...(filters.active_to ? { active_to: filters.active_to } : {}),
    ...(q ? { q } : {}),
  };
  const { data, error, response } = await listThreads({ client: apiClient, query, throwOnError: false });
  // ...unchanged error handling
}
```

The shell calls `listConversations()` with no arguments — check `AppShell.tsx` passes it in a way that doesn't hand a non-filter first argument (e.g. `load={listConversations}` invoked as `load()` is fine; `.then(listConversations)` would not be).

- [ ] **Step 3: `useFilteredConversations`** — loads only while `hasConversationFilters(filters)`; otherwise returns `{ list: null, failed: false }`. Reloads when the filters (by `JSON.stringify`) or `reloadKey` change; the `q` part is debounced 250 ms (other parts load at once); only the latest call's result is applied; nothing is set after unmount. Mirror the latest-wins/alive pattern of `useDocuments` (`web/src/features/library/useDocuments.ts`).

Tests (`useFilteredConversations.test.tsx`, with `renderHook` and fake timers for the debounce):
  - no filters → never calls `load`, `list` null;
  - `subject_id` set → calls `load` once with the filters, exposes its result;
  - a slow first response resolving after a second, faster one never replaces the second's result;
  - `q` changes "r" → "ra" → "rag" within 250 ms → `load` called once with `q: "rag"`;
  - a rejected load sets `failed: true`.

- [ ] **Step 4: `ConversationFilters`** component:

```tsx
type Props = { filters: ConversationFilters; onChange: (f: ConversationFilters) => void; subjects: SubjectResponse[]; count: number | null; onClear: () => void };

// Search titles, a single-select Subject, and a last-activity date popover (PRD US-13), in the Library's filter bar.
export function ConversationFilters({ filters, onChange, subjects, count, onClear }: Props) {
  const set = (patch: Partial<ConversationFilters>) => {
    const next: ConversationFilters = { ...filters, ...patch };
    for (const key of Object.keys(next) as (keyof ConversationFilters)[]) if (!next[key]) delete next[key]; // absent means unfiltered
    onChange(next);
  };
  return (
    <FilterBar label="Filter conversations" noun="conversation" count={count} active={hasConversationFilters(filters)} onClear={onClear}>
      <FilterField id="filter-title" label="Search titles">
        <input id="filter-title" type="search" placeholder="Search titles" value={filters.q ?? ""} onChange={(e) => set({ q: e.target.value })} />
      </FilterField>
      <FilterField id="filter-subject" label="Subject">
        <select id="filter-subject" value={filters.subject_id ?? ""} onChange={(e) => set({ subject_id: e.target.value })}>
          <option value="">All subjects</option>
          {subjects.map((s) => <option key={s.subject_id} value={s.subject_id}>{s.name}</option>)}
        </select>
      </FilterField>
      <DateRangeFilter label="Date" groupLabel="Last activity" from={filters.active_from} to={filters.active_to}
        onChange={(r) => set({ ...("from" in r ? { active_from: r.from } : {}), ...("to" in r ? { active_to: r.to } : {}) })} />
    </FilterBar>
  );
}
```

Note: `set` must keep a typed-but-blank `q` like `" "` in state so the input shows what was typed — so delete only `undefined`/`""` values, not whitespace (the API wrapper trims). Check `FilterBar.module.css` styles `input[type=search]` like the selects (DESIGN.md → Toolbar); if not, add the minimal rule to `FilterBar.module.css` using the same tokens as its `select` rule, so the field matches the mockup's 200px "Search titles" box.

Tests (`ConversationFilters.test.tsx`): typing in "Search titles" calls `onChange` with `q`; choosing a subject by name calls `onChange({ subject_id })`; choosing "All subjects" drops it; the Date popover sets `active_from`; Clear filters shows only when a filter is set and calls `onClear`; the count reads "1 conversation".

- [ ] **Step 5: Page** — `ConversationsPage.tsx`:

```tsx
const defaultLoadSubjects = () => loadMySubjects();

export function ConversationsPage({ loadConversations = listConversations, loadSubjects = defaultLoadSubjects }: Props = {}) {
  const { list, failed } = useConversations();
  const [filters, setFilters] = useState<ConversationFilters>({});
  const [subjects, setSubjects] = useState<SubjectResponse[]>([]);
  useEffect(() => { let alive = true; loadSubjects().then((s) => alive && setSubjects(s), () => {}); return () => { alive = false; }; }, [loadSubjects]);
  const filtering = hasConversationFilters(filters);
  const filtered = useFilteredConversations(loadConversations, filters, list); // a shell reload (rename, answer, navigation) reloads it too
  const rows = filtering ? filtered.list : list;
  const clear = () => setFilters({});
  // header count stays the shell's total; the bar counts `rows`
  ...
  {list && list.length > 0 && <ConversationFilters filters={filters} onChange={setFilters} subjects={subjects} count={rows ? rows.length : null} onClear={clear} />}
  {filtering && filtered.failed && <p className={styles.error}>Can't load your conversations. Reload the page to try again.</p>}
  {rows && rows.length === 0 && filtering && (
    <EmptyState icon={Filter} title="No conversations match these filters" actions={<Button onClick={clear}>Clear filters</Button>}>
      <p>Try another subject, a wider date range or another search.</p>
    </EmptyState>
  )}
  {rows && rows.length > 0 && <ConversationTable conversations={rows} />}
```

Keep the existing "No conversations yet" branch for `list?.length === 0` (no filter bar then). `loadSubjects` default must be a module-level constant so the effect doesn't loop.

Page tests (`ConversationsPage.test.tsx`; pass `loadConversations` / `loadSubjects` fakes; existing tests keep passing with the defaults replaced by fakes that resolve `[]`):
  - choosing a subject shows only the filtered rows the fake returns, the bar counts "1 conversation", and the header still says "2 conversations";
  - a filter that returns `[]` shows "No conversations match these filters" and its text; clicking Clear filters shows the shell's full list again and no filter is set;
  - typing "  " in Search titles shows the full list and no Clear filters (blank search is not a filter);
  - a learner with no conversations sees "No conversations yet" and no filter bar.

- [ ] **Step 6: Run** `cd web && npx vitest run src/features/conversations src/api src/components && npm run build` — PASS.

- [ ] **Step 7: Look at it against the design** — `make design-shots ROUND=v0.10 STATES="conversations-filtered,conversations-no-results" THEME=both` (PNGs in `.design-shots/v0.10/`). Run the app (`docker compose --profile app up -d --build web api` or `make api` + `make web`), sign in as `learner@example.com`/`learner`, filter the Conversations page in light and dark themes, and screenshot both states with Playwright on channel `chrome` (memory: verify in installed Chrome). Fix spacing/alignment so the bar reads Search titles → Subject → Date → count/Clear filters on one row like the mockup. Record differences that come from out-of-slice parts (Archived tab, sort, note badge, previews) in the PR description.

- [ ] **Step 8: Commit** — `Filter the Conversations page by title, subject, and date` (body: US-13; the page loads filtered results itself so the side nav keeps the most recent conversations; no-results copy from design v0.10).

---

## Finish

- Full checks from `AGENTS.md` (backend, web; `infra/` and `deploy/` unchanged).
- Push the branch, open a PR into `main` titled `Filter conversations by date, subject, and title (#190)` that closes #190, lists the acceptance criteria with how each is covered, notes the design differences (no Archived tab or sort yet; copy "No conversations match these filters" from the v0.10 prototype rather than the state description "No results for these filters"), and ends with the Claude Code line.

# Archive and restore a document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A learner archives a document from its row's More menu, finds it under a new Archived tab, and restores it from there; archived documents leave search and My subjects until restored (#108).

**Architecture:** A prefactor first makes `can_read` lookups (`get_readable`, `list_readable_by`, the hash lookup) mean only "the caller may read this"; callers that need active documents filter explicitly. Then `Document.archive(at)` / `restore()` in the domain, an `ArchiveService` in `knowledge.application`, two API routes and an `archived` list parameter, and in the web a `Tabs` component, a `RowMenu` (More) component, an "Archived" state badge, and the Library's Archived tab.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy Core / pytest (backend); React + TypeScript + Vite / Vitest + Testing Library (web).

**Spec:** GitHub issue #108; PRD `sdd/prd.md` §8 US-10, D10, §9.5 (archive/restore row), Q50 (no subject change while archived); design round `design-v0.10`, states `library-archived`, `library-archived-after-archive` (PNGs: `make design-shots ROUND=v0.10 STATES="library-archived,library-archived-after-archive,library-more-menu" THEME=both`).

## Global Constraints

- `documents.archived` and `documents.archived_at` **already exist** (migration `0002_library.py`); no new migration.
- Archiving only sets `archived` and `archived_at`; content, chunks, subjects, and state are untouched. Restore clears both. Repeating either is harmless (a second archive keeps the first `archived_at`).
- Archive is allowed in any document state (PRD §9.5: "a separate flag on any state").
- Every read goes through `can_read` (Release 1: owner only). Another learner gets the same `404 "Document not found"` as for a missing document.
- An archived document's subjects can't be changed until restored (PRD US-10, Q50): suggestions and `PUT .../subjects` answer `409`.
- Archived documents are excluded from search, from My subjects, from `has_ready_documents`, and from the browser duplicate check (`find_in_library`).
- UI copy, verbatim from the mockup: tab labels "Active" and "Archived"; notice "Archived documents aren't used for answers, but citations to them in past conversations still work. Restore a document to change its subjects."; buttons "Archive", "Restore"; badge "Archived".
- Web: rebuild with `web/src/components/` and tokens; never paste prototype HTML/CSS. Icons `lucide-react`, `strokeWidth={1.5}`, `aria-hidden`. Check both themes.
- Checks before each commit (backend): `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Web: `cd web && npm run build && npx vitest run`.
- Commit subjects in the imperative mood, body says why, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Archiving a document that is still processing, then the worker finishing it: it must stay archived. `save` now writes `archived`/`archived_at`, so every loader must read them back — Task 2 adds a unit test that archives a processing document, runs the worker's `await_subjects` path (load with `list_processing_for_content_for_update`, transition, `save`), and checks it is still archived with the same `archived_at`, plus the SQL round-trip test.
- Restoring a document whose subjects are shared with another active document: My subjects shows the subject throughout (Task 2 unit test).
- Archive/restore of another learner's document id → 404, and their list (both tabs) stays unchanged (Task 3 isolation test).
- Choose subjects on an archived `awaiting_subjects` document → 409, not a silent save (Task 2 unit test).
- An archived duplicate reported by the upload tray offers "Restore", which restores and refreshes the list (Task 5 web test).

---

### Task 1: Prefactor — `can_read` lookups stop filtering archived

Behavior is unchanged by this task alone.

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/domain/document.py` (`DocumentFilter`, `Document.matches`)
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py` (docstrings; `find_readable_by_sha256` → `get_readable_by_sha256` returning `Document | None`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py` (`list_readable_by`, `get_readable`, hash lookup)
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py` (`list_documents` gains `archived`, explicit filters)
- Modify: `backend/src/smart_tutor/knowledge/application/subject_choice.py` (`_choosable` rejects archived as not found, for now)
- Modify: `backend/tests/fakes/knowledge.py`
- Test: `backend/tests/unit/knowledge/test_domain.py`, `backend/tests/unit/knowledge/test_document_service.py`, `backend/tests/integration/knowledge/test_sql_library.py`

**Interfaces:**
- Produces: `DocumentFilter.archived: bool | None = None` (None = both); `Document.matches` honors it; `DocumentRepository.get_readable_by_sha256(user_id, sha256) -> Document | None`; `DocumentService.list_documents(..., archived: bool = False)`.

- [ ] **Step 1: Failing tests.** In `test_domain.py`:

```python
def test_the_filter_selects_active_archived_or_both() -> None:
    doc = _document()  # use the module's existing helper that builds a Document; add one if missing
    doc.archived = True
    assert doc.matches(DocumentFilter(archived=True))
    assert not doc.matches(DocumentFilter(archived=False))
    assert doc.matches(DocumentFilter())  # None: both
```

In `test_document_service.py`:

```python
def test_the_list_holds_active_documents_by_default_and_archived_ones_on_request() -> None:
    library = InMemoryLibrary()
    active = ingest_ready(library, "ada", "active")
    archived = ingest_ready(library, "ada", "archived")
    library.state.documents[archived].archived = True
    docs = DocumentService(library.unit_of_work, max_attempts=3)

    assert [d.document_id for d in docs.list_documents(UserId("ada"))] == [active]
    assert [d.document_id for d in docs.list_documents(UserId("ada"), archived=True)] == [archived]


def test_archived_documents_leave_my_subjects_ready_check_and_duplicate_check() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "only", [ART])
    library.state.documents[doc].archived = True
    docs = DocumentService(library.unit_of_work, max_attempts=3)
    sha = hashlib.sha256(b"only").hexdigest()

    assert docs.learner_subjects(UserId("ada")) == frozenset()
    assert docs.has_ready_documents(UserId("ada")) is False
    assert docs.find_in_library(UserId("ada"), sha) is None
```

In `test_sql_library.py`, rename `test_get_readable_is_owner_only_and_skips_archived` → `test_get_readable_is_owner_only_and_includes_archived` and change its last assertion to `found_archived = tx.documents.get_readable(UserId(owner), doc.document_id); assert found_archived is not None and found_archived.archived`. Add next to the existing filter tests (they use a helper around line 612 that lists titles with a `DocumentFilter`) a test that one active and one archived document (archive via `UPDATE documents SET archived = true`) come back for `DocumentFilter(archived=False)` / `(archived=True)` / `DocumentFilter()` as `{active}` / `{archived}` / both. Update the hash-lookup test (around line 552) to call `get_readable_by_sha256` and compare `.document_id`; an archived document is still returned (with `archived=True`).

- [ ] **Step 2: Run them, expect failures.** `cd backend && uv run pytest tests/unit/knowledge -q` and `uv run pytest -m integration tests/integration/knowledge/test_sql_library.py -q` (Compose Postgres on :10400 must be up; use `uv run --env-file ../.env`).

- [ ] **Step 3: Implement.**

`document.py`:

```python
@dataclass(frozen=True)
class DocumentFilter:
    ...
    archived: bool | None = None  # True: only archived; False: only active; None: both
```

and in `matches` add `and (f.archived is None or self.archived is f.archived)`.

`sql_library.py`: drop `documents.c.archived.is_(False)` from `list_readable_by` and `get_readable`; in `list_readable_by` add `if f.archived is not None: stmt = stmt.where(documents.c.archived.is_(f.archived))`. Replace `find_readable_by_sha256` with:

```python
    def get_readable_by_sha256(self, user_id: UserId, sha256: str) -> Document | None:
        row = self._conn.execute(
            select(documents)
            .select_from(documents.join(contents, documents.c.content_id == contents.c.content_id))
            .where(readable_by(user_id), contents.c.sha256 == sha256)
            .limit(1)  # contents are unique per (owner_id, sha256) and documents per (owner_id, content_id)
        ).first()
        return self._load([row])[0] if row else None
```

Port docstrings: `list_readable_by` "`can_read` in storage: the caller's documents matching the filter (archived ones included unless the filter says otherwise), newest first."; `get_readable` "`can_read` in storage: the caller's document, archived or not, with its content title; locked if `for_update`."; `get_readable_by_sha256` "`can_read` in storage: the caller's document whose content has this hash, archived or not (at most one: contents are per learner)."

`document_service.py`: `list_documents(..., archived: bool = False)` passes `archived` into `DocumentFilter`; `learner_subjects` and `has_ready_documents` call `list_readable_by(user_id, DocumentFilter(archived=False))`; `find_in_library`:

```python
        with self._uow() as tx:
            found = tx.documents.get_readable_by_sha256(user_id, sha256)
        return None if found is None or found.archived else found.document_id
```

`subject_choice._choosable`: after the `None` check, `if document is None or document.archived: raise DocumentNotFoundError(...)` (keeps today's 404; Task 2 turns it into 409).

Fakes (`tests/fakes/knowledge.py`): `list_readable_by` drops `not d.archived` (filter via `d.matches`); rename the hash method to `get_readable_by_sha256` returning a deep copy of the `Document`; `subject_ids_readable_by` adds `and not d.archived` (matching SQL).

- [ ] **Step 4: Run the full backend checks** (Global Constraints). All pass.
- [ ] **Step 5: Commit** "Let can_read lookups return archived documents" (body: restore needs to find what it restores; active-only callers now filter explicitly).

---

### Task 2: Domain archive/restore and `ArchiveService`

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/domain/document.py`
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py` (`_document`, `_Documents.save`)
- Create: `backend/src/smart_tutor/knowledge/application/archive_service.py`
- Modify: `backend/src/smart_tutor/knowledge/application/__init__.py` (export `ArchiveService`)
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py` (`DocumentView.archived`)
- Modify: `backend/src/smart_tutor/knowledge/application/subject_choice.py` (archived → `DocumentStateError`)
- Test: `backend/tests/unit/knowledge/test_domain.py`, `backend/tests/unit/knowledge/test_archive_service.py` (new), `backend/tests/unit/knowledge/test_subject_choice.py`, `backend/tests/integration/knowledge/test_sql_library.py`

**Interfaces:**
- Consumes: Task 1's `DocumentFilter.archived`, `get_readable` returning archived documents.
- Produces: `Document.archived_at: datetime | None = None`; `Document.archive(at: datetime) -> None`; `Document.restore() -> None`; `DocumentView.archived: bool` (last field); `ArchiveService(uow: Callable[[], LibraryUnitOfWork], clock: Clock, max_attempts: int)` with `archive(user_id, document_id) -> DocumentView` and `restore(user_id, document_id) -> DocumentView`, both raising `DocumentNotFoundError` for unknown/unreadable ids.

- [ ] **Step 1: Failing tests.**

`test_domain.py`:

```python
def test_archive_sets_the_flag_once_and_restore_clears_it() -> None:
    doc = _document()
    first, later = datetime(2026, 10, 9, tzinfo=UTC), datetime(2026, 10, 10, tzinfo=UTC)
    doc.archive(first)
    doc.archive(later)  # harmless: keeps the first time
    assert (doc.archived, doc.archived_at) == (True, first)
    doc.restore()
    doc.restore()
    assert (doc.archived, doc.archived_at) == (False, None)


def test_subjects_of_an_archived_document_cant_change() -> None:
    doc = _document()  # awaiting_subjects or ready
    doc.archive(datetime(2026, 10, 9, tzinfo=UTC))
    with pytest.raises(DocumentStateError):
        doc.choose_subjects([SubjectId("s1")])
```

`test_archive_service.py` (new), using `InMemoryLibrary`, `ingest_ready`, `FixedClock`, `SearchService` the way `test_search_service.py` builds it (read that file for the constructor and `fake_embeddings`):

```python
def test_archive_hides_chunks_and_subjects_until_restore() -> None:
    library, clock = InMemoryLibrary(), FixedClock()
    doc = ingest_ready(library, "ada", "attention mechanisms", [ART])
    archive = ArchiveService(library.unit_of_work, clock, max_attempts=3)
    docs = DocumentService(library.unit_of_work, max_attempts=3)
    search = ...  # SearchService over library.unit_of_work, as in test_search_service.py

    view = archive.archive(UserId("ada"), doc)
    assert view.archived is True
    assert library.state.documents[doc].archived_at == clock.current
    assert search.search(UserId("ada"), "attention mechanisms") == []
    assert docs.learner_subjects(UserId("ada")) == frozenset()

    assert archive.restore(UserId("ada"), doc).archived is False
    assert [h.document_id for h in search.search(UserId("ada"), "attention mechanisms")] == [doc]
    assert docs.learner_subjects(UserId("ada")) == frozenset({ART})


def test_a_subject_stays_mine_while_another_active_document_has_it() -> None:
    library = InMemoryLibrary()
    archived = ingest_ready(library, "ada", "one", [ART])
    ingest_ready(library, "ada", "two", [ART])
    ArchiveService(library.unit_of_work, FixedClock(), max_attempts=3).archive(UserId("ada"), archived)
    assert DocumentService(library.unit_of_work, max_attempts=3).learner_subjects(UserId("ada")) == frozenset({ART})


def test_archiving_keeps_content_chunks_subjects_and_state() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "kept", [ART])
    before = copy.deepcopy(library.state)
    ArchiveService(library.unit_of_work, FixedClock(), max_attempts=3).archive(UserId("ada"), doc)
    after = library.state.documents[doc]
    assert (after.state, after.subject_ids, after.content_id) == (
        before.documents[doc].state, before.documents[doc].subject_ids, before.documents[doc].content_id
    )
    assert library.state.contents == before.contents and library.state.chunks == before.chunks


def test_another_learner_cant_archive_or_restore() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "mine")
    archive = ArchiveService(library.unit_of_work, FixedClock(), max_attempts=3)
    with pytest.raises(DocumentNotFoundError):
        archive.archive(UserId("bob"), doc)
    with pytest.raises(DocumentNotFoundError):
        archive.restore(UserId("bob"), doc)
    with pytest.raises(DocumentNotFoundError):
        archive.archive(UserId("ada"), DocumentId("missing"))
    assert library.state.documents[doc].archived is False
```

`test_subject_choice.py`: an archived `awaiting_subjects` document → `suggestions` and `choose` raise `DocumentStateError` (and the document keeps no subjects).

`test_sql_library.py`: archive a document entity, `tx.documents.save(doc)`, commit; reload with `get_readable` → `archived is True` and `archived_at` equals the time given; `restore()`, save, reload → `(False, None)`.

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.**

`document.py` — field `archived_at: datetime | None = None` after `archived`, and:

```python
    def archive(self, at: datetime) -> None:
        """Hide from search and My subjects; content, chunks, subjects, and state stay (PRD §9.5). Idempotent."""
        if not self.archived:
            self.archived, self.archived_at = True, at

    def restore(self) -> None:
        self.archived, self.archived_at = False, None
```

At the top of `choose_subjects`: `if self.archived: raise DocumentStateError("Restore this document to change its subjects")`.

`sql_library.py`: `_document(...)` reads `archived_at=row.archived_at`; `_Documents.save` `.values(...)` adds `archived=document.archived, archived_at=document.archived_at`.

`subject_choice._choosable`: archived → `raise DocumentStateError("Restore this document to change its subjects")` (replace Task 1's not-found).

`document_service.py`: `DocumentView` gains `archived: bool` as the last field; `document_view` passes `d.archived`.

`archive_service.py`:

```python
"""Archive and restore a document (PRD §8 US-10, §9.5). Reads go through `can_read`."""

from collections.abc import Callable

from smart_tutor.knowledge.application.document_service import DocumentView, document_view
from smart_tutor.knowledge.domain.document import Document
from smart_tutor.knowledge.domain.errors import DocumentNotFoundError
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import DocumentId, UserId
from smart_tutor.shared.ports.clock import Clock


class ArchiveService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], clock: Clock, max_attempts: int) -> None:
        self._uow, self._clock, self._max_attempts = uow, clock, max_attempts

    def archive(self, user_id: UserId, document_id: DocumentId) -> DocumentView:
        return self._change(user_id, document_id, lambda d: d.archive(self._clock.now()))

    def restore(self, user_id: UserId, document_id: DocumentId) -> DocumentView:
        return self._change(user_id, document_id, Document.restore)

    def _change(self, user_id: UserId, document_id: DocumentId, change: Callable[[Document], None]) -> DocumentView:
        with self._uow() as tx:
            document = tx.documents.get_readable(user_id, document_id, for_update=True)
            if document is None:
                raise DocumentNotFoundError("This document isn't in your library")
            change(document)
            tx.documents.save(document)
            tx.commit()
        return document_view(document, self._max_attempts)
```

Note: `get_readable` doesn't fill authors/year; the returned view has empty authors — acceptable since the web refreshes the list after archive/restore. Check `shared.ports.clock` is importable from `knowledge.application` (lint-imports: `shared` is open to all; `UploadService` already takes a `Clock`, copy its import).

- [ ] **Step 4: Full backend checks pass.**
- [ ] **Step 5: Commit** "Archive and restore a document in the domain and ArchiveService".

---

### Task 3: API routes, list parameter, isolation tests, API client

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/services.py` (`ApiServices.archive`, built with `ArchiveService(library, SystemClock(), max_attempts)`)
- Modify: `backend/src/smart_tutor/apps/api/deps.py` (`Archive = Annotated[ArchiveService, Depends(_archive)]`, add to `__all__`)
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py`
- Modify: `backend/tests/fakes/api.py` (`"archive": ArchiveService(library.unit_of_work, clock, max_attempts=3)`)
- Test: `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/isolation/test_documents.py`; the OpenAPI snapshot (`test_openapi_snapshot.py`, regenerate per its instructions)
- Regenerate: `web/src/api/` via `make api-client` (or its one-line command from the `Makefile`: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`)

**Interfaces:**
- Consumes: `ArchiveService`, `DocumentView.archived`, `DocumentService.list_documents(archived=...)`.
- Produces (HTTP): `POST /documents/{document_id}/archive` (operation `archive_document`) and `POST /documents/{document_id}/restore` (operation `restore_document`), both `200` with `DocumentResponse`, `404 "Document not found"`; `GET /documents?archived=true|false` (default false); `DocumentResponse.archived: bool`. Generated web SDK functions `archiveDocument`, `restoreDocument`.

- [ ] **Step 1: Failing tests.** In `test_knowledge_routes.py` (follow its existing client setup): archive → 200 with `archived: true`; the default list no longer holds it and `?archived=true` does; archive twice → 200 both times; restore → back in the default list; unknown id → 404; `GET /me/subjects` loses the subject while archived; choose subjects on an archived document → 409. In `tests/isolation/test_documents.py`:

```python
def test_b_cannot_archive_restore_or_see_as_archived_document() -> None:
    client, objects, ingestion = setup()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])
    doc = stored["document_id"]

    assert client.post(f"/documents/{doc}/archive", headers=B).status_code == 404
    assert [d["archived"] for d in client.get("/documents", headers=A).json()] == [False]
    assert client.post(f"/documents/{doc}/archive", headers=A).status_code == 200
    assert client.get("/documents", headers=B, params={"archived": "true"}).json() == []
    assert client.post(f"/documents/{doc}/restore", headers=B).status_code == 404
    assert [d["document_id"] for d in client.get("/documents", headers=A, params={"archived": "true"}).json()] == [doc]
```

- [ ] **Step 2: Run, expect failures.**
- [ ] **Step 3: Implement.** `DocumentResponse` gains `archived: bool`; `_document_response` sets it. `list_documents` gains `archived: bool = False` passed through, and its docstring says "active documents by default; `archived=true` lists the archived ones". Routes:

```python
@router.post("/documents/{document_id}/archive", operation_id="archive_document")
def archive_document(document_id: UUID, principal: CurrentPrincipal, archive: Archive, subjects: Subjects) -> DocumentResponse:
    """Archive the caller's document: it leaves search and My subjects; content and chunks stay (PRD §8 US-10).

    Archiving an archived document changes nothing.
    """
    try:
        view = archive.archive(principal.user_id, DocumentId(str(document_id)))
    except DocumentNotFoundError:
        raise HTTPException(404, "Document not found") from None
    return _document_response(view, subjects.names_for(principal.user_id, set(view.subject_ids)))
```

and the same for `restore_document` ("Bring an archived document back into search and My subjects; restoring an active one changes nothing."). Update the module docstring to mention archive and restore. Then regenerate the OpenAPI snapshot and the web client.

- [ ] **Step 4: Full backend checks pass; `cd web && npm run build` passes** (TypeScript may now require `archived` in web test fixtures of `DocumentResponse`; add `archived: false` to fixture builders in `web/src/features/library/*.test.tsx` and anywhere else `tsc` reports).
- [ ] **Step 5: Commit** "Add archive and restore routes and the archived list".

---

### Task 4: Web components — `Tabs`, `RowMenu`, archived `StateBadge`

**Files:**
- Create: `web/src/components/Tabs/Tabs.tsx`, `Tabs.module.css`, `Tabs.test.tsx`
- Create: `web/src/components/RowMenu/RowMenu.tsx`, `RowMenu.module.css`, `RowMenu.test.tsx`
- Modify: `web/src/components/StateBadge/StateBadge.tsx`, `StateBadge.module.css`, `StateBadge.test.tsx`
- Modify: `DESIGN.md` components table: `Tabs` and `RowMenu` built (Library)

**Interfaces:**
- Produces:
  - `Tabs<T extends string>({ label, tabs, value, onChange }: { label: string; tabs: { value: T; label: string; count?: number }[]; value: T; onChange: (value: T) => void })` — `role="tablist"` with `aria-label`, buttons `role="tab"`, `aria-selected`, roving `tabIndex` (selected 0, others -1), ArrowLeft/ArrowRight/Home/End move focus and select. Count shown as a pill. No tab panels (the page's list is the panel; the component is a selector).
  - `RowMenu({ label, items }: { label: string; items: { label: string; icon: LucideIcon; onSelect: () => void; danger?: boolean }[] })` — a 24px+ `IconButton`-style "More" button (`MoreHorizontal` icon, `aria-label={label}`, `aria-haspopup="menu"`, `aria-expanded`) opening `role="menu"` with `role="menuitem"` buttons; first item focused on open; ArrowUp/Down move; Escape closes and returns focus to the button; selecting an item closes then calls `onSelect`; blur outside closes (copy `UserMenu`'s pattern).
  - `StateBadge` accepts `"archived"`: label "Archived", icon `Archive`, look `--surface-2` / `--text-2` with `1px dashed var(--border-strong)` (DESIGN.md → Document states).

- [ ] **Step 1: Failing tests** for each behavior listed above (render, roles, keyboard, focus return, onSelect called once, Archived label).
- [ ] **Step 2: Run** `cd web && npx vitest run src/components` — fail.
- [ ] **Step 3: Implement** with tokens; compact sizes from the prototype (`v03.css`): tab `min-height: 36px; padding: 0 10px; font-size: var(--fs-13); font-weight: 600; color: var(--text-2)`, selected `color: var(--text)` with a 2px `var(--accent)` underline inset 6px; count pill `min-width: 18px; padding: 0 5px; font-size: var(--fs-12); line-height: 18px; background: var(--surface-2); border-radius: var(--r-pill)`. Menu `min-width: 184px; padding: var(--sp-1); background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); box-shadow: var(--shadow-lg); position: absolute; right: 0; top: calc(100% + 4px); z-index: 30`; items `min-height: 32px; gap: var(--sp-2); padding: 0 var(--sp-2); font-size: var(--fs-13)`, hover `var(--surface-2)`, danger `var(--danger)`. Use only tokens that exist in `web/src/styles/tokens.css` (grep first).
- [ ] **Step 4: Tests and `npm run build` pass.**
- [ ] **Step 5: Commit** "Add Tabs, RowMenu, and the Archived state badge".

---

### Task 5: Library — Archive in More, Archived tab, Restore

**Files:**
- Modify: `web/src/api/documents.ts` (`DocumentFilters.archived?: boolean` passed as query `archived: true` only when true; `archiveDocument(id)`, `restoreDocument(id)` returning `DocumentResponse`, throwing `SessionExpiredError` on 401 and `Error` otherwise)
- Modify: `web/src/features/library/DocumentTable.tsx`, `DocumentTable.module.css`, `DocumentTable.test.tsx`
- Modify: `web/src/features/library/LibraryPage.tsx`, `LibraryPage.module.css`, `LibraryPage.test.tsx`
- Modify: `web/src/features/library/LibraryFilters.tsx` (prop `showState?: boolean`, default true; the Archived tab hides State and the needs-subjects chip)
- Modify: `web/src/components/UploadTray/UploadTray.tsx`, `UploadTray.test.tsx` (Restore for an archived duplicate)

**Interfaces:**
- Consumes: `Tabs`, `RowMenu`, `StateBadge "archived"` (Task 4); generated `archiveDocument`/`restoreDocument` (Task 3).
- Produces: `LibraryPage` props `archive?: (id: string) => Promise<DocumentResponse>` and `restore?: (id: string) => Promise<DocumentResponse>` (defaults call the API); `DocumentTable` props `onArchive?: (doc) => void`, `onRestore?: (doc) => void`, `busy?: ReadonlySet<string>`; `UploadTray` prop `onRestore?: (item: TrayItem) => void`.

Behavior:
- Toolbar: `Tabs` (label "Library view") with "Active" and "Archived" and their counts, left of the filters. Counts are unfiltered totals: load both lists with no filters (`load({})`, `load({ archived: true })`) on mount, after archive/restore, after an upload starts or a duplicate is reported, and on tab change; the current tab's list keeps polling through `useDocuments` with `{ ...filters, archived: tab === "archived" || undefined }`. Switching tabs keeps the subject and date filters and drops `state`.
- Header count: "N active documents" from the active total (mockup), unchanged when 0.
- Archived tab: under the toolbar, a one-row notice (`Info` icon, `--surface-2`, 32px, `--fs-13`; DESIGN.md → Notices): "Archived documents aren't used for answers, but citations to them in past conversations still work. Restore a document to change its subjects." Rows show the "Archived" badge in State, the title in `--text-2`, the Restore button (`RotateCcw` icon, `aria-label="Restore <title>"`), no Choose subjects, no Retry, no More (nothing else to put there yet). Empty Archived tab without filters: `EmptyState` with `Archive` icon, title "No archived documents", sentence "Archived documents leave search until you restore them." (no Upload action).
- Active tab: each row's actions cell holds its one contextual button (Choose subjects / Retry, as today) and a `RowMenu` (`label="More actions for <title>"`) with one item "Archive" (`Archive` icon); rows still uploading (`uploading.has(id)`) get no menu.
- Archive: call `archive(id)`, announce "<title> archived. Find it under Archived." in the status region, refresh list, counts and My subjects (subject filter options). Restore: call `restore(id)`, announce "<title> restored.", refresh the same. A failure announces "Couldn't archive <title>. Try again." / "Couldn't restore <title>. Try again."; `SessionExpiredError` is left to the session screen. The row's buttons are disabled while its request runs. After the menu's Archive the row disappears, so move focus to the status region (as after a subject save).
- The live-region change announcer must not announce documents that left the list because they were archived (it only compares ids present in both loads, which already holds; keep a test).
- Upload tray: an "already" item with `archived` and a `documentId` shows a small "Restore" button (`aria-label="Restore <name>"`); the page's handler restores the document, sets the item to not archived (it then shows "Already in your library" with its link), announces "<name> restored.", and refreshes. Remove the "Restore arrives with #108" comment.

- [ ] **Step 1: Failing tests** (`LibraryPage.test.tsx`, using the existing injected-fakes style): archive from the More menu calls `archive` with the id, announces, the row leaves the Active list and the Archived count goes up; the Archived tab loads with `archived: true`, shows the notice, the Archived badge, Restore, and no Choose subjects even for an `awaiting_subjects` archived row; Restore calls `restore`, announces, and the Active count goes up; a failed archive announces the retry message; the Archived tab hides the State filter; the empty Archived tab shows "No archived documents". `DocumentTable.test.tsx`: archived rows have Restore and no More; active rows have a More menu with Archive. `UploadTray.test.tsx`: archived duplicate shows Restore and calls `onRestore`. `documents.ts` tests if the file has them (`api/*.test.ts`): `loadDocuments({ archived: true })` sends `archived=true`; `archiveDocument` posts to the right path.
- [ ] **Step 2: Run** `cd web && npx vitest run src/features/library src/components/UploadTray src/api` — fail.
- [ ] **Step 3: Implement** per Behavior.
- [ ] **Step 4: `npx vitest run` and `npm run build` pass.** Render the app states if the Compose app profile is running (web on :10453) or compare against the design PNGs; check both themes.
- [ ] **Step 5: Commit** "Archive from the Library's More menu and restore from the Archived tab".

---

### Task 6: Docs

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/README.md` (services list: `ArchiveService` (`archive`, `restore`); rules: `can_read` lookups return archived documents; active-only callers filter; archive/restore set and clear `archived`/`archived_at` only; an archived document's subjects can't change; `DocumentService.list_documents` takes `archived`; `find_in_library` ignores archived documents)
- Modify: `sdd/prd.md` — bump to v2.26 with a "Changes from v2.25" row: archive/restore endpoints `POST /documents/{id}/archive` and `/restore`, `GET /documents?archived=true`, `DocumentResponse.archived`, choosing subjects of an archived document answers 409 (#108). Update the AGENTS.md PRD version reference to v2.26.

- [ ] **Step 1:** Edit the docs.
- [ ] **Step 2:** Full backend checks + web build still pass.
- [ ] **Step 3: Commit** "Document archive and restore (PRD v2.26)".

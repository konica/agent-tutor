# Document details, with an editable display title (#109) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Opening a document from the Library shows a details side panel (facts, summary, subjects, Archive/Restore), and the learner can edit or reset the document's display title for their own library.

**Architecture:** `knowledge` gains a domain rule (`Document.set_title`, `clean_title`) and two `DocumentService` use cases (`details`, `set_title`) that read through `can_read` (`get_readable`) plus the learner's own content. `apps/api` exposes `GET /documents/{id}` and `PUT /documents/{id}/title`. The web app gets a reusable `SidePanel` component and a `DocumentDetails` panel in `features/library`, opened from the row title and the row's More menu.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy Core / pytest (backend); React + TypeScript + Vite / vitest + Testing Library (web); generated API client (`make api-client`).

**Spec:** GitHub issue #109 (parent US-10 #19); PRD `sdd/prd.md` §8 US-10, §9.4 (display title), §9.5; mockup round v0.10 states `details-ready`, `details-edit-title`, `details-archived` (prototype `sdd/design/prototype/js/documents.js` §6.5 at tag `design-v0.10`); `DESIGN.md`.

## Global Constraints

- Display title = `coalesce(documents.title_override, contents.title, documents.file_name)`, per learner, resolved at read time (PRD §9.4). Editing writes `documents.title_override` only, never `contents.title`.
- Every read goes through `can_read` (`DocumentRepository.get_readable`); a document the caller can't read is a **404** "Document not found", never 403.
- Title cleaning: whitespace runs (incl. newlines/tabs) collapse to one space, control and bidi characters (the existing `_CONTROL` regex in `knowledge/domain/document.py`) are removed, trimmed; empty → `InvalidTitleError("Enter a title")`; more than `MAX_TITLE = 300` characters → `InvalidTitleError("Keep the title to 300 characters or fewer")`. API maps `InvalidTitleError` to **422** with that message as `detail`.
- A cleaned title equal to the extracted title (`content_title`) clears the override (no override needed).
- No download, no Delete, no Open/viewer, no "Ask about this", no "Change subjects" in this slice (owned by #125, #118/#123, #132 and a later picker change mode).
- UI copy (exact): kicker "Document details"; field label "Display title"; helper "Only changes how the title appears to you. Citations use this title."; buttons "Edit title", "Save title", "Cancel", "Reset to extracted title", "Archive", "Restore"; close button accessible name "Close document details"; archived banner title "Archived", text "Not used for answers. Citations to it in past conversations still open here. Restore it to change its subjects."; no-summary text "A summary appears once Smart Tutor can read this PDF."; status messages "Title updated.", "Title reset to the extracted title.", "Document archived.", "Document restored.".
- Visual rules: `DESIGN.md` (compact density, tokens only, both themes, `--panel-w` 340px drawer, lucide icons `strokeWidth={1.5}`, one primary button per view, focus returns to the opener on close).
- Commits: imperative subject, body says why, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`; `cd web && npm run build` and `npx vitest run`.

## Review Focus

1. A title made only of spaces or control/bidi characters → 422 "Enter a title", override unchanged (Task 1 domain test + Task 3 route test).
2. Learner B with the same PDF as learner A: A's rename leaves B's title as extracted; B's GET/PUT on A's document is 404 (Task 3 isolation test).
3. The worker or archive saving a document after a rename keeps the override (every loader reads `title_override`; `save` writes it) (Task 2 SQL integration test: rename → archive → still renamed).
4. Escape while editing the title cancels the edit but does not close the panel; Escape again closes it and focus returns to the row control that opened it (Task 5 and Task 4 tests).
5. A details request for a document still processing (no content yet) returns facts with nulls instead of failing (Task 2 test).

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/src/smart_tutor/knowledge/domain/document.py` (modify) | `MAX_TITLE`, `clean_title`, `Document.set_title` |
| `backend/src/smart_tutor/knowledge/domain/errors.py` (modify) | `InvalidTitleError` |
| `backend/src/smart_tutor/knowledge/application/document_service.py` (modify) | `DocumentDetails`, `DocumentService.details`, `DocumentService.set_title` |
| `backend/src/smart_tutor/knowledge/application/__init__.py` (modify) | export `DocumentDetails`, `InvalidTitleError` |
| `backend/src/smart_tutor/knowledge/adapters/sql_library.py` (modify) | `_Documents.save` writes `title_override` |
| `backend/src/smart_tutor/knowledge/README.md` (modify) | document the new rules |
| `backend/src/smart_tutor/apps/api/routes/knowledge.py` (modify) | two routes, `DocumentDetailsResponse`, `SetTitleRequest` |
| `backend/tests/unit/knowledge/test_domain.py`, `test_document_service.py`, `tests/unit/apps/api/test_knowledge_routes.py`, `tests/isolation/test_documents.py`, `tests/integration/knowledge/test_sql_library.py` (modify) | tests |
| `web/src/api/openapi.json`, `web/src/api/generated/*` (regenerated) | client |
| `web/src/api/documents.ts` (+ test) | `loadDocumentDetails`, `saveDocumentTitle`, `DocumentDetails` type |
| `web/src/components/Dialog/useModal.ts` (create) | shared focus-in / Tab trap / Escape / focus-back hook |
| `web/src/components/SidePanel/SidePanel.tsx`, `.module.css`, `.test.tsx` (create) | right-hand modal drawer |
| `web/src/features/library/DocumentDetails.tsx`, `.module.css`, `.test.tsx` (create) | the details panel |
| `web/src/features/library/DocumentTable.tsx` (+ test, css) | title button and More menu items open details |
| `web/src/features/library/LibraryPage.tsx` (+ test) | holds which document's details are open; refreshes after changes |
| `DESIGN.md` (modify) | `SidePanel` row says built |
| `sdd/prd.md` (modify) | v2.27: details and title endpoints |

---

### Task 1: Domain — clean and set a display title

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/domain/errors.py`
- Modify: `backend/src/smart_tutor/knowledge/domain/document.py`
- Test: `backend/tests/unit/knowledge/test_domain.py`

**Interfaces:**
- Produces: `InvalidTitleError(ValueError-like, same base as InvalidFileNameError)`; `MAX_TITLE: int = 300`; `clean_title(raw: str) -> str` (raises `InvalidTitleError`); `Document.set_title(self, raw: str | None) -> None`.

- [ ] **Step 1: Write the failing tests** (append to `test_domain.py`; reuse its existing helper for building a `Document` if one exists, else build with `Document.start_upload(DocumentId("d"), UserId("ada"), UploadId("u"), "paper.pdf", datetime(2026, 10, 9, tzinfo=UTC))`)

```python
import pytest

from smart_tutor.knowledge.domain.document import MAX_TITLE, clean_title
from smart_tutor.knowledge.domain.errors import InvalidTitleError


def test_clean_title_collapses_whitespace_and_drops_controls() -> None:
    assert clean_title("  ReAct\n(Yao\t et al.) ‮ ") == "ReAct (Yao et al.)"


@pytest.mark.parametrize("raw", ["", "   ", "‎‪\x07", "\n\t"])
def test_clean_title_refuses_an_empty_title(raw: str) -> None:
    with pytest.raises(InvalidTitleError, match="Enter a title"):
        clean_title(raw)


def test_clean_title_refuses_a_title_over_the_limit() -> None:
    assert clean_title("x" * MAX_TITLE) == "x" * MAX_TITLE
    with pytest.raises(InvalidTitleError, match="300 characters"):
        clean_title("x" * (MAX_TITLE + 1))


def test_set_title_overrides_and_clears() -> None:
    doc = _document()  # file name "paper.pdf"
    doc.content_title = "Extracted"
    doc.set_title(" Mine ")
    assert (doc.title_override, doc.title) == ("Mine", "Mine")
    doc.set_title(None)
    assert (doc.title_override, doc.title) == (None, "Extracted")


def test_set_title_equal_to_the_extracted_title_clears_the_override() -> None:
    doc = _document()
    doc.content_title = "Extracted"
    doc.set_title("Mine")
    doc.set_title("Extracted ")
    assert doc.title_override is None


def test_set_title_refusal_keeps_the_old_override() -> None:
    doc = _document()
    doc.set_title("Mine")
    with pytest.raises(InvalidTitleError):
        doc.set_title("   ")
    assert doc.title_override == "Mine"
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/unit/knowledge/test_domain.py -q`
Expected: FAIL (ImportError `clean_title` / `InvalidTitleError`).

- [ ] **Step 3: Implement**

In `errors.py`, next to `InvalidFileNameError` and with the same base class:

```python
class InvalidTitleError(<same base as InvalidFileNameError>):
    """A display title must keep 1-300 characters once cleaned (PRD §9.4)."""
```

In `document.py` (import `InvalidTitleError`):

```python
MAX_TITLE = 300


def clean_title(raw: str) -> str:
    """A display title the learner typed: one line, no control or bidi characters, 1-300 characters (PRD §9.4)."""
    title = " ".join(_CONTROL.sub("", " ".join(raw.split())).split())
    if not title:
        raise InvalidTitleError("Enter a title")
    if len(title) > MAX_TITLE:
        raise InvalidTitleError(f"Keep the title to {MAX_TITLE} characters or fewer")
    return title
```

On `Document`, after `restore`:

```python
    def set_title(self, raw: str | None) -> None:
        """The learner's display title for their library only (`title_override`); None goes back to the extracted one.

        A title equal to the extracted title needs no override.
        """
        title = None if raw is None else clean_title(raw)
        self.title_override = None if title == self.content_title else title
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && uv run pytest tests/unit/knowledge/test_domain.py -q` → PASS

- [ ] **Step 5: Commit** — `git commit -m "Clean and set a document's display title in the domain"` (body: why — the learner fixes a bad extracted title for their own library only, PRD §9.4).

---

### Task 2: DocumentService details and set_title; SQL save keeps the override

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py`
- Modify: `backend/src/smart_tutor/knowledge/application/__init__.py`
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py` (`_Documents.save`)
- Modify: `backend/src/smart_tutor/knowledge/README.md`
- Test: `backend/tests/unit/knowledge/test_document_service.py`, `backend/tests/integration/knowledge/test_sql_library.py`

**Interfaces:**
- Consumes: `Document.set_title`, `InvalidTitleError` (Task 1); `tx.documents.get_readable(user_id, id, for_update=...)`, `tx.contents.get(content_id)`, `document_view(d, max_attempts)`.
- Produces:

```python
@dataclass(frozen=True)
class DocumentDetails:
    document: DocumentView  # authors and year filled from the learner's own content
    file_name: str
    extracted_title: str | None  # contents.title; None until described
    title_overridden: bool
    doi: str | None
    pages: int | None
    summary: str | None

DocumentService.details(self, user_id: UserId, document_id: DocumentId) -> DocumentDetails  # raises DocumentNotFoundError
DocumentService.set_title(self, user_id: UserId, document_id: DocumentId, title: str | None) -> DocumentDetails  # raises DocumentNotFoundError, InvalidTitleError
```

- [ ] **Step 1: Write failing unit tests** (in `test_document_service.py`; use `InMemoryLibrary`, `ingest_ready` from `fakes`, as `test_archive_service.py` does; to give the content an extracted title/summary, edit it through a unit of work: `with library.unit_of_work() as tx: c = tx.contents.get(cid); c.title = "Extracted"; c.summary = "S"; c.doi = "10.1/x"; c.authors = ["Yao"]; c.year = 2022; tx.contents.save(c); tx.commit()` where `cid = library.state.documents[doc].content_id`)

```python
def test_details_carry_facts_summary_and_subjects() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention", [ART])
    _describe(library, doc, title="Extracted", summary="A summary", doi="10.1/x", authors=["Yao"], year=2022)
    details = DocumentService(library.unit_of_work, max_attempts=3).details(ADA, doc)
    assert details.document.title == "Extracted"
    assert details.document.authors == ("Yao",) and details.document.year == 2022
    assert details.document.subject_ids == (ART,)
    assert (details.extracted_title, details.title_overridden) == ("Extracted", False)
    assert (details.doi, details.pages, details.summary) == ("10.1/x", 1, "A summary")
    assert details.file_name.endswith(".pdf")


def test_details_of_an_archived_document() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention", [ART])
    ArchiveService(library.unit_of_work, FixedClock(), max_attempts=3).archive(ADA, doc)
    assert DocumentService(library.unit_of_work, max_attempts=3).details(ADA, doc).document.archived is True


def test_details_of_a_document_still_uploading_have_no_content_facts() -> None:
    library = InMemoryLibrary()
    started = UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(ADA, "p.pdf")
    details = DocumentService(library.unit_of_work, max_attempts=3).details(ADA, DocumentId(started.document_id))
    assert (details.document.title, details.extracted_title, details.pages, details.summary) == ("p.pdf", None, None, None)


def test_details_of_another_learners_document_is_not_found() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention", [ART])
    with pytest.raises(DocumentNotFoundError):
        DocumentService(library.unit_of_work, max_attempts=3).details(UserId("bob"), doc)


def test_set_title_and_reset() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention", [ART])
    _describe(library, doc, title="Extracted")
    docs = DocumentService(library.unit_of_work, max_attempts=3)
    renamed = docs.set_title(ADA, doc, "  Mine ")
    assert (renamed.document.title, renamed.title_overridden) == ("Mine", True)
    assert [v.title for v in docs.list_documents(ADA)] == ["Mine"]
    reset = docs.set_title(ADA, doc, None)
    assert (reset.document.title, reset.title_overridden) == ("Extracted", False)
    assert library.state.contents[library.state.documents[doc].content_id].title == "Extracted"  # content untouched


def test_set_title_of_another_learners_document_is_not_found() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention", [ART])
    with pytest.raises(DocumentNotFoundError):
        DocumentService(library.unit_of_work, max_attempts=3).set_title(UserId("bob"), doc, "Mine")
    assert library.state.documents[doc].title_override is None


def test_a_renamed_document_is_cited_by_its_new_title() -> None:
    library = InMemoryLibrary()
    doc = ingest_ready(library, "ada", "attention mechanisms", [ART])
    DocumentService(library.unit_of_work, max_attempts=3).set_title(ADA, doc, "Mine")
    assert [h.title for h in SearchService(library.unit_of_work, fake_embeddings()).search(ADA, "attention mechanisms")] == ["Mine"]
```

(Check the `ChunkHit` title attribute name in `knowledge/domain/search.py` and adjust `h.title` if it is named differently. Add a small `_describe(library, doc, **fields)` helper in the test module.)

- [ ] **Step 2: Run to verify failures** — `cd backend && uv run pytest tests/unit/knowledge/test_document_service.py -q` → FAIL (`details` missing).

- [ ] **Step 3: Implement** in `document_service.py` (import `DocumentNotFoundError` from `knowledge.domain.errors`, `Document`):

```python
@dataclass(frozen=True)
class DocumentDetails:
    """What the details panel shows (PRD §8 US-10): the Library view plus the learner's own content's facts."""

    document: DocumentView
    file_name: str
    extracted_title: str | None
    title_overridden: bool
    doi: str | None
    pages: int | None
    summary: str | None
```

Methods on `DocumentService`:

```python
    def details(self, user_id: UserId, document_id: DocumentId) -> DocumentDetails:
        """One of the learner's documents, archived or not; others' are not found."""
        with self._uow() as tx:
            return self._details(tx, self._readable(tx, user_id, document_id))

    def set_title(self, user_id: UserId, document_id: DocumentId, title: str | None) -> DocumentDetails:
        """Set the learner's display title, or go back to the extracted one with None (their library only, §9.4)."""
        with self._uow() as tx:
            document = self._readable(tx, user_id, document_id, for_update=True)
            document.set_title(title)
            tx.documents.save(document)
            details = self._details(tx, document)
            tx.commit()
        return details

    @staticmethod
    def _readable(tx: LibraryUnitOfWork, user_id: UserId, document_id: DocumentId, *, for_update: bool = False) -> Document:
        document = tx.documents.get_readable(user_id, document_id, for_update=for_update)
        if document is None:
            raise DocumentNotFoundError("This document isn't in your library")
        return document

    def _details(self, tx: LibraryUnitOfWork, document: Document) -> DocumentDetails:
        # Contents are per learner, so the document's content is the caller's own.
        content = tx.contents.get(document.content_id) if document.content_id is not None else None
        if content is not None:
            document.content_authors, document.content_year = list(content.authors), content.year
        return DocumentDetails(
            document_view(document, self._max_attempts),
            document.file_name,
            document.content_title,
            document.title_override is not None,
            content.doi if content else None,
            content.pages if content else None,
            content.summary if content else None,
        )
```

Export `DocumentDetails` and `InvalidTitleError` from `knowledge/application/__init__.py` (both import and `__all__`, keeping alphabetical order).

In `sql_library.py` `_Documents.save`, add `title_override=document.title_override,` to `.values(...)`.

- [ ] **Step 4: Integration test** in `tests/integration/knowledge/test_sql_library.py` (follow that file's fixtures for an engine and a ready document): set a title via `DocumentService(SqlLibraryUnitOfWork factory, 3).set_title(...)`, then `ArchiveService(...).archive(...)`, then assert `get_readable(...).title_override == "Mine"` and the `list_readable_by` view's `title == "Mine"`; then `set_title(..., None)` and assert the override is `None`. Run (needs `docker compose up -d` and `make migrate`): `cd backend && uv run pytest tests/integration/knowledge/test_sql_library.py -q -m integration`. If Compose isn't available, say so in the report; the unit tests still cover behavior.

- [ ] **Step 5: Run unit tests** — `cd backend && uv run pytest tests/unit/knowledge -q` → PASS; `uv run mypy` → clean.

- [ ] **Step 6: README** — in `knowledge/README.md`: add `set_title()` to `Document`'s key methods and `details`, `set_title` to `DocumentService`; add to Rules: "`DocumentService.details` returns one of the learner's documents (archived or not, through `get_readable`) with its own content's authors, year, DOI, pages, summary, and extracted title. `DocumentService.set_title` sets `documents.title_override` through `Document.set_title` (cleaned with `clean_title`: one line, control and bidi characters removed, 1–300 characters, else `InvalidTitleError`); None, or the extracted title itself, clears it. It never changes `contents.title`; search and the documents used read the display title at read time."

- [ ] **Step 7: Commit** — "Show a document's details and set its display title" (body: why).

---

### Task 3: API routes, isolation test, regenerated client

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py`
- Test: `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/isolation/test_documents.py`
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`

**Interfaces:**
- Consumes: `DocumentService.details`, `DocumentService.set_title`, `DocumentDetails`, `InvalidTitleError` (Task 2); `Documents`, `Subjects`, `CurrentPrincipal` deps; `_document_response`.
- Produces: `GET /documents/{document_id}` (operation_id `get_document`) and `PUT /documents/{document_id}/title` (operation_id `set_document_title`, body `{"title": string | null}`), both returning `DocumentDetailsResponse` = all `DocumentResponse` fields plus `file_name: str`, `extracted_title: str | None`, `title_overridden: bool`, `doi: str | None`, `pages: int | None`, `summary: str | None`. Generated TS: `getDocument`, `setDocumentTitle`, `DocumentDetailsResponse`.

- [ ] **Step 1: Failing route tests** (in `test_knowledge_routes.py`, following its client setup):
  - GET a ready document → 200 with `title`, `subjects` (names), `file_name`, `summary`, `pages`, `title_overridden: false`.
  - GET an unknown UUID → 404.
  - PUT `{"title": "  Mine  "}` → 200, `title == "Mine"`, `title_overridden is True`; then `GET /documents` lists `"Mine"`.
  - PUT `{"title": null}` → 200, back to the extracted title (or file name).
  - PUT `{"title": "   "}` → 422, `detail == "Enter a title"`; PUT 301 chars → 422 with "300 characters"; PUT `{"title": "x", "owner_id": "b"}` → 422 (extra forbidden); PUT `{}` → 422 (title is required, may be null).
- [ ] **Step 2: Failing isolation test** (in `tests/isolation/test_documents.py`, using `setup()` and the same upload+ingest steps as `test_b_cannot_archive_restore_or_see_as_archived_document`):

```python
def test_b_cannot_see_or_rename_as_document_and_keeps_own_title_for_same_file() -> None:
    client, objects, ingestion = setup()
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    docs = {}
    for who, headers in (("a", A), ("b", B)):
        stored = client.post("/uploads", json={"file_name": f"{who}.pdf"}, headers=headers).json()
        objects.objects[stored["fields"]["key"]] = pdf
        ingestion.ingest_upload(stored["fields"]["key"])
        docs[who] = stored["document_id"]

    assert client.get(f"/documents/{docs['a']}", headers=B).status_code == 404
    assert client.put(f"/documents/{docs['a']}/title", json={"title": "B's"}, headers=B).status_code == 404
    assert client.put(f"/documents/{docs['a']}/title", json={"title": "A's"}, headers=A).json()["title"] == "A's"
    assert client.get(f"/documents/{docs['b']}", headers=B).json()["title"] != "A's"
    assert client.get(f"/documents/{docs['a']}", headers=A).json()["title"] == "A's"
```

- [ ] **Step 3: Run to verify failures** — `cd backend && uv run pytest tests/unit/apps/api/test_knowledge_routes.py tests/isolation/test_documents.py -q`.
- [ ] **Step 4: Implement** in `routes/knowledge.py` (update the module docstring to mention details and display title):

```python
class DocumentDetailsResponse(DocumentResponse):
    file_name: str
    extracted_title: str | None  # from the learner's own content; null until described
    title_overridden: bool
    doi: str | None
    pages: int | None
    summary: str | None


class SetTitleRequest(BaseModel):
    # null goes back to the extracted title. Cleaning and the 300-character limit are the domain's (PRD §9.4).
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(max_length=2000)


def _details_response(details: DocumentDetails, names: dict[SubjectId, str]) -> DocumentDetailsResponse:
    return DocumentDetailsResponse(
        **_document_response(details.document, names).model_dump(),
        file_name=details.file_name,
        extracted_title=details.extracted_title,
        title_overridden=details.title_overridden,
        doi=details.doi,
        pages=details.pages,
        summary=details.summary,
    )


@router.get("/documents/{document_id}", operation_id="get_document")
def get_document(document_id: UUID, principal: CurrentPrincipal, documents: Documents, subjects: Subjects) -> DocumentDetailsResponse:
    """The caller's document with its facts, summary, and subjects, archived or not (PRD §8 US-10)."""
    try:
        details = documents.details(principal.user_id, DocumentId(str(document_id)))
    except DocumentNotFoundError:
        raise HTTPException(404, "Document not found") from None
    return _details_response(details, subjects.names_for(principal.user_id, set(details.document.subject_ids)))


@router.put("/documents/{document_id}/title", operation_id="set_document_title")
def set_document_title(
    document_id: UUID, body: SetTitleRequest, principal: CurrentPrincipal, documents: Documents, subjects: Subjects
) -> DocumentDetailsResponse:
    """Set the caller's display title for this document, or clear it with null; their library only (PRD §9.4)."""
    try:
        details = documents.set_title(principal.user_id, DocumentId(str(document_id)), body.title)
    except DocumentNotFoundError:
        raise HTTPException(404, "Document not found") from None
    except InvalidTitleError as e:
        raise HTTPException(422, str(e)) from None
    return _details_response(details, subjects.names_for(principal.user_id, set(details.document.subject_ids)))
```

Route order: `GET /documents/{document_id}` must not shadow `/documents/duplicate-check` (that one is POST, so no clash) — keep the new GET after `list_documents`.

- [ ] **Step 5: Run** — the two test files → PASS; then the full backend checks from Global Constraints.
- [ ] **Step 6: Regenerate the client** — the `api-client` Makefile target: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Then `cd web && npm run build` must pass.
- [ ] **Step 7: Commit** — "Add document details and display title routes".

---

### Task 4: SidePanel component (shared modal focus hook)

**Files:**
- Create: `web/src/components/Dialog/useModal.ts`
- Modify: `web/src/components/Dialog/Dialog.tsx` (use the hook; behavior unchanged — existing `Dialog.test.tsx` must still pass)
- Create: `web/src/components/SidePanel/SidePanel.tsx`, `SidePanel.module.css`, `SidePanel.test.tsx`
- Modify: `DESIGN.md` (components table: split `SidePanel` into its own row: "built (document details): a right-hand modal drawer of `--panel-w`, kicker and badge header, close button, scrolling body, footer; focus moves in, Tab stays in, Escape closes, focus goes back")

**Interfaces:**
- Produces:

```ts
// useModal.ts
export function useModal(onClose: () => void): { ref: RefObject<HTMLDivElement | null>; onKeyDown: (event: KeyboardEvent) => void };
// moves focus to [data-autofocus] or the first focusable on mount, returns focus to the previous element on unmount,
// Escape → stopPropagation + onClose, Tab/Shift+Tab wrap inside ref.

// SidePanel.tsx
type Props = { labelledBy: string; kicker: string; badge?: ReactNode; closeLabel: string; onClose: () => void; children: ReactNode; footer?: ReactNode };
export function SidePanel(props: Props): JSX.Element;
```

- [ ] **Step 1: Failing tests** (`SidePanel.test.tsx`, Testing Library + `userEvent`, like `Dialog.test.tsx`): renders `role="dialog"` with `aria-modal="true"` named by the element with id `labelledBy`; shows kicker and badge; the close button (name = `closeLabel`) calls `onClose`; Escape calls `onClose`; focus starts on `[data-autofocus]` inside children when present; Tab from the last focusable wraps to the first; on unmount focus returns to the button that was focused before opening.
- [ ] **Step 2: Run to verify failures** — `cd web && npx vitest run src/components/SidePanel`.
- [ ] **Step 3: Implement** `useModal` by moving the focus logic from `Dialog.tsx` (the `FOCUSABLE` selector, the mount effect, the `onKeyDown`) into the hook; `Dialog` uses `const { ref, onKeyDown } = useModal(onClose)`. `SidePanel`:

```tsx
export function SidePanel({ labelledBy, kicker, badge, closeLabel, onClose, children, footer }: Props) {
  const { ref, onKeyDown } = useModal(onClose);
  return (
    <div className={styles.scrim} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside ref={ref} className={styles.panel} role="dialog" aria-modal="true" aria-labelledby={labelledBy} onKeyDown={onKeyDown}>
        <header className={styles.header}>
          <div className={styles.heading}>
            <p className={styles.kicker}>{kicker}</p>
            {badge}
          </div>
          <IconButton label={closeLabel} icon={X} tip={false} onClick={onClose} />
        </header>
        <div className={styles.body}>{children}</div>
        {footer && <footer className={styles.footer}>{footer}</footer>}
      </aside>
    </div>
  );
}
```

CSS (tokens only): scrim `position: fixed; inset: 0; z-index: 50; background: var(--scrim)`; panel `position: absolute; inset-block: 0; inset-inline-end: 0; width: min(var(--panel-w), 100%); display: flex; flex-direction: column; background: var(--surface); border-inline-start: 1px solid var(--border); box-shadow: var(--shadow-lg)`; header `padding: var(--sp-4); border-bottom: 1px solid var(--border); display:flex; justify-content: space-between; gap: var(--sp-3)`; kicker as in `Dialog.module.css`; body `flex: 1; overflow-y: auto; padding: var(--sp-4); display: grid; align-content: start; gap: var(--sp-4)`; footer `display:flex; justify-content:flex-end; gap: var(--sp-2); padding: var(--sp-3) var(--sp-4); border-top: 1px solid var(--border)`. Slide-in animation with `var(--dur-base) var(--ease-out)`, disabled under `prefers-reduced-motion` if the codebase does that elsewhere.
- [ ] **Step 4: Run** — `npx vitest run src/components` → PASS.
- [ ] **Step 5: Commit** — "Add a SidePanel drawer sharing Dialog's focus handling".

---

### Task 5: API helpers and the DocumentDetails panel

**Files:**
- Modify: `web/src/api/documents.ts`, `web/src/api/documents.test.ts`
- Create: `web/src/features/library/DocumentDetails.tsx`, `DocumentDetails.module.css`, `DocumentDetails.test.tsx`

**Interfaces:**
- Consumes: generated `getDocument`, `setDocumentTitle`, `DocumentDetailsResponse` (Task 3); `SidePanel` (Task 4); existing `StateBadge`, `SubjectChip`, `Button`, `Banner`, `byline`, `APP_TIME_ZONE`, `failure`, `sessionOver`, `SessionExpiredError`.
- Produces:

```ts
export type DocumentDetails = DocumentDetailsResponse;
export async function loadDocumentDetails(documentId: string, apiClient?: Client): Promise<DocumentDetails>; // 404 → Error("Document not found")
export async function saveDocumentTitle(documentId: string, title: string | null, apiClient?: Client): Promise<DocumentDetails>; // 422 → Error(detail message)

type DocumentDetailsProps = {
  documentId: string;
  startEditing?: boolean;
  load: (id: string) => Promise<DocumentDetails>;
  saveTitle: (id: string, title: string | null) => Promise<DocumentDetails>;
  archive: (id: string) => Promise<unknown>;
  restore: (id: string) => Promise<unknown>;
  onChanged: () => void; // the Library re-lists after a title, archive, or restore change
  onClose: () => void;
};
export function DocumentDetailsPanel(props: DocumentDetailsProps): JSX.Element;
```

- [ ] **Step 1: Failing API helper tests** in `documents.test.ts` following its existing pattern for `archiveDocument` (fake fetch / client): `loadDocumentDetails` returns the body; 401 throws `SessionExpiredError`; `saveDocumentTitle` sends `PUT /documents/{id}/title` with `{"title": "Mine"}` and with `{"title": null}`; a 422 `{"detail": "Enter a title"}` throws an `Error` with message "Enter a title".
- [ ] **Step 2: Implement** the helpers like `archiveDocument` (`if (!data) throw failure(error)`).
- [ ] **Step 3: Failing panel tests** (`DocumentDetails.test.tsx`, fake `load`/`saveTitle`/`archive`/`restore` as `vi.fn`, a `details()` fixture builder with `state: "ready"`, `archived: false`, `title: "ReAct"`, `extracted_title: "ReAct"`, `title_overridden: false`, `authors: ["Yao", "Zhao"]`, `year: 2022`, `doi: "10.48550/arXiv.2210.03629"`, `file_name: "react.pdf"`, `pages: 33`, `summary: "Proposes…"`, subjects `[{subject_id: "s1", name: "AI Agents"}]`):
  1. Ready: shows the "Document details" kicker, "Ready" badge, the title as heading naming the dialog, facts (Authors "Yao, Zhao", Year, DOI, File name, Pages, Uploaded), the summary, the "AI Agents" chip, an "Edit title" button, and an "Archive" button; no "Restore", no Delete/Download/Open buttons.
  2. Edit: clicking "Edit title" shows a textbox labelled "Display title" with the current title, focused, and the helper text; typing "ReAct (Yao et al.)" and clicking "Save title" calls `saveTitle("d1", "ReAct (Yao et al.)")`, leaves edit mode with the new title as heading, shows "Title updated." in a status region, and calls `onChanged`.
  3. Validation: clearing the field and pressing Enter shows "Enter a title" (as an alert next to the field) and does not call `saveTitle`; 301 characters shows "Keep the title to 300 characters or fewer"; a rejected `saveTitle` with `Error("Enter a title")` shows that message and stays in edit mode.
  4. Reset: with `title_overridden: true`, `title: "Mine"`, `extracted_title: "ReAct"`, view mode shows "Extracted title: ReAct" and a "Reset to extracted title" button; clicking it calls `saveTitle("d1", null)` and announces "Title reset to the extracted title."; the edit form also shows "Reset to extracted title" when overridden; neither shows when not overridden or when `extracted_title` is null.
  5. Escape in the title field cancels editing (title unchanged, `onClose` not called); a second Escape calls `onClose`.
  6. Archive: clicking "Archive" calls `archive("d1")`, then reloads (`load` called again) and shows the Archived state; announces "Document archived."; calls `onChanged`.
  7. Archived (`archived: true`): "Archived" badge, the archived banner text, "Restore" button (primary) and no "Archive" and no "Edit title"; Restore calls `restore("d1")`, reloads, announces "Document restored.".
  8. `startEditing` opens directly in edit mode with the field focused.
  9. No summary → "A summary appears once Smart Tutor can read this PDF."; null facts show "—"; a failed document shows its `failure_reason` in a danger banner and no "Edit title".
  10. `load` rejecting shows "Couldn't load this document." with the close button still usable.
- [ ] **Step 4: Implement** `DocumentDetailsPanel`:
  - State: `details: DocumentDetails | null`, `loadError: boolean`, `editing: boolean` (init `startEditing`), `draft: string`, `error: string | null`, `saving: boolean`, `status: string`.
  - `useEffect` loads once; `reload()` re-calls `load` and sets `details`.
  - Header: `SidePanel` with `kicker="Document details"`, `closeLabel="Close document details"`, `labelledBy` = id of the `<h2>` title (or of the input's label while editing), `badge` = `<StateBadge state={details.archived ? "archived" : details.state} />`.
  - Body order (mockup): failed banner (danger, `failure_reason`) / archived banner; title block; `<dl>` facts; Summary section (`<h3>`); Subjects section (`<h3>`, `SubjectChip`s, else "No subjects yet." / for processing "You can choose subjects when processing finishes." / for awaiting_subjects "Processing has finished; choose its subjects from the Library.").
  - Title block, view mode: `<h2 id=…>` title + ghost small `Button icon={Pencil}` "Edit title" (only when `!archived && state !== "failed"`); when `title_overridden && extracted_title`: `<p>` "Extracted title: {extracted_title} · " + ghost small button "Reset to extracted title".
  - Edit mode: a `<form onSubmit>` with `<label htmlFor>` "Display title", `<input data-autofocus aria-describedby={helper id + error id} aria-invalid={!!error}>`, helper text, error `<p role="alert">` with a `CircleAlert` icon, then buttons "Save title" (primary sm, submit), "Cancel" (quiet sm), and "Reset to extracted title" (ghost sm, `RotateCcw`) when `title_overridden && extracted_title`. Input `onKeyDown`: Escape → `preventDefault(); stopPropagation(); setEditing(false)` (focus back to "Edit title"). Client check: trimmed empty → "Enter a title"; collapsed-whitespace length > 300 → "Keep the title to 300 characters or fewer"; else `saveTitle`. Errors from `saveTitle` (except `SessionExpiredError`, which is rethrown/ignored as LibraryPage does) show their message, or "Couldn't save the title. Try again." when empty.
  - Footer: archived → primary "Restore" (`RotateCcw`); otherwise secondary "Archive" (`Archive` icon). Disabled while running. After success: `reload()`, set status, `onChanged()`.
  - Status: a visually hidden `<p role="status" aria-live="polite">` inside the panel.
  - Uploaded: `new Date(created_at).toLocaleDateString(undefined, { timeZone: APP_TIME_ZONE, day: "numeric", month: "short", year: "numeric" })`.
  - CSS: facts `<dl>` as a two-column grid (`grid-template-columns: 96px 1fr`, rows separated by `1px solid var(--border)`, `--fs-13`, dt `--text-2`); title `--fs-18` 650; section `h3` `--fs-14` 600 margin 0; summary `--fs-14`/`--lh-body`; chips wrap with `--sp-1` gap; all tokens from `DESIGN.md`.
- [ ] **Step 5: Run** — `cd web && npx vitest run src/features/library/DocumentDetails.test.tsx src/api/documents.test.ts` → PASS.
- [ ] **Step 6: Commit** — "Add the document details panel with an editable display title".

---

### Task 6: Open details from the Library

**Files:**
- Modify: `web/src/features/library/DocumentTable.tsx`, `DocumentTable.module.css`, `DocumentTable.test.tsx`
- Modify: `web/src/features/library/LibraryPage.tsx`, `LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `DocumentDetailsPanel`, `loadDocumentDetails`, `saveDocumentTitle` (Task 5); existing `refresh`, `counts.refresh`, `refreshSubjects`, `archive`, `restore` in `LibraryPage`.
- Produces: `DocumentTable` prop `onOpen?: (doc: DocumentResponse, options?: { editTitle?: boolean }) => void`; `LibraryPage` props `loadDetails?: (id: string) => Promise<DocumentDetails>`, `saveTitle?: (id: string, title: string | null) => Promise<DocumentDetails>`.

- [ ] **Step 1: Failing table tests**: with `onOpen`, the title is a button named by the document title; clicking it calls `onOpen(doc)`. The More menu of an active, non-failed row lists "Details", "Edit title", "Archive" in that order; "Edit title" calls `onOpen(doc, { editTitle: true })`; a failed row's menu has "Details" and "Archive" but no "Edit title". An archived row's title button also calls `onOpen(doc)`. Without `onOpen` the title stays plain text (existing tests unchanged).
- [ ] **Step 2: Implement** in `DocumentTable`: when `onOpen` is set, render the title as `<button type="button" className={styles.titleButton} title={doc.title} onClick={() => onOpen(doc)}>{doc.title}</button>` (CSS: reset button styles, keep `.title` truncation, `color: inherit`, underline on hover, visible focus ring); pass `onOpen` into `Actions` and build RowMenu items `[{label: "Details", icon: Info, …}, …(doc.state !== "failed" ? [{label: "Edit title", icon: Pencil, onSelect: () => onOpen(doc, { editTitle: true })}] : []), {label: "Archive", …}]` (Details/Edit title only when `onOpen` is given).
- [ ] **Step 3: Failing LibraryPage tests**: clicking a row title opens a dialog named by the document's title with "Document details"; "Edit title" from the More menu opens it with the "Display title" field focused; saving a title through the panel re-lists (the fake `load` is called again and the row shows the new title); archiving from the panel re-lists; closing the panel returns focus to the title button.
- [ ] **Step 4: Implement** in `LibraryPage`: `const [details, setDetails] = useState<{ id: string; editing: boolean } | null>(null);`, `onOpen={(d, o) => setDetails({ id: d.document_id, editing: Boolean(o?.editTitle) })}` on `DocumentTable`, and render

```tsx
{details && (
  <DocumentDetailsPanel
    key={details.id}
    documentId={details.id}
    startEditing={details.editing}
    load={loadDetails}
    saveTitle={saveTitle}
    archive={archive}
    restore={restore}
    onChanged={() => void Promise.all([refresh(), counts.refresh(), refreshSubjects()])}
    onClose={() => setDetails(null)}
  />
)}
```

with defaults `const defaultLoadDetails = (id: string) => loadDocumentDetails(id); const defaultSaveTitle = (id: string, title: string | null) => saveDocumentTitle(id, title);`. Hide the drop overlay while the panel is open (`{dragging && !picking && !details && <DropOverlay />}`). Note: the opener row can leave the current list after Archive (Active tab) — `useModal` returning focus to a detached element is harmless; then focus the status region if `document.activeElement === document.body` in `onClose`.
- [ ] **Step 5: Run** — `cd web && npx vitest run src/features/library && npm run build` → PASS.
- [ ] **Step 6: Visual check** — run the app or render with the mock (`make web` with the API) if available; at minimum compare against `.design-shots/v0.10/details-*.png` in both themes by reading the CSS against `DESIGN.md`. Note in the report what was checked.
- [ ] **Step 7: Commit** — "Open document details from the Library title and More menu".

---

### Task 7: PRD v2.27

**Files:**
- Modify: `sdd/prd.md`

- [ ] **Step 1:** Bump the status line version to v2.27 and add a "Changes from v2.26" row, in the style of existing rows: "Document details (#109): `GET /documents/{id}` returns the caller's document, archived or not, with authors, year, DOI, file name, pages, summary, subjects, extracted title, and whether the title is overridden; `PUT /documents/{id}/title` sets the learner's display title (`title_override`: one line, control and bidi characters removed, 1–300 characters, 422 otherwise) or clears it with null (Reset to extracted title); another learner's document is a 404. The Library opens details from a row's title and More menu (Details, Edit title). Open, Ask about this, Delete, and Change subjects in details come with their own stories."
- [ ] **Step 2:** In US-10 (around the "edit its display title" line) add the 1–300 character rule and that a title equal to the extracted title clears the override; check §9.4 "Display title" line still matches.
- [ ] **Step 3: Commit** — "Document the details and display title contract (PRD v2.27)".

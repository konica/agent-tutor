# Delete a document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The owner deletes a document from the Library's More menu; its rows, chunks, and every S3 version of its PDF and page text are gone, while conversations keep their text and show it as "Deleted" (#125).

**Architecture:** `knowledge` gains `Document.check_deletable()`, repository removes, `ObjectStore.delete_all_versions`, and a `DeleteService` that locks content then document (the retry lock order), calls a `keep_title` hook, removes the rows, commits, then deletes S3 versions. The hook is `tutoring`'s `ConversationService.keep_deleted_title`, wired in `apps/api/services.py` (knowledge may not import tutoring, S4/module order). `DELETE /documents/{id}` answers `204`. The web adds a danger `Button`, a delete dialog, Delete in each row's More menu, and marks citations and documents used as Deleted.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy Core / boto3 / pytest; AWS CDK (Python); React + TypeScript + Vite / Vitest + Testing Library.

**Spec:** GitHub issue #125 (parent #119); PRD `sdd/prd.md` §8 US-10c, D10, §9.5 (Delete row, document lifecycle), §9.4 (Thread document), §10.1 "Isolation, duplicates, and delete"; ADR 0011; design round `design-v0.10`, states `library-more-menu`, `library-delete-confirm`, `library-deleted`, `chat-citation-deleted`, `chat-documents-used-deleted` (`make design-shots ROUND=v0.10 STATES="library-more-menu,library-delete-confirm,library-deleted,chat-citation-deleted,chat-documents-used-deleted" THEME=both`).

**Base:** this branch stacks on #162 (archive/restore, branch `108-archive-restore`) merged with `main` (#122 documents used). Merge #162 first.

## Global Constraints

- No migration: `thread_documents.deleted_title` exists (0009); `thread_documents` has no FK to `documents`.
- Delete is refused with `409` only while the document state is `processing`. Any other state (awaiting_subjects, ready, failed) and archived documents can be deleted. Another learner's or a missing id → `404 "Document not found"` (same body for both).
- Lock order is the retry's: read the document unlocked → lock its content (`contents.get_for_update`) → lock the document (`get_readable(..., for_update=True)`) and re-check. A document without content (`content_id is None`) locks only the document.
- The title copy (`thread_documents.deleted_title`) runs **before** the knowledge commit, in tutoring's own transaction, and only for threads whose `user_id` is the deleter. If the knowledge commit then fails, the copied title is harmless (a live document's view wins). A turn saved after the delete gets a row with `deleted_title = NULL` and reads "Deleted document" (already handled by #122).
- After the commit, delete every version and delete marker of `contents/<owner_id>/<content_id>.pdf` and `contents/<owner_id>/<content_id>.pages.json` (always both keys; `pages_key()` even when `text_key` is None). An S3 failure after commit is logged with the keys (`logger.exception`) and the route still answers `204`.
- Usage rows are untouched (no usage table yet; #18 labels them). `uploads` rows stay; `GET /uploads/{id}` already returns `document_id: null` for a missing document.
- Details-panel entry points (details-ready/archived/processing states) are out of scope: the details panel is #109. The viewer and `GET /chunks/{id}` / `get_chunk` don't exist yet (#118); deleting the chunks is what makes them 404 later.
- UI copy, verbatim: menu item "Delete…" (danger, last, after a separator); dialog title "Delete *title*?" (title in `<em>`); body "This can't be undone. Conversations and notes keep their text."; for a non-archived document, under it "Archive hides it and can be undone." and a secondary small button "Archive instead"; footer **Cancel** (focused first) and danger **Delete** (Trash2 icon); announcement "*Title* deleted."; citation "Deleted document" (no link); panel badge "Deleted" with `X` icon; panel note "Deleted documents can't be opened." (Info icon) once, under the list, only when any is deleted.
- Web: rebuild with `web/src/components/` and tokens; never paste prototype HTML/CSS. Icons `lucide-react`, `strokeWidth={1.5}`, `aria-hidden="true"`. Check both themes.
- Checks before each commit (backend): `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Integration (Compose up): `uv run pytest -m integration <files>`. Web: `cd web && npm run build && npx vitest run`. Infra: `cd infra && uv run pytest`.
- After changing an API route: `make api-client` (or its two commands from the `Makefile`).
- Commit subjects in the imperative mood, body says why, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Deleting a `failed` document that never got a content (`content_id is None`): the document row goes, nothing else is touched, no S3 call fails — Task 3 unit test.
- Retry racing a delete on the same failed document: the delete must not deadlock and must re-check state under the lock (retry may have made it `processing` → 409) — Task 3 unit test simulates "state changed to processing between the unlocked read and the locked read".
- Another learner's copy of the same file (same SHA-256, own content) is untouched: rows, chunks, and S3 objects — Task 4 isolation test.
- S3 failing after the DB commit: `204`, rows gone, error logged with both keys — Task 3 unit test with a failing fake store.
- A delete during a streamed answer that cites it: the answer's `record_answer` still adds the row and documents used shows it Deleted with "Deleted document" as title; the citation reads "Deleted document" — Task 2 unit test (backend) and Task 6 web test.

---

### Task 1: Storage primitives — S3 "delete all versions", content/chunk removal, `check_deletable`

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/ports/object_store.py` (add abstract `delete_all_versions`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/s3_object_store.py`
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py` (`ContentRepository.remove`, `ChunkRepository.remove_for_content`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py`
- Modify: `backend/src/smart_tutor/knowledge/domain/document.py` (`check_deletable`)
- Modify: `backend/tests/fakes/knowledge.py`
- Test: `backend/tests/unit/knowledge/test_domain.py`, `backend/tests/integration/knowledge/test_s3_object_store.py`, `backend/tests/integration/knowledge/test_sql_library.py`

**Interfaces:**
- Produces: `ObjectStore.delete_all_versions(key: str) -> None` (every version and delete marker of exactly `key`; missing key is not an error); `FakeObjectStore.versions_deleted: list[str]`; `ContentRepository.remove(content_id: ContentId) -> None`; `ChunkRepository.remove_for_content(content_id: ContentId) -> None`; `Document.check_deletable() -> None` raising `DocumentStateError("This document is still processing")`.

- [ ] **Step 1: Failing domain test** in `test_domain.py` (use the module's existing document builder):

```python
def test_only_a_processing_document_cant_be_deleted() -> None:
    doc = _processing_document()  # existing helper or Document.start(...)
    with pytest.raises(DocumentStateError):
        doc.check_deletable()
    for state in (DocumentState.AWAITING_SUBJECTS, DocumentState.READY, DocumentState.FAILED):
        doc.state = state
        doc.check_deletable()  # no error
    doc.archived = True
    doc.check_deletable()
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/knowledge/test_domain.py -k deleted -v` → FAIL (no attribute).

- [ ] **Step 3: Implement** in `Document`:

```python
    def check_deletable(self) -> None:
        """Delete is refused only while processing (PRD §9.5); archived and failed documents can go."""
        if self.state is DocumentState.PROCESSING:
            raise DocumentStateError("This document is still processing")
```

- [ ] **Step 4: Failing integration tests.** In `test_s3_object_store.py` (LocalStack's bucket is versioned, `local/localstack/init/ready.d/10-smart-tutor.sh`):

```python
def test_delete_all_versions_removes_every_version_and_marker_of_that_key_only(store: S3ObjectStore) -> None:
    key = f"contents/it-{uuid.uuid4()}/{uuid.uuid4()}.pdf"
    neighbour = key + ".bak"  # shares the prefix
    store.put(key, b"v1", "application/pdf")
    store.put(key, b"v2", "application/pdf")
    store.delete(key)  # leaves a delete marker
    store.put(neighbour, b"keep", "application/pdf")

    store.delete_all_versions(key)
    store.delete_all_versions(key)  # nothing left: not an error

    versions = store._client.list_object_versions(Bucket=BUCKET, Prefix=key)
    assert [v["Key"] for v in versions.get("Versions", []) + versions.get("DeleteMarkers", [])] == [neighbour]
    assert store.read(neighbour) == b"keep"
```

In `test_sql_library.py`, using the module's existing helpers for a stored content with chunks:

```python
def test_removing_a_content_and_its_chunks_leaves_other_contents(engine: Engine) -> None:
    # arrange: two contents of one learner, each with chunks (reuse the module's chunk-writing helper)
    ...
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.chunks.remove_for_content(gone.content_id)
        tx.documents.remove(gone_doc.document_id)
        tx.contents.remove(gone.content_id)
        tx.commit()
    with engine.connect() as conn:
        assert conn.execute(select(func.count()).select_from(chunks).where(chunks.c.content_id == gone.content_id)).scalar() == 0
        assert conn.execute(select(func.count()).select_from(contents).where(contents.c.content_id == gone.content_id)).scalar() == 0
        assert conn.execute(select(func.count()).select_from(chunks).where(chunks.c.content_id == kept.content_id)).scalar() > 0
```

(Fill the arrange part with the helpers already used by the chunk/search tests in that file; the assertions are fixed.)

- [ ] **Step 5: Run** `uv run pytest -m integration tests/integration/knowledge -k "delete_all_versions or removing_a_content" -v` → FAIL.

- [ ] **Step 6: Implement.**

Port (`object_store.py`):

```python
    @abstractmethod
    def delete_all_versions(self, key: str) -> None:
        """Delete every stored version and delete marker of exactly `key` (the bucket is versioned, PRD §9.5).

        A missing key is not an error.
        """
```

S3 adapter:

```python
    def delete_all_versions(self, key: str) -> None:
        # The prefix also matches longer keys, so only exact matches are deleted.
        paginator = self._client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=key):
            found = [
                {"Key": v["Key"], "VersionId": v["VersionId"]}
                for v in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
                if v["Key"] == key
            ]
            if not found:
                continue
            result = self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": found, "Quiet": True})
            if result.get("Errors"):
                raise RuntimeError(f"Couldn't delete every version of {key}: {result['Errors']}")
```

(A page holds at most 1000 entries, the `delete_objects` limit.)

Fake (`FakeObjectStore`): add `self.versions_deleted: list[str] = []` in `__init__` and

```python
    def delete_all_versions(self, key: str) -> None:
        self.versions_deleted.append(key)
        self.objects.pop(key, None)
        self.content_types.pop(key, None)
```

Ports (`library.py`): `ContentRepository.remove(self, content_id) -> None` docstring "Delete the content row; its chunks must be gone first."; `ChunkRepository.remove_for_content(self, content_id) -> None` docstring "Delete every chunk of the content."

SQL (`sql_library.py`): `delete(contents).where(contents.c.content_id == content_id)` and `delete(chunks).where(chunks.c.content_id == content_id)`. Fakes: `self._s.contents.pop(content_id, None)` and `self._s.chunks.pop(content_id, None)`; also make the fake `_Documents.remove` drop nothing else (document_subjects live on the Document there).

- [ ] **Step 7: Run** unit + the two integration tests → PASS; run the full backend checks.

- [ ] **Step 8: Commit** "Add delete-all-versions and content removal for deleting a document".

---

### Task 2: Tutoring keeps a deleted document's title

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/ports/thread_repository.py` (`keep_deleted_title`)
- Modify: `backend/src/smart_tutor/tutoring/adapters/sql_threads.py`
- Modify: `backend/src/smart_tutor/tutoring/application/conversation_service.py`
- Modify: `backend/tests/fakes/tutoring.py`
- Modify: `backend/src/smart_tutor/tutoring/README.md` (one sentence on `keep_deleted_title`)
- Test: `backend/tests/unit/tutoring/test_conversation_service.py`, `backend/tests/integration/tutoring/test_sql_threads.py`

**Interfaces:**
- Produces: `ThreadRepository.keep_deleted_title(user_id: UserId, document_id: DocumentId, title: str) -> None` (sets `deleted_title` on that document's rows in the user's threads only; its own transaction); `ConversationService.keep_deleted_title(user_id: UserId, document_id: DocumentId, title: str) -> None` (delegates).

- [ ] **Step 1: Failing unit tests** in `test_conversation_service.py` (use its existing setup helpers for a service with `InMemoryThreads` and an `InMemoryLibrary`-backed `DocumentService`):

```python
def test_a_deleted_document_keeps_its_title_in_the_learners_threads_only() -> None:
    # learner-a's thread used doc; learner-b's thread has a row with the same document id (cannot happen in
    # practice, but the update must be scoped by owner)
    ...
    service.keep_deleted_title(UserId("learner-a"), doc, "Chain-of-Thought Prompting")
    remove the document from the library (library.state.documents.pop(doc))
    assert [(d.title, d.deleted) for d in service.documents_used(thread_a, UserId("learner-a"))] == [("Chain-of-Thought Prompting", True)]
    assert [(d.title, d.deleted) for d in service.documents_used(thread_b, UserId("learner-b"))] == [("Deleted document", True)]


def test_an_answer_saved_after_the_delete_lists_the_document_as_deleted() -> None:
    # the streamed answer cited doc; the document is deleted before record_answer runs
    ...
    library.state.documents.pop(doc)
    service.record_answer(thread, UserId("learner-a"), [DocumentId(doc)])
    assert [(d.title, d.deleted) for d in service.documents_used(thread, UserId("learner-a"))] == [("Deleted document", True)]
```

Write the `...` arrange with the file's existing helpers (start a thread, `record_answer` with the doc id).

- [ ] **Step 2: Run** → FAIL (no `keep_deleted_title`).

- [ ] **Step 3: Implement.** Port:

```python
    @abstractmethod
    def keep_deleted_title(self, user_id: UserId, document_id: DocumentId, title: str) -> None:
        """Copy a document's display title onto its rows in the user's threads, before the document is deleted."""
```

SQL:

```python
    def keep_deleted_title(self, user_id: UserId, document_id: DocumentId, title: str) -> None:
        owned = select(threads.c.thread_id).where(threads.c.user_id == user_id)
        with self._engine.begin() as conn:
            conn.execute(
                update(thread_documents)
                .where(thread_documents.c.document_id == document_id, thread_documents.c.thread_id.in_(owned))
                .values(deleted_title=title)
            )
```

Fake: for each thread in `self.threads.values()` with `user_id == user_id`, replace rows in `documents_used_rows[thread_id]` whose `document_id` matches with `dataclasses.replace(row, deleted_title=title)`.

Service:

```python
    def keep_deleted_title(self, user_id: UserId, document_id: DocumentId, title: str) -> None:
        """Called by the document delete before it commits, so documents used keep the title (US-10c)."""
        self._threads.keep_deleted_title(user_id, document_id, title)
```

- [ ] **Step 4: Integration test** in `test_sql_threads.py`: two users' threads with rows for one document id; `keep_deleted_title` for user A; `documents_used` shows the title only on A's row. Run with `-m integration`.

- [ ] **Step 5: Run** all checks → PASS. **Commit** "Keep a deleted document's title in the learner's threads".

---

### Task 3: `DeleteService`

**Files:**
- Create: `backend/src/smart_tutor/knowledge/application/delete_service.py`
- Modify: `backend/src/smart_tutor/knowledge/application/__init__.py` (export `DeleteService`)
- Modify: `backend/src/smart_tutor/knowledge/README.md` (key class + rule sentence)
- Test: `backend/tests/unit/knowledge/test_delete_service.py`

**Interfaces:**
- Consumes: Task 1 (`check_deletable`, `remove`, `remove_for_content`, `delete_all_versions`), `content_key`, `pages_key` from `knowledge/domain/content.py`.
- Produces: `DeleteService(uow: Callable[[], LibraryUnitOfWork], objects: ObjectStore, keep_title: Callable[[UserId, DocumentId, str], None])` with `delete(user_id: UserId, document_id: DocumentId) -> None`; raises `DocumentNotFoundError("Document not found")` and `DocumentStateError`.

- [ ] **Step 1: Failing tests** (`test_delete_service.py`, using `InMemoryLibrary`, `FakeObjectStore`, and the `ingest_ready` helper used by `test_document_service.py` — import it the same way):

```python
def service(library, objects, kept=None):
    kept = kept if kept is not None else []
    return DeleteService(library.unit_of_work, objects, lambda u, d, t: kept.append((u, d, t))), kept


def test_delete_removes_the_document_its_content_chunks_and_every_file_version() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    doc = ingest_ready(library, "ada", "Attention weighs tokens.", [ART])
    content_id = library.state.documents[doc].content_id
    deleter, kept = service(library, objects)

    deleter.delete(UserId("ada"), DocumentId(doc))

    assert doc not in library.state.documents
    assert content_id not in library.state.contents and content_id not in library.state.chunks
    assert sorted(objects.versions_deleted) == sorted([content_key(UserId("ada"), content_id), pages_key(UserId("ada"), content_id)])
    assert kept == [(UserId("ada"), DocumentId(doc), "<the document's display title>")]  # use library.state.documents[doc].title captured before


def test_another_learners_or_a_missing_document_is_not_found_and_nothing_changes() -> None:
    ...  # ingest for "ada"; delete as "bob" and with a random id → DocumentNotFoundError; ada's doc, content, chunks remain; kept == []; versions_deleted == []


def test_a_processing_document_cant_be_deleted() -> None:
    ...  # Document.start(...) added to library state, state processing → DocumentStateError; nothing removed; kept == []


def test_a_failed_document_without_content_is_deleted_without_touching_storage() -> None:
    ...  # a failed document with content_id None → deleted; versions_deleted == []


def test_an_archived_document_can_be_deleted() -> None: ...


def test_the_state_is_checked_again_under_the_lock() -> None:
    # The unlocked read sees failed; a retry makes it processing before the locked read.
    # Wrap library.unit_of_work so the first get_readable returns the failed copy and the for_update one
    # returns the stored (processing) one: set library.state.documents[doc].state = PROCESSING after the
    # first get_readable call (monkeypatch the fake's get_readable). Expect DocumentStateError, nothing removed.


def test_storage_failing_after_the_commit_is_logged_and_the_rows_stay_deleted(caplog) -> None:
    class Failing(FakeObjectStore):
        def delete_all_versions(self, key: str) -> None:
            raise RuntimeError("S3 down")
    ...  # delete succeeds (no exception), document gone, caplog has an ERROR record naming both keys
```

Fill each `...` with the same arrange as the first test; the assertions are spelled out in the comments.

- [ ] **Step 2: Run** `uv run pytest tests/unit/knowledge/test_delete_service.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement** `delete_service.py`:

```python
"""Delete a document for good (PRD §8 US-10c, §9.5): its rows, chunks, and every version of its files."""

import logging
from collections.abc import Callable

from smart_tutor.knowledge.domain.content import pages_key
from smart_tutor.knowledge.domain.errors import DocumentNotFoundError
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectStore
from smart_tutor.shared.domain.ids import DocumentId, UserId

logger = logging.getLogger(__name__)

KeepTitle = Callable[[UserId, DocumentId, str], None]


class DeleteService:
    """`keep_title` copies the display title into the learner's threads (tutoring) before this commits."""

    def __init__(self, uow: Callable[[], LibraryUnitOfWork], objects: ObjectStore, keep_title: KeepTitle) -> None:
        self._uow, self._objects, self._keep_title = uow, objects, keep_title

    def delete(self, user_id: UserId, document_id: DocumentId) -> None:
        """Raises DocumentNotFoundError (missing or not the caller's) and DocumentStateError (processing)."""
        keys: list[str] = []
        with self._uow() as tx:
            seen = tx.documents.get_readable(user_id, document_id)
            if seen is None:
                raise DocumentNotFoundError("Document not found")
            # The retry's lock order: content, then document; the state is checked again under the lock.
            content = tx.contents.get_for_update(seen.content_id) if seen.content_id is not None else None
            document = tx.documents.get_readable(user_id, document_id, for_update=True)
            if document is None:
                raise DocumentNotFoundError("Document not found")
            document.check_deletable()
            self._keep_title(user_id, document_id, document.title)
            tx.documents.remove(document_id)
            if content is not None and tx.documents.get_by_content(content.content_id) is None:
                tx.chunks.remove_for_content(content.content_id)
                tx.contents.remove(content.content_id)
                keys = [content.s3_key, pages_key(content.owner_id, content.content_id)]
            tx.commit()
        for key in keys:
            try:
                self._objects.delete_all_versions(key)
            except Exception:
                logger.exception("Document %s deleted, but its file %s is still stored", document_id, key)
```

(Check `Content`'s field names — `s3_key`, `owner_id`, `content_id` — in `knowledge/domain/content.py` and adjust if different. If the in-memory fake's `get_readable(..., for_update=True)` returns a copy, removal by id still works.)

- [ ] **Step 4: Run** tests → PASS; full checks.

- [ ] **Step 5: README.** In `knowledge/README.md` add `DeleteService` (`delete`) to the services list and this sentence to Rules after the `ArchiveService` sentence: "`DeleteService.delete` refuses only a `processing` document (`Document.check_deletable`, API 409); it reads the document, locks its content, then the document (the retry's order) and checks again, calls `keep_title` (tutoring copies the display title into the learner's `thread_documents` in its own transaction, so a failed delete leaves only a harmless copy), removes the document with its subjects, the content's chunks and the content, commits, then deletes every S3 version of `contents/<owner_id>/<content_id>.pdf` and `.pages.json`; a storage failure after the commit is logged."

- [ ] **Step 6: Commit** "Delete a document with its content, chunks, and file versions".

---

### Task 4: `DELETE /documents/{id}`, wiring, isolation, CDK

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/services.py` (`ApiServices.deletion`)
- Modify: `backend/src/smart_tutor/apps/api/deps.py` (`Deletion` dependency)
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py` (route; module docstring mentions delete)
- Modify: `backend/tests/fakes/api.py` (`"deletion": DeleteService(library.unit_of_work, objects, conversations.keep_deleted_title)` — reuse the `ConversationService` the fake already builds; if it builds it inline, hoist it into a local first)
- Modify: `infra/smart_tutor_infra/stacks/cluster.py`, `infra/tests/test_synth.py`
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`
- Test: `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/isolation/test_documents.py`

**Interfaces:**
- Consumes: Task 2 `ConversationService.keep_deleted_title`, Task 3 `DeleteService`.
- Produces: route `DELETE /documents/{document_id}`, `operation_id="delete_document"`, `204`; `404 {"detail": "Document not found"}`; `409 {"detail": "This document is still processing"}`; generated web SDK function `deleteDocument`.

- [ ] **Step 1: Failing route tests** in `test_knowledge_routes.py` (follow the file's client/setup pattern):

```python
def test_delete_answers_204_and_the_document_leaves_both_lists() -> None: ...
    # ready doc → DELETE 204 (empty body) → GET /documents and GET /documents?archived=true don't list it
def test_delete_of_a_processing_document_is_409() -> None: ...
def test_delete_of_an_unknown_document_is_404() -> None: ...
def test_a_deleted_documents_subject_leaves_my_subjects_unless_another_document_has_it() -> None: ...
    # two ready docs share subject S, one also has T; delete that one → GET /me/subjects (the route used by
    # existing "my subjects" tests) lists S, not T
```

- [ ] **Step 2: Failing isolation tests** in `tests/isolation/test_documents.py` (its `setup()` gives A/B clients, fake store, ingestion; extend `setup` to return the `InMemoryLibrary` and `InMemoryThreads` if needed):

```python
def test_b_cant_delete_as_document_and_as_copy_of_the_same_file_is_untouched() -> None:
    # A and B each upload the same bytes; both ingested (two contents, ADR 0011).
    # B: DELETE A's id → 404; A's document still listed.
    # A: DELETE own id → 204. Then for A's content: no document, content, chunks; versions_deleted holds A's two keys.
    # B's document, content, chunks, and S3 objects remain; B's GET /documents lists it.


def test_after_a_delete_as_conversation_lists_it_as_deleted() -> None:
    # A asks (or record_answer through the fakes) so a thread uses the document; A deletes it;
    # GET /threads/{id}/documents → [{"title": <its title>, "deleted": true, ...}]; B gets 404 for that thread.
```

- [ ] **Step 3: Run** → FAIL. **Implement** route:

```python
@router.delete(
    "/documents/{document_id}", operation_id="delete_document", status_code=status.HTTP_204_NO_CONTENT
)
def delete_document(document_id: UUID, principal: CurrentPrincipal, deletion: Deletion) -> None:
    """Delete the caller's document for good: its PDF, page text, and chunks (PRD §8 US-10c).

    Refused while processing (409). Conversations keep their text and list it as deleted.
    """
    try:
        deletion.delete(principal.user_id, DocumentId(str(document_id)))
    except DocumentNotFoundError:
        raise HTTPException(404, "Document not found") from None
    except DocumentStateError as e:
        raise HTTPException(409, str(e)) from None
```

`deps.py`: `_deletion(request) -> DeleteService` like `_archive`, `Deletion = Annotated[DeleteService, Depends(_deletion)]`, add to `__all__`. `services.py`: build `conversations = ConversationService(...)` before `ApiServices(...)`, then `deletion=DeleteService(library, objects, conversations.keep_deleted_title)`.

- [ ] **Step 4: Run** backend checks → PASS. Regenerate the client (`Makefile` target `api-client`).

- [ ] **Step 5: CDK.** In the API pod identity (`cluster.py`) add, and update its comment ("…and deletes a document's files, every version"):

```python
                    iam.PolicyStatement(
                        actions=["s3:ListBucketVersions"],
                        resources=[bucket_arn],
                        conditions={"StringLike": {"s3:prefix": ["contents/*"]}},
                    ),
                    iam.PolicyStatement(actions=["s3:DeleteObjectVersion"], resources=[f"{bucket_arn}/contents/*"]),
```

In `infra/tests/test_synth.py`, next to the existing API assertions (line ~547): `assert "contents/*" in api["s3:DeleteObjectVersion"]` and `"uploads/" not in api["s3:DeleteObjectVersion"]`, and that `s3:ListBucketVersions` is present. Run `cd infra && uv run pytest`.

- [ ] **Step 6: Commit** "Add DELETE /documents/{id} and let the API delete file versions".

---

### Task 5: Web — delete from the Library

**Files:**
- Modify: `web/src/api/documents.ts` (+ `documents.test.ts`): `deleteDocument(id)`
- Modify: `web/src/components/Button/Button.tsx`, `Button.module.css`: `variant="danger"`
- Modify: `web/src/components/Dialog/Dialog.tsx`: `title: ReactNode`
- Modify: `web/src/components/PageHeader/PageHeader.tsx`: optional `headingRef` (h1 gets `tabIndex={-1}` when given)
- Modify: `web/src/components/RowMenu/RowMenu.tsx`, `.module.css`: a separator before the first `danger` item
- Create: `web/src/features/library/DeleteDialog.tsx`, `DeleteDialog.module.css`, `DeleteDialog.test.tsx`
- Modify: `web/src/features/library/DocumentTable.tsx` (+ test), `LibraryPage.tsx` (+ test)

**Interfaces:**
- Consumes: generated `deleteDocument` (Task 4).
- Produces: `deleteDocument(documentId: string, apiClient?: Client): Promise<void>` (throws `SessionExpiredError` on 401 like its neighbours, `Error` otherwise); `DocumentTable` prop `onDelete?: (doc: DocumentResponse) => void`; `LibraryPage` prop `remove?: (documentId: string) => Promise<void>`.

- [ ] **Step 1: API wrapper test + impl**, mirroring `archiveDocument` in `documents.ts`/`documents.test.ts` (204 → resolves; 404/409 → throws; 401 → `SessionExpiredError`).

- [ ] **Step 2: Component tests first.**
  - `Button`: `variant="danger"` renders class `danger`. CSS: `.danger { background: var(--danger); color: var(--surface); border-color: var(--danger); } .danger:hover:not(:disabled) { filter: brightness(0.92); }` — match the structure of the existing `.primary` rules.
  - `RowMenu`: an item with `danger: true` gets a `role="separator"` before it (not focusable, skipped by Arrow keys).
  - `PageHeader`: with `headingRef`, the h1 has `tabindex="-1"` and the ref points at it.
  - `DeleteDialog.test.tsx`:

```tsx
it("asks to confirm with Cancel focused, and offers Archive instead for an active document", () => {
  render(<DeleteDialog doc={doc({ title: "Chain-of-Thought Prompting" })} onCancel={vi.fn()} onDelete={vi.fn()} onArchive={vi.fn()} />);
  expect(screen.getByRole("dialog", { name: "Delete Chain-of-Thought Prompting?" })).toBeInTheDocument();
  expect(screen.getByText("This can't be undone. Conversations and notes keep their text.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
  expect(screen.getByRole("button", { name: "Archive instead" })).toBeInTheDocument();
});
it("has no Archive instead for an archived document", ...);
it("calls onDelete, onArchive, onCancel from Delete, Archive instead, Cancel and Escape", ...);
it("disables both actions while deleting", ...);  // prop busy
```

- [ ] **Step 3: Implement `DeleteDialog`:**

```tsx
type Props = { doc: DocumentResponse; busy?: boolean; onCancel: () => void; onDelete: () => void; onArchive: () => void };

// US-10c: Cancel is focused first; Delete is the danger action; an active document can be archived instead.
export function DeleteDialog({ doc, busy = false, onCancel, onDelete, onArchive }: Props) {
  return (
    <Dialog
      title={<>Delete <em>{doc.title}</em>?</>}
      onClose={onCancel}
      footer={
        <>
          <Button data-autofocus onClick={onCancel}>Cancel</Button>
          <Button variant="danger" icon={Trash2} disabled={busy} onClick={onDelete}>Delete</Button>
        </>
      }
    >
      <p>This can't be undone. Conversations and notes keep their text.</p>
      {!doc.archived && (
        <div className={styles.alternative}>
          <p>Archive hides it and can be undone.</p>
          <Button size="sm" icon={Archive} disabled={busy} onClick={onArchive}>Archive instead</Button>
        </div>
      )}
    </Dialog>
  );
}
```

`Dialog`: change `title: string` to `title: ReactNode` (the h2 already renders it; `aria-labelledby` keeps the accessible name as text). Check `Button` forwards `data-autofocus` through `...rest`.

- [ ] **Step 4: `DocumentTable`.** Test: a ready row's More menu lists "Archive" then "Delete…"; a processing row's menu has no "Delete…"; an archived row shows Restore and a More menu with "Delete…" only; selecting it calls `onDelete(doc)`. Implement: active rows `items = [Archive, ...(doc.state !== "processing" && onDelete ? [{ label: "Delete…", icon: Trash2, danger: true, onSelect: () => onDelete(doc) }] : [])]` (keep the `!uploading` guard on the whole menu); archived rows render Restore plus `<RowMenu label={`More actions for ${doc.title}`} items={[deleteItem]} />` when `onDelete`.

- [ ] **Step 5: `LibraryPage`.** Tests (inject `remove`, `archive`, `load`):
  - Delete… → dialog → Delete calls `remove(id)`, closes the dialog, refreshes, the row is gone, focus is on the "Library" heading, and the status region reads "Chain-of-Thought Prompting deleted."
  - Cancel → no call, dialog closes, focus returns to the More button.
  - Archive instead → calls `archive(id)` (reuse `changeArchived(doc, true)`), dialog closes.
  - `remove` rejecting with an Error → dialog stays open, status "Couldn't delete *title*. Try again."; `SessionExpiredError` → no message (same as archive).
  Implement: `const [deleting, setDeleting] = useState<DocumentResponse | null>(null)`, `deleteBusy` flag, `headingRef = useRef<HTMLHeadingElement>(null)` passed to `PageHeader`; on success `setDeleting(null); setStatus(`${doc.title} deleted.`); refresh(); headingRef.current?.focus()` — focus after the dialog unmounts (the Dialog's cleanup restores focus to the old element, so focus the heading in a `setTimeout(…, 0)` or a `useEffect` keyed on a "just deleted" flag; the test pins the final focus).

- [ ] **Step 6: Run** `cd web && npx vitest run && npm run build` → PASS. Look at both themes against `library-delete-confirm` and `library-more-menu` shots.

- [ ] **Step 7: Commit** "Delete a document from the Library's More menu".

---

### Task 6: Web — deleted documents in conversations

**Files:**
- Modify: `web/src/features/chat/ChatPage.tsx` (+ test), `ChatPage.module.css`
- Modify: `web/src/features/chat/ConversationPanel.tsx` (+ test), `ConversationPanel.module.css`

**Interfaces:**
- Consumes: `ThreadDocumentResponse.deleted` (exists), `ChatCitation.document_id` (exists).

- [ ] **Step 1: Failing tests.**
  - `ConversationPanel.test.tsx`: a deleted row has a "Deleted" badge containing an svg icon, the row is not a link/button, and "Deleted documents can't be opened." appears exactly once when two are deleted; absent when none are deleted. The row exposes "Deleted: " to screen readers (visually hidden prefix, as the prototype does).
  - `ChatPage.test.tsx`: the answer cites d1 and d2; after the stream, `loadUsed` returns d2 with `deleted: true`; the Sources list shows "Deleted document" for d2's citation (with its [n] marker, no page and no title of d2), and d1's citation unchanged.

- [ ] **Step 2: Implement.**
  - Panel: badge `<span className={styles.badge}><X className={styles.badgeIcon} strokeWidth={1.5} aria-hidden="true" />Deleted</span>`; prefix `<span className="visually-hidden">Deleted: </span>` inside deleted rows; after the `<ul>`, `{documents.some((d) => d.deleted) && <p className={styles.note}><Info … aria-hidden="true" />Deleted documents can't be opened.</p>}`. `.gone` stays muted but readable (`--text-2`), badge muted (same tokens as archived).
  - ChatPage: keep the loaded documents used in state (it already loads them for the panel); `const deletedIds = new Set(used.filter((d) => d.deleted).map((d) => d.document_id))`; in Sources, a citation whose `document_id` is in `deletedIds` renders `[n] Deleted document` with class `sourceDeleted` (muted, no page, `title` "Deleted document").

- [ ] **Step 3: Run** web tests and build → PASS; compare with `chat-citation-deleted` and `chat-documents-used-deleted` in both themes.

- [ ] **Step 4: Commit** "Show deleted documents in conversations".

---

### Task 7: PRD

**Files:**
- Modify: `sdd/prd.md` (status line v2.26 → v2.27; new "Changes from v2.26" row)

- [ ] **Step 1:** Add the row: "Delete a document (#125, US-10c): `DELETE /documents/{id}` answers `204`, `404 "Document not found"` for a missing document or another learner's, `409` while processing. The display title is copied into the learner's `thread_documents.deleted_title` before the delete commits (tutoring's own transaction), then the document, its subjects, content, and chunks are removed and every S3 version of the PDF and page text is deleted after the commit (the API role gains `s3:ListBucketVersions` on `contents/*` and `s3:DeleteObjectVersion`). Delete is in the Library row's More menu (active and archived rows, not while processing); the details panel (#109) and Usage (#18) add theirs when they are built." Bump the status line to v2.27. In §9.5's Delete row, change nothing else (it already matches).
- [ ] **Step 2:** Update the AGENTS.md table's PRD version if it names one (`sdd/prd.md` (v2.26) → v2.27).
- [ ] **Step 3: Commit** "Document deleting a document (PRD v2.27)".

# Retry a Failed Document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A failed document's Library row has **Retry**, which reprocesses the stored content (up to 3 attempts in total, counted on the shared content); after the third failure the row says "This file could not be processed" and has no Retry (issue #63).

**Architecture:** `Content.retry(max_attempts)` and `Document.retry()` are the state rules. `RetryService` (knowledge) locks the document and content, moves content and every failed document linked to it back to `processing`, and sends a `{"retry_content_id": …}` message to the existing ingest queue **before committing, while it holds the content's row lock**. The worker's `process_content` reads the content with `get_for_update`, so it waits for that commit and never sees the pre-retry state. The listing adds `attempt`, `max_attempts`, and `can_retry`. The limit comes from SSM `/smart-tutor/max-processing-attempts` (3).

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy Core / SQS (boto3), React + TypeScript + Vitest, AWS CDK (Python).

**Spec:** GitHub issue #63; PRD `sdd/prd.md` §8 US-2 (third criterion), §9.5 (content and document states), §9.12 Settings row ("retry attempts (3)"). Mockups: round v0.4, states `library-failed`, `library-retry-processing`.

## Global Constraints

- Up to **3 attempts in total** per content, from settings (SSM `/smart-tutor/max-processing-attempts`, value `3`); the first upload is attempt 1.
- Exhausted copy, verbatim: `This file could not be processed`.
- Retry reprocesses from the stored `contents/<sha256>.pdf`; no new upload.
- Only the owner can retry (`can_read`); anyone else gets **404** (never reveal that the document exists).
- Retrying a document that isn't failed (or whose content isn't failed) changes nothing and returns 204.
- A fourth attempt is refused with **409**.
- Module rules (`backend/AGENTS.md`): domain rules on domain classes; use case in `knowledge/application`; routes/handlers in `apps/`; vendor SDKs only in adapters; `PYTHONUTF8=1 uv run lint-imports` must pass.
- Web: API calls only through `web/src/api/`; UI from `web/src/components/` and design tokens (read `DESIGN.md`); never paste prototype HTML/CSS.
- Out of scope: retry by re-uploading (US-11, #21); Retry on Document details (US-10, #19).

## Review Focus

1. Double-click / two tabs: two retries race on one failed content → exactly one attempt is consumed, the second is a no-op (row lock + "not failed → nothing"). Pinned in Task 2 (`test_a_second_retry_while_processing_changes_nothing`).
2. Worker receives the retry message before the API commits → it must wait, not drop the message. Pinned in Task 2 by asserting `process_content` uses `get_for_update` (fake records lock calls).
3. A failed document with no content (the "Duplicate uploads aren't supported yet" failure) → no Retry button and the API does nothing (204). Pinned in Task 2 and Task 4.
4. Queue send fails → nothing is committed (attempt not consumed, document stays failed, learner can try again). Pinned in Task 2 (`test_a_failed_send_commits_nothing`).
5. A malformed `document_id` in the URL → 422, not 500. Pinned in Task 3.

---

### Task 1: Retry rules on Content and Document

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/domain/content.py`
- Modify: `backend/src/smart_tutor/knowledge/domain/document.py`
- Modify: `backend/src/smart_tutor/knowledge/domain/errors.py`
- Test: `backend/tests/unit/knowledge/test_domain.py`

**Interfaces:**
- Produces: `RETRIES_USED_UP = "This file could not be processed"` (content.py); `Content.retry(max_attempts: int) -> None`; `Content.can_retry(max_attempts: int) -> bool`; `Document.retry() -> None`; `Document.content_attempts: int | None = None` (filled by listings, never saved, like `content_title`); `RetryLimitError(DomainError)`, `DocumentNotFoundError(DomainError)` in errors.py.

- [ ] **Step 1: Write the failing tests** (append to `test_domain.py`; reuse its existing helpers/imports for building a `Content` and a `Document` — read the file first)

```python
def test_retry_puts_failed_content_back_to_processing_and_counts_the_attempt() -> None:
    content = Content.first_upload(ContentId("c1"), "a" * 64, 10, UserId("ada"))
    content.fail("This file isn't a readable PDF")
    content.retry(max_attempts=3)
    assert (content.state, content.attempts, content.failure_reason) == (ContentState.PROCESSING, 2, None)


def test_retry_is_refused_once_the_attempts_are_used_up() -> None:
    content = Content.first_upload(ContentId("c1"), "a" * 64, 10, UserId("ada"))
    for _ in range(2):
        content.fail("x")
        content.retry(max_attempts=3)
    content.fail("x")
    assert content.attempts == 3 and not content.can_retry(3)
    with pytest.raises(RetryLimitError, match="This file could not be processed"):
        content.retry(max_attempts=3)
    assert content.state is ContentState.FAILED


def test_only_failed_content_can_retry() -> None:
    content = Content.first_upload(ContentId("c1"), "a" * 64, 10, UserId("ada"))
    assert not content.can_retry(3)
    with pytest.raises(ContentStateError):
        content.retry(max_attempts=3)


def test_document_retry_returns_a_failed_document_to_processing() -> None:
    doc = Document.start_upload(DocumentId("d1"), UserId("ada"), UploadId("u1"), "a.pdf", NOW)
    doc.link_content(ContentId("c1"))
    doc.fail("This file isn't a readable PDF")
    doc.retry()
    assert (doc.state, doc.failure_reason) == (DocumentState.PROCESSING, None)


def test_only_a_failed_document_with_content_can_retry() -> None:
    doc = Document.start_upload(DocumentId("d1"), UserId("ada"), UploadId("u1"), "a.pdf", NOW)
    with pytest.raises(DocumentStateError):
        doc.retry()  # processing
    doc.fail("Duplicate uploads aren't supported yet")  # failed, but no content
    with pytest.raises(DocumentStateError):
        doc.retry()
```

(`NOW` = any timezone-aware datetime; define it if the file has none.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/unit/knowledge/test_domain.py -q`
Expected: FAIL (`retry` / `RetryLimitError` not defined).

- [ ] **Step 3: Implement**

errors.py:

```python
class RetryLimitError(DomainError):
    """The content used all its processing attempts (PRD §9.5)."""


class DocumentNotFoundError(DomainError):
    """No such document for this learner; entrypoints answer 404 whether it is missing or someone else's."""
```

content.py (constant next to the other messages; methods on `Content` after `fail`):

```python
RETRIES_USED_UP = "This file could not be processed"

    def can_retry(self, max_attempts: int) -> bool:
        return self.state is ContentState.FAILED and self.attempts < max_attempts

    def retry(self, max_attempts: int) -> None:
        """failed → processing for another attempt (Retry or, with US-11, a re-upload); at most `max_attempts` in all."""
        if self.state is not ContentState.FAILED:
            raise ContentStateError("Only failed content can be retried")
        if self.attempts >= max_attempts:
            raise RetryLimitError(RETRIES_USED_UP)
        self.state, self.attempts, self.failure_reason = ContentState.PROCESSING, self.attempts + 1, None
```

document.py: add field `content_attempts: int | None = None  # contents.attempts, filled when listing; never saved` after `content_title`, and:

```python
    def retry(self) -> None:
        """failed → processing when its content is retried."""
        if self.state is not DocumentState.FAILED or self.content_id is None:
            raise DocumentStateError("Only a failed document with content can be retried")
        self.state, self.failure_reason = DocumentState.PROCESSING, None
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && uv run pytest tests/unit/knowledge -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/src/smart_tutor/knowledge/domain backend/tests/unit/knowledge/test_domain.py
git commit -m "Add retry rules to Content and Document"
```

---

### Task 2: RetryService, repositories, queue send, and the listing fields

**Files:**
- Create: `backend/src/smart_tutor/knowledge/application/retry_service.py`
- Modify: `backend/src/smart_tutor/knowledge/application/__init__.py` (export `RetryService`, `retry_message`, `retried_content`, `load_max_attempts`, `DocumentNotFoundError`, `RetryLimitError`)
- Modify: `backend/src/smart_tutor/knowledge/application/limits.py` (add `load_max_attempts`)
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py`
- Modify: `backend/src/smart_tutor/knowledge/application/ingestion_service.py` (first read in `process_content` → `get_for_update`)
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py`
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py`
- Modify: `backend/src/smart_tutor/shared/ports/message_queue.py` (add `send`)
- Modify: `backend/src/smart_tutor/shared/adapters/aws/sqs_queue.py` (implement `send`)
- Modify: `backend/tests/fakes/knowledge.py`, `backend/tests/fakes/queue.py`
- Modify: every existing `DocumentService(...)` construction in tests (now needs `max_attempts`): `grep -rn "DocumentService(" backend/tests`
- Test: `backend/tests/unit/knowledge/test_retry_service.py` (new), `backend/tests/unit/knowledge/test_document_service.py`, `backend/tests/unit/knowledge/test_limits.py`, `backend/tests/integration/knowledge/test_sql_library.py`

**Interfaces:**
- Consumes (Task 1): `Content.retry`, `Content.can_retry`, `Document.retry`, `Document.content_attempts`, `RETRIES_USED_UP`, `RetryLimitError`, `DocumentNotFoundError`.
- Produces:
  - `MessageQueue.send(self, body: str) -> None` (abstract); `SqsMessageQueue.send` → `send_message(QueueUrl=…, MessageBody=body)`; `FakeQueue.send` appends `QueueMessage(f"s{n}", body)` to `self.sent` (and to `waiting`, so a worker test can receive it); `FakeQueue(fail_send=True)` raises `RuntimeError("queue down")` from `send`.
  - `DocumentRepository.get_for_update(document_id: DocumentId) -> Document | None`; `DocumentRepository.list_failed_for_content_for_update(content_id: ContentId) -> list[Document]`.
  - `list_readable_by` fills `content_attempts` (SQL: `contents.c.attempts.label("content_attempts")`; fake: from the content).
  - `ContentRepository.save` also writes `attempts`.
  - `retry_message(content_id: ContentId) -> str` → `json.dumps({"retry_content_id": content_id})`; `retried_content(body: str) -> ContentId | None` (None for anything else, including bad JSON and non-string ids).
  - `RetryService(uow: Callable[[], LibraryUnitOfWork], queue: MessageQueue, max_attempts: int)`; `.retry(user_id: UserId, document_id: DocumentId) -> None`, raises `DocumentNotFoundError`, `RetryLimitError`.
  - `DocumentService(uow, max_attempts: int)`; `DocumentView` gains `attempt: int | None`, `max_attempts: int`, `can_retry: bool`; for a failed document whose content used all attempts, `failure_reason` is `RETRIES_USED_UP`.
  - `load_max_attempts(store: ParameterStore, param: str) -> int` (positive whole number, same validation as file limits).

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/knowledge/test_retry_service.py`:

```python
import pytest

from fakes import TEST_LIMITS, FakeObjectStore, FakeQueue, FixedClock, InMemoryLibrary, fake_tools
from smart_tutor.knowledge.application import (
    DocumentNotFoundError,
    DocumentService,
    IngestionService,
    RetryLimitError,
    RetryService,
    UploadService,
    retried_content,
    retry_message,
)
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UserId

ADA = UserId("ada")
SCAN = b"%PDF-1.7 tiny"  # fake extractor: too little text → "No text layer"


def failed_upload(data: bytes = SCAN) -> tuple[InMemoryLibrary, FakeObjectStore, IngestionService, DocumentId]:
    """Ada's document, failed after its first attempt."""
    library, objects = InMemoryLibrary(), FakeObjectStore()
    started = UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS).start_upload(ADA, "scan.pdf")
    objects.objects[started.fields["key"]] = data
    ingestion = IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS)
    ingestion.ingest_upload(started.fields["key"])
    assert library.state.documents[started.document_id].state.value == "failed"
    return library, objects, ingestion, started.document_id


def test_retry_returns_document_and_content_to_processing_and_queues_the_content() -> None:
    library, _, _, doc_id = failed_upload()
    queue = FakeQueue()
    RetryService(library.unit_of_work, queue, max_attempts=3).retry(ADA, doc_id)

    doc = library.state.documents[doc_id]
    content = library.state.contents[doc.content_id]  # type: ignore[index]
    assert (doc.state.value, doc.failure_reason) == ("processing", None)
    assert (content.state.value, content.attempts) == ("processing", 2)
    assert [retried_content(m.body) for m in queue.sent] == [content.content_id]
    [view] = DocumentService(library.unit_of_work, max_attempts=3).list_documents(ADA)
    assert (view.state, view.attempt, view.max_attempts, view.can_retry) == ("processing", 2, 3, False)


def test_the_queued_retry_reprocesses_the_stored_file() -> None:
    library, objects, ingestion, doc_id = failed_upload()
    queue = FakeQueue()
    RetryService(library.unit_of_work, queue, max_attempts=3).retry(ADA, doc_id)
    content_id = retried_content(queue.sent[0].body)
    assert content_id is not None
    ingestion.process_content(content_id)  # same bytes → fails again, attempt 2
    [view] = DocumentService(library.unit_of_work, max_attempts=3).list_documents(ADA)
    assert (view.state, view.attempt, view.can_retry) == ("failed", 2, True)


def test_after_three_failed_attempts_there_is_no_retry() -> None:
    library, _, ingestion, doc_id = failed_upload()
    retries = RetryService(library.unit_of_work, FakeQueue(), max_attempts=3)
    for _ in range(2):
        retries.retry(ADA, doc_id)
        ingestion.process_content(library.state.documents[doc_id].content_id)  # type: ignore[arg-type]
    [view] = DocumentService(library.unit_of_work, max_attempts=3).list_documents(ADA)
    assert (view.state, view.attempt, view.can_retry) == ("failed", 3, False)
    assert view.failure_reason == "This file could not be processed"
    with pytest.raises(RetryLimitError):
        retries.retry(ADA, doc_id)
    assert library.state.documents[doc_id].state.value == "failed"


def test_a_second_retry_while_processing_changes_nothing() -> None:
    library, _, _, doc_id = failed_upload()
    queue = FakeQueue()
    retries = RetryService(library.unit_of_work, queue, max_attempts=3)
    retries.retry(ADA, doc_id)
    retries.retry(ADA, doc_id)
    content = library.state.contents[library.state.documents[doc_id].content_id]  # type: ignore[index]
    assert content.attempts == 2 and len(queue.sent) == 1


def test_a_failed_document_without_content_is_left_alone() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    uploads = UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS)
    ingestion = IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS)
    for name in ("a.pdf", "copy.pdf"):  # the second is a duplicate: failed with no content
        started = uploads.start_upload(ADA, name)
        objects.objects[started.fields["key"]] = SCAN
        ingestion.ingest_upload(started.fields["key"])
    duplicate = started.document_id
    queue = FakeQueue()
    RetryService(library.unit_of_work, queue, max_attempts=3).retry(ADA, duplicate)
    assert library.state.documents[duplicate].failure_reason == "Duplicate uploads aren't supported yet"
    assert queue.sent == []
    views = DocumentService(library.unit_of_work, max_attempts=3).list_documents(ADA)
    assert next(v for v in views if v.document_id == duplicate).can_retry is False


def test_another_learner_cannot_retry_and_learns_nothing() -> None:
    library, _, _, doc_id = failed_upload()
    queue = FakeQueue()
    retries = RetryService(library.unit_of_work, queue, max_attempts=3)
    with pytest.raises(DocumentNotFoundError):
        retries.retry(UserId("bob"), doc_id)
    with pytest.raises(DocumentNotFoundError):
        retries.retry(ADA, DocumentId("00000000-0000-4000-8000-00000000dead"))
    assert library.state.documents[doc_id].state.value == "failed" and queue.sent == []


def test_a_failed_send_commits_nothing() -> None:
    library, _, _, doc_id = failed_upload()
    with pytest.raises(RuntimeError):
        RetryService(library.unit_of_work, FakeQueue(fail_send=True), max_attempts=3).retry(ADA, doc_id)
    content = library.state.contents[library.state.documents[doc_id].content_id]  # type: ignore[index]
    assert (library.state.documents[doc_id].state.value, content.attempts) == ("failed", 1)


def test_retry_messages_round_trip_and_reject_anything_else() -> None:
    assert retried_content(retry_message(ContentId("c1"))) == "c1"
    for body in ("not json", "[]", '{"Records": []}', '{"retry_content_id": 5}', '{"retry_content_id": ""}'):
        assert retried_content(body) is None


def test_processing_waits_for_a_retry_commit_by_locking_the_content() -> None:
    library, _, ingestion, doc_id = failed_upload()
    RetryService(library.unit_of_work, FakeQueue(), max_attempts=3).retry(ADA, doc_id)
    library.locked_contents.clear()
    ingestion.process_content(library.state.documents[doc_id].content_id)  # type: ignore[arg-type]
    assert library.locked_contents  # the first read is get_for_update, so it waits for the API's commit
```

Notes for the implementer: check `fakes/processing.py` to confirm `SCAN` fails with "No text layer" under `fake_tools()` (adjust the bytes if the fake extractor needs otherwise). Add `self.locked_contents: list[str] = []` to `InMemoryLibrary` and have the fake `_Contents.get_for_update` append the id (the fake `_Contents` needs a reference to the library for that — pass it in through `FakeLibraryUnitOfWork`).

Also add to `test_limits.py`:

```python
def test_max_attempts_comes_from_ssm_and_must_be_positive() -> None:
    assert load_max_attempts(FakeParameterStore({"/a": "3"}), "/a") == 3
    for bad in ("0", "-1", "three", ""):
        with pytest.raises(ValueError):
            load_max_attempts(FakeParameterStore({"/a": bad}), "/a")
```

And to `tests/integration/knowledge/test_sql_library.py` (follow its existing fixtures and helpers — read it first) a test that: inserts a content, fails it, `save`s, reloads and checks `attempts` round-trips after `retry`; `get_for_update` finds a document by id and returns None for an unknown id; `list_failed_for_content_for_update` returns only failed documents of that content; `list_readable_by` sets `content_attempts`.

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/unit/knowledge -q`
Expected: FAIL (imports missing).

- [ ] **Step 3: Implement**

`shared/ports/message_queue.py` — add to `MessageQueue`:

```python
    @abstractmethod
    def send(self, body: str) -> None:
        """Add a message at the back of the queue."""
```

`shared/adapters/aws/sqs_queue.py`:

```python
    def send(self, body: str) -> None:
        self._client.send_message(QueueUrl=self._url, MessageBody=body)
```

`tests/fakes/queue.py`:

```python
class FakeQueue(MessageQueue):
    def __init__(self, *bodies: str, fail_send: bool = False) -> None:
        self.waiting = [QueueMessage(f"r{i}", body) for i, body in enumerate(bodies)]
        self.deleted: list[QueueMessage] = []
        self.sent: list[QueueMessage] = []
        self._fail_send = fail_send

    def send(self, body: str) -> None:
        if self._fail_send:
            raise RuntimeError("queue down")
        message = QueueMessage(f"s{len(self.sent)}", body)
        self.sent.append(message)
        self.waiting.append(message)
```

`knowledge/ports/library.py` — on `DocumentRepository`:

```python
    @abstractmethod
    def get_for_update(self, document_id: DocumentId) -> Document | None:
        """The document, locked until the unit of work ends (no access check: callers apply `can_read`)."""

    @abstractmethod
    def list_failed_for_content_for_update(self, content_id: ContentId) -> list[Document]:
        """Every failed document linked to this content, locked until the unit of work ends."""
```

and update `ContentRepository.save`'s docstring to mention `attempts`.

`sql_library.py`: `_Contents.save` adds `attempts=content.attempts`; `_document` adds `content_attempts=getattr(row, "content_attempts", None)`; `list_readable_by` selects `contents.c.attempts.label("content_attempts")` too; new methods:

```python
    def get_for_update(self, document_id: DocumentId) -> Document | None:
        row = self._conn.execute(
            select(documents).where(documents.c.document_id == document_id).with_for_update()
        ).first()
        return self._load([row])[0] if row else None

    def list_failed_for_content_for_update(self, content_id: ContentId) -> list[Document]:
        rows = self._conn.execute(
            select(documents)
            .where(documents.c.content_id == content_id, documents.c.state == DocumentState.FAILED.value)
            .order_by(documents.c.document_id)
            .with_for_update()
        ).all()
        return self._load(list(rows))
```

Fake `_Documents`: same two methods (deep copies), `list_readable_by` also sets `d.content_attempts = content.attempts if content else None`.

`knowledge/application/limits.py`:

```python
def load_max_attempts(store: ParameterStore, param: str) -> int:
    """Processing attempts per content, Retry and re-upload included (PRD §9.5)."""
    return _positive(store, param)
```

`knowledge/application/retry_service.py`:

```python
"""Retry a failed document: its shared content gets another processing attempt from the stored file (PRD §9.5).

The worker is woken by a message on the ingest queue. It is sent before the commit, while this transaction holds
the content's row lock; the worker's first read locks the content too, so it waits for the commit. If the commit
fails, the worker finds the content still failed and drops the message; nothing was used up.
"""

import json
from collections.abc import Callable

from smart_tutor.knowledge.domain.content import ContentState
from smart_tutor.knowledge.domain.document import DocumentState
from smart_tutor.knowledge.domain.errors import DocumentNotFoundError
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UserId
from smart_tutor.shared.ports.message_queue import MessageQueue

_KEY = "retry_content_id"


def retry_message(content_id: ContentId) -> str:
    return json.dumps({_KEY: content_id})


def retried_content(body: str) -> ContentId | None:
    """The content a retry message asks to process; None for any other message."""
    try:
        message = json.loads(body)
    except json.JSONDecodeError:
        return None
    value = message.get(_KEY) if isinstance(message, dict) else None
    return ContentId(value) if isinstance(value, str) and value else None


class RetryService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], queue: MessageQueue, max_attempts: int) -> None:
        self._uow, self._queue, self._max_attempts = uow, queue, max_attempts

    def retry(self, user_id: UserId, document_id: DocumentId) -> None:
        """Raises DocumentNotFoundError (missing or not the caller's) and RetryLimitError; anything not failed is left alone."""
        with self._uow() as tx:
            document = tx.documents.get_for_update(document_id)
            if document is None or not document.can_be_read_by(user_id):
                raise DocumentNotFoundError("Document not found")
            if document.state is not DocumentState.FAILED or document.content_id is None:
                return
            content = tx.contents.get_for_update(document.content_id)
            if content is None or content.state is not ContentState.FAILED:
                return
            content.retry(self._max_attempts)
            tx.contents.save(content)
            for linked in tx.documents.list_failed_for_content_for_update(content.content_id):
                linked.retry()
                tx.documents.save(linked)
            self._queue.send(retry_message(content.content_id))
            tx.commit()
```

`document_service.py`:

```python
@dataclass(frozen=True)
class DocumentView:
    document_id: DocumentId
    title: str
    state: DocumentStateName
    failure_reason: str | None
    created_at: datetime
    subject_ids: tuple[SubjectId, ...]
    attempt: int | None  # of the shared content; None until the upload is hashed
    max_attempts: int
    can_retry: bool


class DocumentService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], max_attempts: int) -> None:
        self._uow, self._max_attempts = uow, max_attempts

    def list_documents(self, user_id: UserId) -> list[DocumentView]:
        with self._uow() as tx:
            documents = tx.documents.list_readable_by(user_id)
        return [self._view(d) for d in documents]

    def _view(self, d: Document) -> DocumentView:
        failed = d.state is DocumentState.FAILED and d.content_attempts is not None
        used_up = failed and d.content_attempts >= self._max_attempts  # type: ignore[operator]
        return DocumentView(
            d.document_id,
            d.title,
            d.state.value,
            RETRIES_USED_UP if used_up else d.failure_reason,
            d.created_at,
            tuple(d.subject_ids),
            d.content_attempts,
            self._max_attempts,
            failed and not used_up,
        )
```

(Write `used_up` without the `type: ignore` if mypy narrows it; e.g. `attempts = d.content_attempts` then `failed = d.state is DocumentState.FAILED and attempts is not None` and `used_up = failed and attempts >= …` with an explicit `attempts is not None` check.)

`ingestion_service.py` `process_content`: change the first read to `content = tx.contents.get_for_update(content_id)` and extend the docstring: "The first read locks the content so a retry's message waits for the retry to commit."

Update every test that builds `DocumentService(library.unit_of_work)` to `DocumentService(library.unit_of_work, max_attempts=3)`; `apps/api/services.py` gets fixed in Task 3, but make it type-check now by passing `max_attempts=3` temporarily is **not** allowed — instead do Task 3's `services.py` change for `DocumentService` here (load `max_attempts` with `load_max_attempts(params, settings.max_processing_attempts_param)` and add that setting to `shared/config.py`: `max_processing_attempts_param: str = "/smart-tutor/max-processing-attempts"` with a comment `# Processing attempts per content (PRD §9.5), read once at startup by the API.`).

- [ ] **Step 4: Run to verify they pass**

Run: `cd backend && uv run pytest -q && uv run mypy && uv run ruff check . && uv run ruff format --check . && PYTHONUTF8=1 uv run lint-imports`
Then (Compose Postgres is up on 10400): `cd backend && uv run --env-file ../.env pytest -m integration tests/integration/knowledge/test_sql_library.py -q` (run `make migrate`-equivalent first if needed: see Makefile `migrate` target).
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add backend
git commit -m "Retry a failed content from its stored file and show attempts in the library"
```

---

### Task 3: API route, worker handling, settings, and isolation test

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py`
- Modify: `backend/src/smart_tutor/apps/api/deps.py`
- Modify: `backend/src/smart_tutor/apps/api/services.py`
- Modify: `backend/src/smart_tutor/apps/worker/main.py`
- Modify: `compose.yaml` (api service), `local/localstack/init/ready.d/10-smart-tutor.sh`, `infra/smart_tutor_infra/stacks/config.py`, `infra/tests/test_config_stack.py`
- Modify: `web/src/api/openapi.json` and `web/src/api/generated/*` (regenerated)
- Modify: `backend/src/smart_tutor/knowledge/README.md`
- Test: `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/unit/apps/worker/test_worker.py`, `backend/tests/isolation/test_documents.py`

**Interfaces:**
- Consumes (Task 2): `RetryService`, `retried_content`, `retry_message`, `load_max_attempts`, `DocumentNotFoundError`, `RetryLimitError`, `DocumentView.attempt/max_attempts/can_retry`, `MessageQueue.send`.
- Produces: `POST /documents/{document_id}/retry` (`operation_id="retry_document"`, 204; 404; 409 with detail `This file could not be processed`; 422 for a non-UUID id). `DocumentResponse` gains `attempt: int | None`, `max_attempts: int`, `can_retry: bool`. `ApiServices.retries: RetryService`. Generated web SDK function `retryDocument`.

- [ ] **Step 1: Write the failing tests**

In `test_knowledge_routes.py`, extend the fixture's `ApiServices(...)` with `retries=RetryService(library.unit_of_work, FakeQueue(), max_attempts=3)` and `documents=DocumentService(library.unit_of_work, max_attempts=3)`; store the queue on `app.state.queue`. Then add:

```python
SCAN = b"%PDF-1.7 tiny"  # fake extractor: no text layer → failed


def failed_document(client: TestClient) -> str:
    started = client.post("/uploads", json={"file_name": "scan.pdf"}, headers=AUTH).json()
    client.app.state.objects.objects[started["fields"]["key"]] = SCAN  # type: ignore[attr-defined]
    client.app.state.ingestion.ingest_upload(started["fields"]["key"])  # type: ignore[attr-defined]
    return str(started["document_id"])


def test_retry_returns_a_failed_document_to_processing_with_its_attempt(client: TestClient) -> None:
    doc_id = failed_document(client)
    [before] = client.get("/documents", headers=AUTH).json()
    assert (before["state"], before["attempt"], before["max_attempts"], before["can_retry"]) == ("failed", 1, 3, True)

    assert client.post(f"/documents/{doc_id}/retry", headers=AUTH).status_code == 204
    [after] = client.get("/documents", headers=AUTH).json()
    assert (after["state"], after["attempt"], after["can_retry"], after["failure_reason"]) == ("processing", 2, False, None)


def test_a_fourth_attempt_is_refused(client: TestClient) -> None:
    doc_id = failed_document(client)
    for _ in range(2):
        assert client.post(f"/documents/{doc_id}/retry", headers=AUTH).status_code == 204
        content_id = retried_content(client.app.state.queue.sent[-1].body)  # type: ignore[attr-defined]
        client.app.state.ingestion.process_content(content_id)  # type: ignore[attr-defined]
    [doc] = client.get("/documents", headers=AUTH).json()
    assert (doc["failure_reason"], doc["can_retry"]) == ("This file could not be processed", False)
    refused = client.post(f"/documents/{doc_id}/retry", headers=AUTH)
    assert (refused.status_code, refused.json()["detail"]) == (409, "This file could not be processed")


def test_retrying_a_document_that_is_not_failed_changes_nothing(client: TestClient) -> None:
    started = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH).json()
    assert client.post(f"/documents/{started['document_id']}/retry", headers=AUTH).status_code == 204
    [doc] = client.get("/documents", headers=AUTH).json()
    assert (doc["state"], doc["attempt"]) == ("processing", None)
    assert client.app.state.queue.sent == []  # type: ignore[attr-defined]


def test_retry_of_an_unknown_or_malformed_id(client: TestClient) -> None:
    assert client.post("/documents/00000000-0000-4000-8000-00000000dead/retry", headers=AUTH).status_code == 404
    assert client.post("/documents/not-a-uuid/retry", headers=AUTH).status_code == 422
    assert client.post("/documents/00000000-0000-4000-8000-00000000dead/retry").status_code == 401
```

Also add `assert paths["/documents/{document_id}/retry"]["post"]["operationId"] == "retry_document"` to `test_openapi_names_the_operations`.

In `isolation/test_documents.py`, give `setup()` a `FakeQueue` and the new services (`DocumentService(..., max_attempts=3)`, `retries=RetryService(library.unit_of_work, queue, max_attempts=3)`), and add:

```python
def test_b_cannot_retry_a_documents_processing() -> None:
    client, objects, ingestion = setup()
    started = client.post("/uploads", json={"file_name": "scan.pdf"}, headers=A).json()
    objects.objects[started["fields"]["key"]] = b"%PDF-1.7 tiny"
    ingestion.ingest_upload(started["fields"]["key"])

    response = client.post(f"/documents/{started['document_id']}/retry", headers=B)

    assert response.status_code == 404  # the same answer as for a document that doesn't exist
    [doc] = client.get("/documents", headers=A).json()
    assert (doc["state"], doc["attempt"]) == ("failed", 1)
```

In `test_worker.py`:

```python
def test_a_retry_message_reprocesses_the_content_and_is_deleted() -> None:
    library, objects, uploads, ingestion = world()
    started = uploads.start_upload(UserId("ada"), "scan.pdf")
    objects.objects[started.fields["key"]] = b"%PDF-1.7 tiny"
    ingestion.ingest_upload(started.fields["key"])
    queue = FakeQueue()
    RetryService(library.unit_of_work, queue, max_attempts=3).retry(UserId("ada"), started.document_id)
    objects.objects[library.state.contents[library.state.documents[started.document_id].content_id].s3_key] = PDF  # type: ignore[index]

    assert run_once(queue, ingestion) == 1
    assert queue.waiting == [] and len(queue.deleted) == 1
    assert library.state.documents[started.document_id].state.value == "ready"
```

In `infra/tests/test_config_stack.py`, add an assertion next to the existing one:

```python
    template.has_resource_properties("AWS::SSM::Parameter", {"Name": "/smart-tutor/max-processing-attempts", "Value": "3"})
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd backend && uv run pytest tests/unit/apps tests/isolation -q` and `cd infra && uv run pytest -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`routes/knowledge.py`: add to `DocumentResponse`:

```python
    attempt: int | None  # processing attempts of the shared content so far; null until the upload is hashed
    max_attempts: int
    can_retry: bool
```

fill them in `list_documents` from the view, and add:

```python
@router.post("/documents/{document_id}/retry", operation_id="retry_document", status_code=status.HTTP_204_NO_CONTENT)
def retry_document(document_id: UUID, principal: CurrentPrincipal, retries: Retries) -> None:
    """Process a failed document's stored file again (PRD §9.5); a document that isn't failed is left as it is."""
    try:
        retries.retry(principal.user_id, DocumentId(str(document_id)))
    except DocumentNotFoundError:
        raise HTTPException(404, "Document not found") from None
    except RetryLimitError as e:
        raise HTTPException(409, str(e)) from None
```

(`from uuid import UUID`; `DocumentId` from `smart_tutor.shared.domain.ids`; errors from `knowledge.application`.)

`deps.py`: `def _retries(request) -> RetryService: return _services(request).retries`; `Retries = Annotated[RetryService, Depends(_retries)]`.

`services.py`: `ApiServices` gets `retries: RetryService`; build `params = SsmParameterStore(ssm_client(settings))` once, `max_attempts = load_max_attempts(params, settings.max_processing_attempts_param)`, `queue = SqsMessageQueue(sqs_client(settings), settings.ingest_queue_url)`, `retries=RetryService(library, queue, max_attempts)`.

`apps/worker/main.py` `run_once`:

```python
def run_once(queue: MessageQueue, ingestion: IngestionService) -> int:
    messages = queue.receive()
    for message in messages:
        retried = retried_content(message.body)  # Retry from the Library (PRD §9.5)
        keys = [] if retried else upload_keys(message.body)
        try:
            if retried:
                ingestion.process_content(retried)
            for key in keys:
                ingestion.ingest_upload(key)
        except Exception:
            logger.exception("ingestion failed for %s; the message will be redelivered", retried or keys)
            continue
        queue.delete(message)
    return len(messages)
```

and update the module docstring's first line to mention retry messages ("read S3 upload events and Library retries from SQS").

`compose.yaml` api environment, next to the SSM endpoint (the `.env` value points at localhost, which the container can't reach):

```yaml
      # Retry sends a message to the worker's queue (PRD §9.5).
      SMART_TUTOR_INGEST_QUEUE_URL: http://localstack:4566/000000000000/smart-tutor-ingest
      AWS_ENDPOINT_URL_SQS: http://localstack:4566
```

`local/localstack/init/ready.d/10-smart-tutor.sh` after the file limits:

```bash
# Processing attempts per content (PRD §9.5): the API refuses a Retry after this many.
awslocal ssm put-parameter --name /smart-tutor/max-processing-attempts --type String --value 3 --overwrite
```

`infra/.../config.py`: add `("max-processing-attempts", "3")` to the loop and update its comment/docstring ("Per-file limits and processing attempts …").

Regenerate the web client: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`.

`knowledge/README.md`: add `RetryService` to services, `Content.retry(max_attempts)`, `Document.retry()`, and a Rules sentence: "Retry (`RetryService`) gives a failed content another attempt from `contents/<sha256>.pdf` — at most `max-processing-attempts` (SSM, 3) in all — returns every failed document linked to it to `processing`, and sends `{"retry_content_id": …}` to the ingest queue before committing, under the content's row lock; `process_content` locks the content on its first read, so it waits for that commit. After the last attempt the Library shows "This file could not be processed"."

- [ ] **Step 4: Run all checks**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest -q` and `cd infra && uv run pytest -q`
Expected: PASS (including `test_web_openapi_snapshot_is_current`).

- [ ] **Step 5: Commit**

```bash
git add backend compose.yaml local infra web/src/api
git commit -m "Add POST /documents/{id}/retry and let the worker process retries"
```

---

### Task 4: Retry in the Library table

**Files:**
- Modify: `web/src/api/documents.ts`, `web/src/api/documents.test.ts`
- Modify: `web/src/features/library/DocumentTable.tsx`, `DocumentTable.module.css`
- Modify: `web/src/features/library/LibraryPage.tsx`, `LibraryPage.test.tsx`

**Interfaces:**
- Consumes (Task 3): generated `retryDocument({ client, path: { document_id }, throwOnError: false })`; `DocumentResponse.attempt: number | null`, `max_attempts: number`, `can_retry: boolean`.
- Produces: `retryProcessing(documentId: string, apiClient?: Client): Promise<void>` in `api/documents.ts`; `LibraryPage` prop `retry?: (documentId: string) => Promise<void>`; `DocumentTable` props `{ documents, onRetry, retrying }` where `retrying: ReadonlySet<string>`.

Read `DESIGN.md` (Document states, buttons, accessibility) and look at `.design-shots/v0.4/library-failed.light.png` and `library-retry-processing.light.png` (render with `cd web && npm run design:shots -- --states "library-failed,library-retry-processing" --round v0.4 --theme both`). The mockup puts a secondary **Retry** button with the `RefreshCw` lucide icon in a trailing actions column; the exhausted row shows the "This file could not be processed" reason and no Retry. The "Open" link and "…" menu in the mockup belong to other stories — don't add them.

- [ ] **Step 1: Write the failing tests**

Update the fixtures at the top of `LibraryPage.test.tsx` to carry the new fields (`attempt: null, max_attempts: 3, can_retry: false` for `processing`; `attempt: null, max_attempts: 3, can_retry: false` for `duplicate`), then add:

```tsx
const scan: DocumentResponse = { document_id: "d3", title: "scan.pdf", state: "failed", failure_reason: "No text layer (scanned PDFs are not supported yet)", created_at: today, subjects: [], attempt: 1, max_attempts: 3, can_retry: true };

it("retries a failed document and refreshes the list", async () => {
  const load = vi.fn().mockResolvedValueOnce([scan]).mockResolvedValue([{ ...scan, state: "processing", failure_reason: null, attempt: 2, can_retry: false }]);
  const retry = vi.fn(async () => {});
  render(<LibraryPage loadLimits={limits} load={load} upload={vi.fn()} retry={retry} />);
  const row = (await screen.findByText("scan.pdf")).closest("tr")!;
  await userEvent.click(within(row).getByRole("button", { name: "Retry scan.pdf" }));
  expect(retry).toHaveBeenCalledWith("d3");
  expect(await within(row).findByText("Attempt 2 of 3.")).toBeVisible();
  expect(within(row).getByText("Processing")).toBeVisible();
  expect(within(row).queryByRole("button", { name: /Retry/ })).toBeNull();
});

it("shows no Retry once the attempts are used up", async () => {
  const usedUp = { ...scan, failure_reason: "This file could not be processed", attempt: 3, can_retry: false };
  render(<LibraryPage loadLimits={limits} load={async () => [usedUp]} upload={vi.fn()} retry={vi.fn()} />);
  const row = (await screen.findByText("scan.pdf")).closest("tr")!;
  expect(within(row).getByText("This file could not be processed")).toBeVisible();
  expect(within(row).queryByRole("button", { name: /Retry/ })).toBeNull();
});

it("shows no Retry for a failed document without a retry", async () => {
  render(<LibraryPage loadLimits={limits} load={async () => [duplicate]} upload={vi.fn()} retry={vi.fn()} />);
  const row = (await screen.findByText("copy.pdf")).closest("tr")!;
  expect(within(row).queryByRole("button", { name: /Retry/ })).toBeNull();
});

it("says so when a retry fails", async () => {
  const retry = vi.fn(async () => {
    throw new Error("POST /documents/d3/retry failed (500)");
  });
  render(<LibraryPage loadLimits={limits} load={async () => [scan]} upload={vi.fn()} retry={retry} />);
  const row = (await screen.findByText("scan.pdf")).closest("tr")!;
  await userEvent.click(within(row).getByRole("button", { name: "Retry scan.pdf" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Couldn't retry scan.pdf. Try again.");
  expect(within(row).getByRole("button", { name: "Retry scan.pdf" })).toBeEnabled();
});
```

In `documents.test.ts`, following its existing pattern for `loadDocuments` (read it first), add tests that `retryProcessing("d3", client)` POSTs to `/documents/d3/retry` and resolves on 204, throws `SessionExpiredError` on 401, and throws an `Error` on 409 and 500.

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npx vitest run src/features/library src/api/documents.test.ts`
Expected: FAIL.

- [ ] **Step 3: Implement**

`api/documents.ts`:

```ts
// Reprocesses a failed document's stored file (PRD §9.5). 409: the attempts are used up; the list then says so.
export async function retryProcessing(documentId: string, apiClient: Client = client): Promise<void> {
  const { error, response } = await retryDocument({ client: apiClient, path: { document_id: documentId }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!response?.ok) throw new Error(`POST /documents/${documentId}/retry failed (${response?.status ?? "no response"})`);
}
```

(import `retryDocument` from `./generated/sdk.gen`.)

`DocumentTable.tsx`: props `{ documents: DocumentResponse[]; onRetry: (doc: DocumentResponse) => void; retrying: ReadonlySet<string> }`. In `StateCell`, the processing hint becomes:

```tsx
{doc.state === "processing" && (
  <p className={styles.hint}>
    {doc.attempt && doc.attempt > 1 ? `Attempt ${doc.attempt} of ${doc.max_attempts}. ` : ""}
    You can choose subjects when processing finishes.
  </p>
)}
```

— but render the attempt as its own element so the test's exact text `Attempt 2 of 3.` matches: `<p className={styles.hint}>{attempt text}</p>` above the subjects hint. Add a fifth header `<th scope="col"><span className="visually-hidden">Actions</span></th>` and a cell:

```tsx
<td className={styles.actions}>
  {doc.state === "failed" && doc.can_retry && (
    <Button size="sm" icon={RefreshCw} aria-label={`Retry ${doc.title}`} disabled={retrying.has(doc.document_id)} onClick={() => onRetry(doc)}>
      Retry
    </Button>
  )}
</td>
```

CSS: `.actions { text-align: right; white-space: nowrap; }`.

`LibraryPage.tsx`: prop `retry = defaultRetry` with `const defaultRetry = (id: string) => retryProcessing(id);`; state `const [retrying, setRetrying] = useState<ReadonlySet<string>>(new Set());` and:

```tsx
async function onRetry(doc: DocumentResponse) {
  setRetrying((s) => new Set(s).add(doc.document_id));
  setStatus(`Retrying ${doc.title}…`);
  try {
    await retry(doc.document_id);
    setStatus(`Retrying ${doc.title}. Processing again.`);
  } catch {
    // A 401 is handled by the API client; a 409 (attempts used up) shows on the refreshed row.
    setStatus(`Couldn't retry ${doc.title}. Try again.`);
  }
  await refresh();
  setRetrying((s) => {
    const next = new Set(s);
    next.delete(doc.document_id);
    return next;
  });
}
```

Pass `onRetry={(d) => void onRetry(d)} retrying={retrying}` to `DocumentTable`.

- [ ] **Step 4: Run to verify they pass**

Run: `cd web && npx vitest run && npm run build`
Expected: PASS. Then render the app states you can (optional) or at least re-read the mockups against the table.

- [ ] **Step 5: Commit**

```bash
git add web/src
git commit -m "Show Retry and the attempt number in the Library"
```

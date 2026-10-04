# Upload a PDF; it's stored once and shows "processing" — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A signed-in learner picks a PDF on **My library**; the browser uploads it to S3 with a presigned POST, a row titled with the file name appears as *processing*, and the ingestion worker hashes the bytes on the server, stores one content at `contents/<sha256>.pdf` (insert-or-get), deletes the upload copy, and fails a duplicate with "Duplicate uploads aren't supported yet".

**Architecture:** `knowledge` gets its first real code: domain (`Content`, `Document`, `Upload`), ports (`ObjectStore`, `LibraryUnitOfWork` with content/document/upload repositories), and three services (`UploadService`, `DocumentService`, `IngestionService`). Adapters: SQLAlchemy Core on PostgreSQL (`INSERT … ON CONFLICT DO NOTHING` + select = insert-or-get) and boto3 S3. `shared` gains a `MessageQueue` port with an SQS adapter, a `SystemClock`, and boto3/SQLAlchemy factories. `apps/api` adds `POST /uploads` and `GET /documents`; `apps/worker` long-polls SQS and calls `IngestionService` per S3 event. The web Library polls `GET /documents` every 2 s and uploads through the generated client plus one form POST to S3.

**Tech Stack:** FastAPI, SQLAlchemy 2 Core + psycopg 3, Alembic, boto3 (S3, SQS), pytest; React 19, `@hey-api/openapi-ts` client, Vitest + Testing Library; LocalStack 4 and pgvector/pg17 in Compose.

**Spec:** GitHub issue #60 (slice of US-2 #9); PRD §8 US-2, §9.3 (uploads), §9.4, §9.5; ADR 0001, 0002; mockup state `library-first-processing@v0.4` (`make design-shots ROUND=v0.4 STATES="library-first-processing" THEME=both`).

## Global Constraints

- Upload key: `uploads/<user_id>/<upload_id>.pdf`; content key: `contents/<sha256>.pdf` (lowercase hex SHA-256 of the bytes, computed by the worker).
- Presigned POST policy: `Content-Type` = `application/pdf`, `content-length-range` 1 … 52,428,800 bytes (50 MiB), expires in 600 s. The key comes only from the caller's token `sub`; no endpoint takes a user id or a key.
- Duplicate failure reason, verbatim: `Duplicate uploads aren't supported yet`.
- Insert-or-get on the unique `contents.sha256`; two concurrent uploads of the same new file make one content row.
- Table and column names follow PRD §9.4. This slice adds `documents.file_name` and `documents.failure_reason` (PRD §9.4 is updated in Task 8, version → v2.9).
- `can_read` (Release 1): owner only — `Document.can_be_read_by()` in the domain and `documents.owner_id = :user_id` in SQL; `GET /documents` lists only the caller's non-archived documents, newest first.
- The Library refreshes every 2000 ms. Copy: "Upload", "Choose PDFs", "Not chosen yet", "You can choose subjects when processing finishes.", "Uploading <name>…", "Couldn't upload <name>. Try again.".
- Backend layering (`backend/AGENTS.md`): boto3/SQLAlchemy/FastAPI only in `adapters/` and `apps/`; `knowledge.domain|ports|application` import no vendor SDK and no `shared.adapters`.
- UI: `web/src/components/` and `var(--…)` tokens only (`DESIGN.md`); every web API call goes through `web/src/api/`.
- Out of scope (later slices): text, chunks, embeddings, page/type/size checks with reasons, Retry, browser duplicate check, drop zone and tray, rate limits, choosing subjects.
- Commits: imperative subject, body says why, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`; web: `cd web && npm run build && npm test`.

## Review Focus

1. **SQS redelivers a message the worker already handled** (crash after commit, before delete) — the document must not flip to "duplicate". Pinned in Task 2 (`test_redelivery_after_success_changes_nothing`).
2. **The same learner uploads the same file twice** — second document fails as a duplicate (no unique-constraint crash on `(owner_id, content_id)`). Pinned in Task 2 (`test_same_learner_same_file_is_a_duplicate`) and Task 3 (`test_duplicate_document_keeps_content_id_null`).
3. **A key that doesn't belong to the document's owner, or isn't an upload key** (S3 test event, stray object) — ignored, never linked. Pinned in Task 2 (`test_key_owner_mismatch_is_skipped`) and Task 6 (`test_s3_test_event_is_deleted_without_ingesting`).
4. **A file name with a path, control characters, or only spaces** — stored as the bare name, or 422. Pinned in Task 1 (`test_file_name_is_cleaned`) and Task 5 (`test_blank_file_name_is_422`).
5. **The S3 POST fails in the browser** (policy rejection, network) — the learner sees "Couldn't upload <name>. Try again." and the page keeps polling. Pinned in Task 7 (`shows an error when the upload fails`).

---

## File structure

```
backend/src/smart_tutor/
  shared/domain/ids.py                                   # + UploadId
  shared/ports/message_queue.py                          # QueueMessage, MessageQueue
  shared/adapters/clock.py                               # SystemClock
  shared/adapters/postgres/engine.py                     # create_db_engine()
  shared/adapters/postgres/migrations/versions/0002_library.py
  shared/adapters/aws/clients.py                         # s3_client(), sqs_client()
  shared/adapters/aws/sqs_queue.py                       # SqsMessageQueue
  shared/config.py                                       # + s3_path_style
  knowledge/domain/{errors,content,document,upload}.py
  knowledge/ports/{object_store,library}.py
  knowledge/application/{upload_service,document_service,ingestion_service}.py
  knowledge/application/__init__.py                      # public API re-exports
  knowledge/adapters/{sql_tables,sql_library,s3_object_store}.py
  apps/api/{main,deps,services}.py, apps/api/routes/knowledge.py
  apps/worker/{events,main}.py
backend/tests/
  fakes/{knowledge,queue,clock}.py, fakes/__init__.py
  unit/knowledge/{test_domain,test_upload_service,test_document_service,test_ingestion_service}.py
  unit/apps/api/test_knowledge_routes.py, unit/apps/worker/test_worker.py
  isolation/test_documents.py
  integration/knowledge/{test_sql_library,test_s3_object_store}.py
  integration/shared/test_migrations.py                  # expects 0002
web/src/
  api/documents.ts (+ .test.ts), api/generated/*, api/openapi.json
  components/StateBadge/*                                # + awaiting_subjects ("Choose subjects")
  features/library/{LibraryPage,DocumentTable,useDocuments}.tsx|ts, LibraryPage.module.css, DocumentTable.module.css, LibraryPage.test.tsx
compose.yaml, .env.example, backend/README.md, knowledge/README.md, sdd/prd.md
```

---

### Task 1: Knowledge domain, ports, and fakes

**Files:**
- Modify: `backend/src/smart_tutor/shared/domain/ids.py`
- Create: `backend/src/smart_tutor/knowledge/domain/errors.py`, `content.py`, `document.py`, `upload.py`
- Create: `backend/src/smart_tutor/knowledge/ports/object_store.py`, `library.py`
- Create: `backend/tests/fakes/knowledge.py`, `backend/tests/fakes/clock.py`; Modify: `backend/tests/fakes/__init__.py`
- Test: `backend/tests/unit/knowledge/test_domain.py`, `backend/tests/unit/knowledge/test_fakes.py`

**Interfaces:**
- Produces: `UploadId`; `Content.first_upload(content_id, sha256, size, uploader) -> Content`; `content_key(sha256)`; `Document.start_upload(document_id, owner_id, upload_id, file_name, created_at)`, `.title`, `.awaiting_upload`, `.link_content(content_id)`, `.fail(reason)`, `.can_be_read_by(user_id)`; `DUPLICATE_UPLOAD`; `Upload(upload_id, user_id, created_at, size=None, outcome=None)`, `.key`; `UploadOutcome.STORED|DUPLICATE`; `upload_key()`, `parse_upload_key(key) -> tuple[UserId, UploadId] | None`; `InvalidFileNameError`, `DocumentStateError`; ports `ObjectStore`, `PresignedPost`, `ObjectNotFoundError`, `ContentRepository`, `DocumentRepository`, `UploadRepository`, `LibraryUnitOfWork`; fakes `InMemoryLibrary` (`.unit_of_work()`), `FakeObjectStore`, `FixedClock`.

- [ ] **Step 1: Add `UploadId`** to `shared/domain/ids.py`:

```python
UploadId = NewType("UploadId", str)  # one presigned upload; binds uploads/<user_id>/<upload_id>.pdf to its document
```

- [ ] **Step 2: Write the failing domain tests** — `backend/tests/unit/knowledge/test_domain.py`:

```python
from datetime import UTC, datetime

import pytest

from smart_tutor.knowledge.domain.content import Content, ContentState, content_key
from smart_tutor.knowledge.domain.document import DUPLICATE_UPLOAD, Document, DocumentState
from smart_tutor.knowledge.domain.errors import DocumentStateError, InvalidFileNameError
from smart_tutor.knowledge.domain.upload import Upload, parse_upload_key, upload_key
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UploadId, UserId

NOW = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)
SHA = "a" * 64


def new_document(file_name: str = "lewis-rag-2020.pdf") -> Document:
    return Document.start_upload(DocumentId("d1"), UserId("ada"), UploadId("u1"), file_name, NOW)


def test_a_started_upload_is_processing_and_titled_by_its_file_name() -> None:
    doc = new_document()
    assert doc.state is DocumentState.PROCESSING
    assert doc.title == "lewis-rag-2020.pdf"
    assert doc.content_id is None
    assert doc.awaiting_upload


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("C:\\Users\\ada\\paper.pdf", "paper.pdf"),
        ("/home/ada/paper.pdf", "paper.pdf"),
        ("  paper.pdf  ", "paper.pdf"),
        ("pa\x00per\n.pdf", "paper.pdf"),
        ("x" * 300 + ".pdf", "x" * 255),
    ],
)
def test_file_name_is_cleaned(raw: str, clean: str) -> None:
    assert new_document(raw).file_name == clean


@pytest.mark.parametrize("raw", ["", "   ", "C:\\folder\\", "\x00\x01"])
def test_blank_file_name_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidFileNameError):
        new_document(raw)


def test_linking_content_keeps_the_document_processing() -> None:
    doc = new_document()
    doc.link_content(ContentId("c1"))
    assert doc.content_id == "c1"
    assert doc.state is DocumentState.PROCESSING
    assert not doc.awaiting_upload


def test_a_document_links_content_only_once() -> None:
    doc = new_document()
    doc.link_content(ContentId("c1"))
    with pytest.raises(DocumentStateError):
        doc.link_content(ContentId("c2"))


def test_failing_records_the_reason() -> None:
    doc = new_document()
    doc.fail(DUPLICATE_UPLOAD)
    assert doc.state is DocumentState.FAILED
    assert doc.failure_reason == "Duplicate uploads aren't supported yet"
    assert not doc.awaiting_upload
    with pytest.raises(DocumentStateError):
        doc.fail("again")


def test_only_the_owner_can_read_a_document() -> None:
    doc = new_document()
    assert doc.can_be_read_by(UserId("ada"))
    assert not doc.can_be_read_by(UserId("bob"))


def test_title_override_wins() -> None:
    doc = new_document()
    doc.title_override = "RAG for knowledge-intensive NLP"
    assert doc.title == "RAG for knowledge-intensive NLP"


def test_first_upload_creates_processing_content_at_its_hash_key() -> None:
    content = Content.first_upload(ContentId("c1"), SHA, 1234, UserId("ada"))
    assert content.state is ContentState.PROCESSING
    assert content.s3_key == content_key(SHA) == f"contents/{SHA}.pdf"
    assert content.attempts == 1
    assert content.processed_by_user_id == "ada"


@pytest.mark.parametrize("bad", ["A" * 64, "a" * 63, "g" * 64, ""])
def test_content_needs_a_lowercase_sha256(bad: str) -> None:
    with pytest.raises(ValueError, match="sha256"):
        Content.first_upload(ContentId("c1"), bad, 1, UserId("ada"))


def test_upload_key_round_trips() -> None:
    upload = Upload(UploadId("u1"), UserId("ada"), NOW)
    assert upload.key == upload_key(UserId("ada"), UploadId("u1")) == "uploads/ada/u1.pdf"
    assert parse_upload_key("uploads/ada/u1.pdf") == ("ada", "u1")


@pytest.mark.parametrize(
    "key", ["contents/x.pdf", "uploads/ada.pdf", "uploads/ada/u1.txt", "uploads/a/b/c.pdf", "uploads//u1.pdf"]
)
def test_other_keys_are_not_upload_keys(key: str) -> None:
    assert parse_upload_key(key) is None
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && uv run pytest tests/unit/knowledge/test_domain.py -q`
Expected: FAIL with `ModuleNotFoundError: smart_tutor.knowledge.domain.content`.

- [ ] **Step 4: Implement the domain**

`knowledge/domain/errors.py`:

```python
"""Errors of the knowledge module; entrypoints map them to responses."""

from smart_tutor.shared.domain.errors import DomainError


class InvalidFileNameError(DomainError):
    """The upload has no usable file name."""


class DocumentStateError(DomainError):
    """The document isn't in a state that allows this change (PRD §9.5)."""
```

`knowledge/domain/content.py`:

```python
"""A unique file, keyed by the SHA-256 the server computed from its bytes (PRD §9.4, §9.5; ADR 0002). No owner."""

import re
from dataclasses import dataclass
from enum import StrEnum

from smart_tutor.shared.domain.ids import ContentId, UserId

_SHA256 = re.compile(r"[0-9a-f]{64}")


class ContentState(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


def content_key(sha256: str) -> str:
    return f"contents/{sha256}.pdf"


@dataclass
class Content:
    content_id: ContentId
    sha256: str
    s3_key: str
    size: int  # column `bytes`
    state: ContentState
    attempts: int
    processed_by_user_id: UserId | None

    @classmethod
    def first_upload(cls, content_id: ContentId, sha256: str, size: int, uploader: UserId) -> "Content":
        """The first server-verified upload of these bytes starts processing (attempt 1 of 3)."""
        if not _SHA256.fullmatch(sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return cls(content_id, sha256, content_key(sha256), size, ContentState.PROCESSING, 1, uploader)
```

`knowledge/domain/document.py`:

```python
"""A learner's library entry (PRD §9.4, §9.5). Access: `can_be_read_by` is the domain half of `can_read`."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from smart_tutor.knowledge.domain.errors import DocumentStateError, InvalidFileNameError
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UploadId, UserId

DUPLICATE_UPLOAD = "Duplicate uploads aren't supported yet"  # until US-11 links duplicates
MAX_FILE_NAME = 255
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


class DocumentState(StrEnum):
    PROCESSING = "processing"
    AWAITING_SUBJECTS = "awaiting_subjects"
    READY = "ready"
    FAILED = "failed"


def clean_file_name(raw: str) -> str:
    """The bare name the learner picked: no folders, no control characters, at most 255 characters."""
    name = _CONTROL.sub("", raw.replace("\\", "/").rsplit("/", 1)[-1]).strip()[:MAX_FILE_NAME]
    if not name:
        raise InvalidFileNameError("The file needs a name")
    return name


@dataclass
class Document:
    document_id: DocumentId
    owner_id: UserId
    upload_id: UploadId
    file_name: str
    state: DocumentState
    created_at: datetime
    content_id: ContentId | None = None
    failure_reason: str | None = None
    title_override: str | None = None

    @classmethod
    def start_upload(
        cls, document_id: DocumentId, owner_id: UserId, upload_id: UploadId, file_name: str, created_at: datetime
    ) -> "Document":
        """(none) → processing when the upload starts; content_id stays null until the worker hashes the bytes."""
        return cls(document_id, owner_id, upload_id, clean_file_name(file_name), DocumentState.PROCESSING, created_at)

    @property
    def title(self) -> str:
        # Display title = title_override, else contents.title (first-pages step, US-2b), else the file name.
        return self.title_override or self.file_name

    @property
    def awaiting_upload(self) -> bool:
        """Still waiting for the worker to hash its upload."""
        return self.state is DocumentState.PROCESSING and self.content_id is None

    def can_be_read_by(self, user_id: UserId) -> bool:
        return self.owner_id == user_id  # Release 1: owner only (PRD §9.3)

    def link_content(self, content_id: ContentId) -> None:
        if not self.awaiting_upload:
            raise DocumentStateError("This document already has its content")
        self.content_id = content_id

    def fail(self, reason: str) -> None:
        if self.state is not DocumentState.PROCESSING:
            raise DocumentStateError("Only a processing document can fail")
        self.state = DocumentState.FAILED
        self.failure_reason = reason
```

`knowledge/domain/upload.py`:

```python
"""One presigned upload, recorded for rate limits and daily caps (PRD §9.4). The key binds it to its learner."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from smart_tutor.shared.domain.ids import UploadId, UserId

_KEY = re.compile(r"uploads/([^/]+)/([^/]+)\.pdf")


class UploadOutcome(StrEnum):
    STORED = "stored"  # new content stored at contents/<sha256>.pdf
    DUPLICATE = "duplicate"  # bytes already known; the document failed (until US-11)


def upload_key(user_id: UserId, upload_id: UploadId) -> str:
    return f"uploads/{user_id}/{upload_id}.pdf"


def parse_upload_key(key: str) -> tuple[UserId, UploadId] | None:
    match = _KEY.fullmatch(key)
    return (UserId(match[1]), UploadId(match[2])) if match else None


@dataclass
class Upload:
    upload_id: UploadId
    user_id: UserId
    created_at: datetime
    size: int | None = None  # column `bytes`, known once the worker reads the upload
    outcome: UploadOutcome | None = None

    @property
    def key(self) -> str:
        return upload_key(self.user_id, self.upload_id)
```

- [ ] **Step 5: Run the domain tests** — `uv run pytest tests/unit/knowledge/test_domain.py -q` → PASS.

- [ ] **Step 6: Write the ports**

`knowledge/ports/object_store.py`:

```python
"""Object storage for uploads and contents (S3 in production, LocalStack locally)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class ObjectNotFoundError(Exception):
    """No object at that key."""


@dataclass(frozen=True)
class PresignedPost:
    """Where and how the browser POSTs a file: the form fields go first, the file last."""

    url: str
    fields: dict[str, str]


class ObjectStore(ABC):
    @abstractmethod
    def presign_post(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedPost:
        """A POST that stores exactly `key`, only with this content type and 1..max_bytes bytes."""

    @abstractmethod
    def read(self, key: str) -> bytes:
        """The object's bytes; raises ObjectNotFoundError."""

    @abstractmethod
    def copy(self, source_key: str, dest_key: str) -> None:
        """Copy within the bucket (same bytes at `dest_key`)."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete; a missing object is not an error."""
```

`knowledge/ports/library.py`:

```python
"""Persistence of contents, documents, and uploads, committed together (one unit of work per use case)."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from smart_tutor.knowledge.domain.content import Content
from smart_tutor.knowledge.domain.document import Document
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.shared.domain.ids import UploadId, UserId


class ContentRepository(ABC):
    @abstractmethod
    def insert_or_get(self, content: Content) -> tuple[Content, bool]:
        """Insert unless the sha256 exists; return the stored content and whether this call created it.

        Concurrent callers with the same sha256 get one row: the second waits for the first to commit.
        """


class DocumentRepository(ABC):
    @abstractmethod
    def add(self, document: Document) -> None: ...

    @abstractmethod
    def get_by_upload_for_update(self, upload_id: UploadId) -> Document | None:
        """The document of this upload, locked until the unit of work ends."""

    @abstractmethod
    def save(self, document: Document) -> None:
        """Write back content_id, state, and failure_reason."""

    @abstractmethod
    def list_readable_by(self, user_id: UserId) -> list[Document]:
        """`can_read` in storage: the caller's non-archived documents, newest first."""


class UploadRepository(ABC):
    @abstractmethod
    def add(self, upload: Upload) -> None: ...

    @abstractmethod
    def record_outcome(self, upload_id: UploadId, size: int, outcome: UploadOutcome) -> None: ...


class LibraryUnitOfWork(ABC):
    """`with factory() as tx: …; tx.commit()` — leaving without commit rolls back."""

    contents: ContentRepository
    documents: DocumentRepository
    uploads: UploadRepository

    @abstractmethod
    def commit(self) -> None: ...

    @abstractmethod
    def __enter__(self) -> Self: ...

    @abstractmethod
    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None: ...
```

- [ ] **Step 7: Write the fakes** — `backend/tests/fakes/clock.py`:

```python
"""A clock that says what the test tells it."""

from datetime import UTC, datetime

from smart_tutor.shared.ports.clock import Clock


class FixedClock(Clock):
    def __init__(self, now: datetime = datetime(2026, 10, 4, 9, 0, tzinfo=UTC)) -> None:
        self.current = now

    def now(self) -> datetime:
        return self.current
```

`backend/tests/fakes/knowledge.py`:

```python
"""In-memory library and object store. A unit of work edits a copy and publishes it on commit."""

import copy
from types import TracebackType
from typing import Self

from smart_tutor.knowledge.domain.content import Content
from smart_tutor.knowledge.domain.document import Document
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.knowledge.ports.library import (
    ContentRepository,
    DocumentRepository,
    LibraryUnitOfWork,
    UploadRepository,
)
from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, ObjectStore, PresignedPost
from smart_tutor.shared.domain.ids import UploadId, UserId


class _State:
    def __init__(self) -> None:
        self.contents: dict[str, Content] = {}
        self.documents: dict[str, Document] = {}
        self.uploads: dict[str, Upload] = {}


class InMemoryLibrary:
    def __init__(self) -> None:
        self.state = _State()
        self.commits = 0

    def unit_of_work(self) -> "FakeLibraryUnitOfWork":
        return FakeLibraryUnitOfWork(self)


class _Contents(ContentRepository):
    def __init__(self, state: _State) -> None:
        self._s = state

    def insert_or_get(self, content: Content) -> tuple[Content, bool]:
        for existing in self._s.contents.values():
            if existing.sha256 == content.sha256:
                return copy.deepcopy(existing), False
        self._s.contents[content.content_id] = copy.deepcopy(content)
        return content, True


class _Documents(DocumentRepository):
    def __init__(self, state: _State) -> None:
        self._s = state

    def add(self, document: Document) -> None:
        self._s.documents[document.document_id] = copy.deepcopy(document)

    def get_by_upload_for_update(self, upload_id: UploadId) -> Document | None:
        found = [d for d in self._s.documents.values() if d.upload_id == upload_id]
        return copy.deepcopy(found[0]) if found else None

    def save(self, document: Document) -> None:
        if document.content_id is not None and any(
            d.owner_id == document.owner_id and d.content_id == document.content_id and d.document_id != document.document_id
            for d in self._s.documents.values()
        ):
            raise AssertionError("unique (owner_id, content_id) violated")
        self._s.documents[document.document_id] = copy.deepcopy(document)

    def list_readable_by(self, user_id: UserId) -> list[Document]:
        mine = [copy.deepcopy(d) for d in self._s.documents.values() if d.can_be_read_by(user_id)]
        return sorted(mine, key=lambda d: d.created_at, reverse=True)


class _Uploads(UploadRepository):
    def __init__(self, state: _State) -> None:
        self._s = state

    def add(self, upload: Upload) -> None:
        self._s.uploads[upload.upload_id] = copy.deepcopy(upload)

    def record_outcome(self, upload_id: UploadId, size: int, outcome: UploadOutcome) -> None:
        upload = self._s.uploads[upload_id]
        upload.size, upload.outcome = size, outcome


class FakeLibraryUnitOfWork(LibraryUnitOfWork):
    def __init__(self, library: InMemoryLibrary) -> None:
        self._library = library
        self._staged = copy.deepcopy(library.state)
        self.contents = _Contents(self._staged)
        self.documents = _Documents(self._staged)
        self.uploads = _Uploads(self._staged)

    def commit(self) -> None:
        self._library.state = copy.deepcopy(self._staged)
        self._library.commits += 1

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        return None  # uncommitted changes stay in the discarded copy


class FakeObjectStore(ObjectStore):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.presigned: list[tuple[str, str, int, int]] = []  # key, content type, max bytes, expires in

    def presign_post(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedPost:
        self.presigned.append((key, content_type, max_bytes, expires_in))
        return PresignedPost(url="http://s3.test/bucket", fields={"key": key, "Content-Type": content_type})

    def read(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise ObjectNotFoundError(key) from None

    def copy(self, source_key: str, dest_key: str) -> None:
        self.objects[dest_key] = self.read(source_key)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)
```

Export from `fakes/__init__.py`: add `FixedClock`, `InMemoryLibrary`, `FakeObjectStore` to imports and `__all__`.

- [ ] **Step 8: Test the fake's unit-of-work semantics** — `tests/unit/knowledge/test_fakes.py`:

```python
from datetime import UTC, datetime

from fakes import InMemoryLibrary
from smart_tutor.knowledge.domain.upload import Upload
from smart_tutor.shared.domain.ids import UploadId, UserId


def test_uncommitted_changes_are_discarded() -> None:
    library = InMemoryLibrary()
    with library.unit_of_work() as tx:
        tx.uploads.add(Upload(UploadId("u1"), UserId("ada"), datetime.now(UTC)))
    assert library.state.uploads == {}
    with library.unit_of_work() as tx:
        tx.uploads.add(Upload(UploadId("u1"), UserId("ada"), datetime.now(UTC)))
        tx.commit()
    assert set(library.state.uploads) == {"u1"}
```

Run: `uv run pytest tests/unit/knowledge -q` → PASS. Then `uv run mypy && PYTHONUTF8=1 uv run lint-imports` → clean.

- [ ] **Step 9: Commit**

```bash
git add backend/src/smart_tutor/shared/domain/ids.py backend/src/smart_tutor/knowledge backend/tests/fakes backend/tests/unit/knowledge
git commit -m "Add the knowledge domain and ports for uploads, documents, and contents" -m "Contents are keyed by a server-computed SHA-256 and documents start processing when the upload starts (PRD 9.5); in-memory fakes let the services be tested without Postgres or S3."
```

---

### Task 2: Upload, document, and ingestion services

**Files:**
- Create: `backend/src/smart_tutor/knowledge/application/upload_service.py`, `document_service.py`, `ingestion_service.py`
- Modify: `backend/src/smart_tutor/knowledge/application/__init__.py`
- Test: `backend/tests/unit/knowledge/test_upload_service.py`, `test_document_service.py`, `test_ingestion_service.py`

**Interfaces:**
- Consumes: Task 1 domain, ports, fakes.
- Produces (all re-exported from `smart_tutor.knowledge.application`):
  - `UploadService(uow: Callable[[], LibraryUnitOfWork], objects: ObjectStore, clock: Clock, new_id: Callable[[], str] = new_uuid)`; `.start_upload(owner_id: UserId, file_name: str) -> StartedUpload`; `StartedUpload(document_id, upload_id, url, fields)`; constants `MAX_UPLOAD_BYTES = 52_428_800`, `PDF_CONTENT_TYPE = "application/pdf"`, `PRESIGN_SECONDS = 600`.
  - `DocumentService(uow)`; `.list_documents(user_id) -> list[DocumentView]`; `DocumentView(document_id, title, state: str, failure_reason: str | None, created_at: datetime)`.
  - `IngestionService(uow, objects, new_id=new_uuid)`; `.ingest_upload(key: str) -> UploadOutcome | None` (None = skipped).
  - Re-exports `InvalidFileNameError`, `UploadOutcome`, `ObjectStore`, `LibraryUnitOfWork` for `apps` wiring.

- [ ] **Step 1: Write failing tests** — `tests/unit/knowledge/test_upload_service.py`:

```python
import pytest

from fakes import FakeObjectStore, FixedClock, InMemoryLibrary
from smart_tutor.knowledge.application import InvalidFileNameError, UploadService
from smart_tutor.shared.domain.ids import UserId


def make(ids: list[str] | None = None) -> tuple[UploadService, InMemoryLibrary, FakeObjectStore]:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    it = iter(ids or ["upload-1", "doc-1"])
    return UploadService(library.unit_of_work, objects, FixedClock(), lambda: next(it)), library, objects


def test_start_upload_presigns_the_callers_key_with_the_pdf_policy() -> None:
    service, _, objects = make()
    started = service.start_upload(UserId("ada"), "paper.pdf")
    assert started.upload_id == "upload-1"
    assert started.document_id == "doc-1"
    assert started.fields["key"] == "uploads/ada/upload-1.pdf"
    assert objects.presigned == [("uploads/ada/upload-1.pdf", "application/pdf", 52_428_800, 600)]


def test_start_upload_records_the_upload_and_a_processing_document() -> None:
    service, library, _ = make()
    service.start_upload(UserId("ada"), "C:\\papers\\paper.pdf")
    doc = library.state.documents["doc-1"]
    assert (doc.owner_id, doc.upload_id, doc.file_name, doc.state) == ("ada", "upload-1", "paper.pdf", "processing")
    assert library.state.uploads["upload-1"].user_id == "ada"


def test_a_blank_name_stores_nothing() -> None:
    service, library, objects = make()
    with pytest.raises(InvalidFileNameError):
        service.start_upload(UserId("ada"), "   ")
    assert library.state.documents == {} and objects.presigned == []
```

`tests/unit/knowledge/test_document_service.py`:

```python
from datetime import timedelta

from fakes import FakeObjectStore, FixedClock, InMemoryLibrary
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.domain.ids import UserId


def test_lists_only_the_callers_documents_newest_first() -> None:
    library, clock = InMemoryLibrary(), FixedClock()
    uploads = UploadService(library.unit_of_work, FakeObjectStore(), clock)
    uploads.start_upload(UserId("ada"), "first.pdf")
    clock.current += timedelta(minutes=1)
    uploads.start_upload(UserId("ada"), "second.pdf")
    uploads.start_upload(UserId("bob"), "bobs.pdf")

    docs = DocumentService(library.unit_of_work).list_documents(UserId("ada"))

    assert [d.title for d in docs] == ["second.pdf", "first.pdf"]
    assert {d.state for d in docs} == {"processing"}
    assert all(d.failure_reason is None for d in docs)
    assert DocumentService(library.unit_of_work).list_documents(UserId("carol")) == []
```

`tests/unit/knowledge/test_ingestion_service.py`:

```python
import hashlib

from fakes import FakeObjectStore, FixedClock, InMemoryLibrary
from smart_tutor.knowledge.application import IngestionService, StartedUpload, UploadOutcome, UploadService
from smart_tutor.shared.domain.ids import UserId

PDF = b"%PDF-1.7 the same bytes"
SHA = hashlib.sha256(PDF).hexdigest()


class World:
    def __init__(self) -> None:
        self.library, self.objects = InMemoryLibrary(), FakeObjectStore()
        self.uploads = UploadService(self.library.unit_of_work, self.objects, FixedClock())
        self.ingestion = IngestionService(self.library.unit_of_work, self.objects)

    def upload(self, user: str, data: bytes = PDF, name: str = "paper.pdf") -> StartedUpload:
        started = self.uploads.start_upload(UserId(user), name)
        self.objects.objects[started.fields["key"]] = data  # what the browser's POST does
        return started

    def doc(self, started: StartedUpload):  # noqa: ANN201
        return self.library.state.documents[started.document_id]


def test_a_new_file_is_stored_once_under_its_hash_and_the_upload_copy_removed() -> None:
    w = World()
    a = w.upload("ada")
    assert w.ingestion.ingest_upload(a.fields["key"]) is UploadOutcome.STORED
    assert w.objects.objects == {f"contents/{SHA}.pdf": PDF}
    [content] = w.library.state.contents.values()
    assert (content.sha256, content.size, content.state, content.processed_by_user_id) == (SHA, len(PDF), "processing", "ada")
    doc = w.doc(a)
    assert (doc.content_id, doc.state) == (content.content_id, "processing")
    upload = w.library.state.uploads[a.upload_id]
    assert (upload.size, upload.outcome) == (len(PDF), UploadOutcome.STORED)


def test_another_learners_identical_file_fails_as_a_duplicate() -> None:
    w = World()
    a, b = w.upload("ada"), w.upload("bob")
    w.ingestion.ingest_upload(a.fields["key"])
    assert w.ingestion.ingest_upload(b.fields["key"]) is UploadOutcome.DUPLICATE
    assert len(w.library.state.contents) == 1
    doc = w.doc(b)
    assert (doc.state, doc.failure_reason, doc.content_id) == ("failed", "Duplicate uploads aren't supported yet", None)
    assert b.fields["key"] not in w.objects.objects
    assert w.library.state.uploads[b.upload_id].outcome is UploadOutcome.DUPLICATE


def test_same_learner_same_file_is_a_duplicate() -> None:
    w = World()
    first, second = w.upload("ada"), w.upload("ada", name="copy.pdf")
    w.ingestion.ingest_upload(first.fields["key"])
    assert w.ingestion.ingest_upload(second.fields["key"]) is UploadOutcome.DUPLICATE
    assert w.doc(second).state == "failed"


def test_different_bytes_make_different_contents() -> None:
    w = World()
    a, b = w.upload("ada"), w.upload("ada", data=b"%PDF other")
    w.ingestion.ingest_upload(a.fields["key"])
    assert w.ingestion.ingest_upload(b.fields["key"]) is UploadOutcome.STORED
    assert len(w.library.state.contents) == 2


def test_redelivery_after_success_changes_nothing() -> None:
    w = World()
    a, b = w.upload("ada"), w.upload("bob")
    w.ingestion.ingest_upload(a.fields["key"])
    w.objects.objects[a.fields["key"]] = PDF  # S3 event redelivered; say the delete hadn't happened
    assert w.ingestion.ingest_upload(a.fields["key"]) is None
    assert w.doc(a).state == "processing" and w.doc(a).content_id is not None
    assert a.fields["key"] not in w.objects.objects
    w.ingestion.ingest_upload(b.fields["key"])
    assert w.ingestion.ingest_upload(b.fields["key"]) is None
    assert w.doc(b).failure_reason == "Duplicate uploads aren't supported yet"


def test_key_owner_mismatch_is_skipped() -> None:
    w = World()
    a = w.upload("ada")
    forged = f"uploads/bob/{a.upload_id}.pdf"
    w.objects.objects[forged] = PDF
    assert w.ingestion.ingest_upload(forged) is None
    assert w.doc(a).awaiting_upload
    assert w.library.state.contents == {}


def test_unknown_upload_and_non_upload_keys_are_skipped() -> None:
    w = World()
    assert w.ingestion.ingest_upload("uploads/ada/nope.pdf") is None
    assert w.ingestion.ingest_upload(f"contents/{SHA}.pdf") is None


def test_a_missing_upload_object_is_skipped_and_the_document_still_waits() -> None:
    w = World()
    a = w.uploads.start_upload(UserId("ada"), "paper.pdf")  # browser never POSTed
    assert w.ingestion.ingest_upload(a.fields["key"]) is None
    assert w.doc(a).awaiting_upload


def test_a_failure_before_commit_leaves_the_upload_for_a_retry() -> None:
    w = World()
    a = w.upload("ada")

    def broken_copy(source_key: str, dest_key: str) -> None:
        raise RuntimeError("S3 down")

    w.objects.copy = broken_copy  # type: ignore[method-assign]
    try:
        w.ingestion.ingest_upload(a.fields["key"])
    except RuntimeError:
        pass
    assert w.library.state.contents == {}
    assert w.doc(a).awaiting_upload
    assert a.fields["key"] in w.objects.objects
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/knowledge -q` → FAIL (`ImportError: cannot import name 'UploadService'`).

- [ ] **Step 3: Implement** — `knowledge/application/upload_service.py`:

```python
"""Start an upload: record it, create the processing document, and presign the browser's POST (PRD §9.3, §9.5)."""

from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from smart_tutor.knowledge.domain.document import Document
from smart_tutor.knowledge.domain.upload import Upload
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectStore
from smart_tutor.shared.domain.ids import DocumentId, UploadId, UserId
from smart_tutor.shared.ports.clock import Clock

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
PDF_CONTENT_TYPE = "application/pdf"
PRESIGN_SECONDS = 600


def new_uuid() -> str:
    return str(uuid4())


@dataclass(frozen=True)
class StartedUpload:
    document_id: DocumentId
    upload_id: UploadId
    url: str
    fields: dict[str, str]


class UploadService:
    def __init__(
        self,
        uow: Callable[[], LibraryUnitOfWork],
        objects: ObjectStore,
        clock: Clock,
        new_id: Callable[[], str] = new_uuid,
    ) -> None:
        self._uow, self._objects, self._clock, self._new_id = uow, objects, clock, new_id

    def start_upload(self, owner_id: UserId, file_name: str) -> StartedUpload:
        now = self._clock.now()
        upload = Upload(UploadId(self._new_id()), owner_id, now)
        document = Document.start_upload(DocumentId(self._new_id()), owner_id, upload.upload_id, file_name, now)
        post = self._objects.presign_post(
            upload.key, content_type=PDF_CONTENT_TYPE, max_bytes=MAX_UPLOAD_BYTES, expires_in=PRESIGN_SECONDS
        )
        with self._uow() as tx:
            tx.uploads.add(upload)
            tx.documents.add(document)
            tx.commit()
        return StartedUpload(document.document_id, upload.upload_id, post.url, post.fields)
```

`knowledge/application/document_service.py`:

```python
"""The learner's library as they see it. Reads go through `can_read` (PRD §9.3)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import DocumentId, UserId


@dataclass(frozen=True)
class DocumentView:
    document_id: DocumentId
    title: str
    state: str  # processing | awaiting_subjects | ready | failed
    failure_reason: str | None
    created_at: datetime


class DocumentService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork]) -> None:
        self._uow = uow

    def list_documents(self, user_id: UserId) -> list[DocumentView]:
        with self._uow() as tx:
            documents = tx.documents.list_readable_by(user_id)
        return [DocumentView(d.document_id, d.title, d.state.value, d.failure_reason, d.created_at) for d in documents]
```

`knowledge/application/ingestion_service.py`:

```python
"""Hash an uploaded file on the server and store its content once (PRD §9.5; ADR 0002).

Text extraction comes in the next slice, so a stored document stays processing.
"""

import hashlib
import logging
from collections.abc import Callable

from smart_tutor.knowledge.application.upload_service import new_uuid
from smart_tutor.knowledge.domain.content import Content
from smart_tutor.knowledge.domain.document import DUPLICATE_UPLOAD
from smart_tutor.knowledge.domain.upload import UploadOutcome, parse_upload_key
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, ObjectStore
from smart_tutor.shared.domain.ids import ContentId

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(
        self, uow: Callable[[], LibraryUnitOfWork], objects: ObjectStore, new_id: Callable[[], str] = new_uuid
    ) -> None:
        self._uow, self._objects, self._new_id = uow, objects, new_id

    def ingest_upload(self, key: str) -> UploadOutcome | None:
        """Store or reject one uploaded file. None means there was nothing to do (not ours, or already handled).

        Everything happens in one transaction that holds the document's row lock and, for a new hash, the
        content's unique key, so a crash before commit leaves the upload to be redelivered and retried.
        """
        parsed = parse_upload_key(key)
        if parsed is None:
            logger.warning("ignoring a non-upload key")
            return None
        user_id, upload_id = parsed
        with self._uow() as tx:
            document = tx.documents.get_by_upload_for_update(upload_id)
            if document is None or not document.can_be_read_by(user_id):
                logger.warning("no document for upload %s under this learner; ignoring", upload_id)
                return None
            if not document.awaiting_upload:
                logger.info("upload %s was already handled", upload_id)
                self._objects.delete(key)
                return None
            try:
                data = self._objects.read(key)
            except ObjectNotFoundError:
                logger.warning("upload %s has no object", upload_id)
                return None
            sha256 = hashlib.sha256(data).hexdigest()
            content, created = tx.contents.insert_or_get(
                Content.first_upload(ContentId(self._new_id()), sha256, len(data), user_id)
            )
            if created:
                self._objects.copy(key, content.s3_key)
                document.link_content(content.content_id)
                outcome = UploadOutcome.STORED
            else:
                # Until US-11 links duplicates. content_id stays null: (owner_id, content_id) is unique.
                document.fail(DUPLICATE_UPLOAD)
                outcome = UploadOutcome.DUPLICATE
            tx.documents.save(document)
            tx.uploads.record_outcome(upload_id, len(data), outcome)
            tx.commit()
        self._objects.delete(key)
        logger.info("upload %s: %s", upload_id, outcome.value)
        return outcome
```

`knowledge/application/__init__.py`:

```python
"""knowledge.application: the module's public API (one service per use case)."""

from smart_tutor.knowledge.application.document_service import DocumentService, DocumentView
from smart_tutor.knowledge.application.ingestion_service import IngestionService
from smart_tutor.knowledge.application.upload_service import (
    MAX_UPLOAD_BYTES,
    PDF_CONTENT_TYPE,
    StartedUpload,
    UploadService,
)
from smart_tutor.knowledge.domain.errors import InvalidFileNameError
from smart_tutor.knowledge.domain.upload import UploadOutcome
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectStore

__all__ = [
    "MAX_UPLOAD_BYTES",
    "PDF_CONTENT_TYPE",
    "DocumentService",
    "DocumentView",
    "IngestionService",
    "InvalidFileNameError",
    "LibraryUnitOfWork",
    "ObjectStore",
    "StartedUpload",
    "UploadOutcome",
    "UploadService",
]
```

(Keep the existing module docstring line if it differs; replace only the body.)

- [ ] **Step 4: Run** — `uv run pytest tests/unit/knowledge -q` → PASS; `uv run ruff check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports` → clean.

- [ ] **Step 5: Commit** — `git commit -m "Hash uploads on the server and store each content once"` with a body explaining insert-or-get, duplicate failure until US-11, and redelivery idempotence.

---

### Task 3: Library tables in PostgreSQL

**Files:**
- Create: `backend/src/smart_tutor/shared/adapters/postgres/engine.py`
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0002_library.py`
- Create: `backend/src/smart_tutor/knowledge/adapters/sql_tables.py`, `sql_library.py`
- Modify: `backend/tests/integration/shared/test_migrations.py`
- Test: `backend/tests/integration/knowledge/__init__.py`, `backend/tests/integration/knowledge/test_sql_library.py`

**Interfaces:**
- Consumes: Task 1 ports and domain.
- Produces: `create_db_engine(url: str) -> Engine`; `SqlLibraryUnitOfWork(engine: Engine)` implementing `LibraryUnitOfWork`; `GENERAL_SUBJECT_ID = "00000000-0000-4000-8000-000000000001"` (seeded subject "General", normalized `general`).

- [ ] **Step 1: Engine factory** — `shared/adapters/postgres/engine.py`:

```python
"""One SQLAlchemy engine per process (psycopg 3)."""

from sqlalchemy import Engine, create_engine


def create_db_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)
```

- [ ] **Step 2: Migration** — `versions/0002_library.py`:

```python
"""Library: contents, uploads, documents, subjects, document_subjects; seed the subject "General" (PRD §9.4).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GENERAL_SUBJECT_ID = "00000000-0000-4000-8000-000000000001"


def _created_at() -> sa.Column:  # type: ignore[type-arg]
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    subjects = op.create_table(
        "subjects",
        sa.Column("subject_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("canonical_name", sa.Text, nullable=False),
        sa.Column("normalized_name", sa.Text, nullable=False, unique=True),
        _created_at(),
    )
    op.bulk_insert(
        subjects, [{"subject_id": GENERAL_SUBJECT_ID, "canonical_name": "General", "normalized_name": "general"}]
    )
    op.create_table(
        "contents",
        sa.Column("content_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("s3_key", sa.Text, nullable=False),
        sa.Column("bytes", sa.BigInteger, nullable=False),
        sa.Column("pages", sa.Integer),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("failure_reason", sa.Text),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("processed_by_user_id", sa.Text),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        _created_at(),
        sa.CheckConstraint("state in ('processing', 'ready', 'failed')", name="contents_state"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="contents_sha256_hex"),
    )
    op.create_table(
        "uploads",
        sa.Column("upload_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("bytes", sa.BigInteger),
        _created_at(),
        sa.Column("outcome", sa.Text),
        sa.CheckConstraint("outcome in ('stored', 'duplicate')", name="uploads_outcome"),
    )
    op.create_index("uploads_user_created", "uploads", ["user_id", "created_at"])
    op.create_table(
        "documents",
        sa.Column("document_id", sa.Uuid(as_uuid=False), primary_key=True),
        sa.Column("owner_id", sa.Text, nullable=False),
        sa.Column("content_id", sa.Uuid(as_uuid=False), sa.ForeignKey("contents.content_id")),
        sa.Column("upload_id", sa.Uuid(as_uuid=False), sa.ForeignKey("uploads.upload_id"), nullable=False, unique=True),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("failure_reason", sa.Text),
        sa.Column("archived", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.Column("visibility", sa.Text, nullable=False, server_default="private"),
        sa.Column("title_override", sa.Text),
        sa.Column("added_via", sa.Text, nullable=False, server_default="upload"),
        _created_at(),
        # NULL content_ids are distinct in Postgres, so many unhashed documents per learner are fine.
        sa.UniqueConstraint("owner_id", "content_id", name="documents_owner_content"),
        sa.CheckConstraint(
            "state in ('processing', 'awaiting_subjects', 'ready', 'failed')", name="documents_state"
        ),
        sa.CheckConstraint("visibility in ('private', 'shared', 'public')", name="documents_visibility"),
        sa.CheckConstraint(
            "added_via in ('upload', 'dedupe', 'share', 'public', 'import')", name="documents_added_via"
        ),
    )
    op.create_index("documents_owner_created", "documents", ["owner_id", "created_at"])
    op.create_table(
        "document_subjects",
        sa.Column("document_id", sa.Uuid(as_uuid=False), sa.ForeignKey("documents.document_id"), primary_key=True),
        sa.Column("subject_id", sa.Uuid(as_uuid=False), sa.ForeignKey("subjects.subject_id"), primary_key=True),
    )


def downgrade() -> None:
    for table in ("document_subjects", "documents", "uploads", "contents", "subjects"):
        op.drop_table(table)
```

If ruff/mypy complain about `_created_at`'s annotation, use `-> sa.Column[Any]` with `from typing import Any` (mypy excludes migration versions; ruff must pass).

- [ ] **Step 3: Core tables for the adapter** — `knowledge/adapters/sql_tables.py` mirrors only what the adapter reads and writes:

```python
"""SQLAlchemy Core views of the library tables (the schema itself lives in the Alembic migrations)."""

from sqlalchemy import BigInteger, Boolean, Column, DateTime, Integer, MetaData, String, Table, Text, Uuid

metadata = MetaData()

contents = Table(
    "contents",
    metadata,
    Column("content_id", Uuid(as_uuid=False), primary_key=True),
    Column("sha256", String(64)),
    Column("s3_key", Text),
    Column("bytes", BigInteger),
    Column("state", Text),
    Column("attempts", Integer),
    Column("processed_by_user_id", Text),
    Column("processed_at", DateTime(timezone=True)),
)

uploads = Table(
    "uploads",
    metadata,
    Column("upload_id", Uuid(as_uuid=False), primary_key=True),
    Column("user_id", Text),
    Column("bytes", BigInteger),
    Column("created_at", DateTime(timezone=True)),
    Column("outcome", Text),
)

documents = Table(
    "documents",
    metadata,
    Column("document_id", Uuid(as_uuid=False), primary_key=True),
    Column("owner_id", Text),
    Column("content_id", Uuid(as_uuid=False)),
    Column("upload_id", Uuid(as_uuid=False)),
    Column("file_name", Text),
    Column("state", Text),
    Column("failure_reason", Text),
    Column("archived", Boolean),
    Column("title_override", Text),
    Column("created_at", DateTime(timezone=True)),
)
```

- [ ] **Step 4: The unit of work** — `knowledge/adapters/sql_library.py`:

```python
"""PostgreSQL library: one connection and transaction per unit of work."""

from types import TracebackType
from typing import Any, Self

from sqlalchemy import ColumnElement, Connection, Engine, func, select, update
from sqlalchemy.dialects.postgresql import insert

from smart_tutor.knowledge.adapters.sql_tables import contents, documents, uploads
from smart_tutor.knowledge.domain.content import Content, ContentState
from smart_tutor.knowledge.domain.document import Document, DocumentState
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.knowledge.ports.library import (
    ContentRepository,
    DocumentRepository,
    LibraryUnitOfWork,
    UploadRepository,
)
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UploadId, UserId


def readable_by(user_id: UserId) -> ColumnElement[bool]:
    """`can_read` in SQL (Release 1: owner only; PRD §9.3). The domain twin is Document.can_be_read_by."""
    return documents.c.owner_id == user_id


def _content(row: Any) -> Content:
    return Content(
        ContentId(row.content_id), row.sha256, row.s3_key, row.bytes, ContentState(row.state), row.attempts,
        UserId(row.processed_by_user_id) if row.processed_by_user_id else None,
    )


def _document(row: Any) -> Document:
    return Document(
        document_id=DocumentId(row.document_id),
        owner_id=UserId(row.owner_id),
        upload_id=UploadId(row.upload_id),
        file_name=row.file_name,
        state=DocumentState(row.state),
        created_at=row.created_at,
        content_id=ContentId(row.content_id) if row.content_id else None,
        failure_reason=row.failure_reason,
        title_override=row.title_override,
    )


class _Contents(ContentRepository):
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def insert_or_get(self, content: Content) -> tuple[Content, bool]:
        inserted = self._conn.execute(
            insert(contents)
            .values(
                content_id=content.content_id, sha256=content.sha256, s3_key=content.s3_key, bytes=content.size,
                state=content.state.value, attempts=content.attempts,
                processed_by_user_id=content.processed_by_user_id, processed_at=func.now(),
            )
            .on_conflict_do_nothing(index_elements=["sha256"])
            .returning(contents.c.content_id)
        ).first()
        if inserted is not None:
            return content, True
        # READ COMMITTED: this statement sees the row the concurrent winner just committed.
        row = self._conn.execute(select(contents).where(contents.c.sha256 == content.sha256)).one()
        return _content(row), False


class _Documents(DocumentRepository):
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add(self, document: Document) -> None:
        self._conn.execute(
            documents.insert().values(
                document_id=document.document_id, owner_id=document.owner_id, upload_id=document.upload_id,
                file_name=document.file_name, state=document.state.value, created_at=document.created_at,
            )
        )

    def get_by_upload_for_update(self, upload_id: UploadId) -> Document | None:
        row = self._conn.execute(
            select(documents).where(documents.c.upload_id == upload_id).with_for_update()
        ).first()
        return _document(row) if row else None

    def save(self, document: Document) -> None:
        self._conn.execute(
            update(documents)
            .where(documents.c.document_id == document.document_id)
            .values(content_id=document.content_id, state=document.state.value, failure_reason=document.failure_reason)
        )

    def list_readable_by(self, user_id: UserId) -> list[Document]:
        rows = self._conn.execute(
            select(documents)
            .where(readable_by(user_id), documents.c.archived.is_(False))
            .order_by(documents.c.created_at.desc(), documents.c.document_id)
        )
        return [_document(r) for r in rows]


class _Uploads(UploadRepository):
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def add(self, upload: Upload) -> None:
        self._conn.execute(
            uploads.insert().values(upload_id=upload.upload_id, user_id=upload.user_id, created_at=upload.created_at)
        )

    def record_outcome(self, upload_id: UploadId, size: int, outcome: UploadOutcome) -> None:
        self._conn.execute(
            update(uploads).where(uploads.c.upload_id == upload_id).values(bytes=size, outcome=outcome.value)
        )


class SqlLibraryUnitOfWork(LibraryUnitOfWork):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def __enter__(self) -> Self:
        self._conn = self._engine.connect()
        self._tx = self._conn.begin()
        self.contents = _Contents(self._conn)
        self.documents = _Documents(self._conn)
        self.uploads = _Uploads(self._conn)
        return self

    def commit(self) -> None:
        self._tx.commit()

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        if self._tx.is_active:
            self._tx.rollback()
        self._conn.close()
```

Format with `uv run ruff format` (the dense `.values(...)` calls get reflowed).

- [ ] **Step 5: Integration tests** — update `tests/integration/shared/test_migrations.py` to expect `"0002"` and add:

```python
def test_general_subject_is_seeded() -> None:
    url = Settings().database_url
    upgrade_to_head(url)
    with create_engine(url).connect() as conn:
        name = conn.execute(text("select canonical_name from subjects where normalized_name = 'general'"))
        assert name.scalar_one() == "General"
```

`tests/integration/knowledge/test_sql_library.py` (create empty `__init__.py` alongside):

```python
"""SqlLibraryUnitOfWork against the Compose Postgres (`make up`)."""

import hashlib
import threading
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text

from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.domain.content import Content
from smart_tutor.knowledge.domain.document import DUPLICATE_UPLOAD, Document
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UploadId, UserId

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = Settings().database_url
    upgrade_to_head(url)
    return create_db_engine(url)


def uid() -> str:
    return str(uuid.uuid4())


def start(engine: Engine, owner: str, name: str = "paper.pdf") -> Document:
    upload = Upload(UploadId(uid()), UserId(owner), datetime.now(UTC))
    doc = Document.start_upload(DocumentId(uid()), UserId(owner), upload.upload_id, name, upload.created_at)
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.uploads.add(upload)
        tx.documents.add(doc)
        tx.commit()
    return doc


def test_documents_list_only_for_their_owner(engine: Engine) -> None:
    ada, bob = f"ada-{uid()}", f"bob-{uid()}"
    first, second = start(engine, ada, "first.pdf"), start(engine, ada, "second.pdf")
    start(engine, bob)
    with SqlLibraryUnitOfWork(engine) as tx:
        mine = tx.documents.list_readable_by(UserId(ada))
    assert [d.document_id for d in mine] == [second.document_id, first.document_id]
    assert all(d.owner_id == ada for d in mine)


def test_uncommitted_work_rolls_back(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    with SqlLibraryUnitOfWork(engine) as tx:
        tx.uploads.add(Upload(UploadId(uid()), UserId(owner), datetime.now(UTC)))
    with engine.connect() as conn:
        count = conn.execute(text("select count(*) from uploads where user_id = :u"), {"u": owner}).scalar_one()
    assert count == 0


def test_concurrent_insert_or_get_makes_one_content_row(engine: Engine) -> None:
    sha = hashlib.sha256(uid().encode()).hexdigest()
    barrier = threading.Barrier(2)
    results: list[bool] = []

    def worker(user: str) -> None:
        with SqlLibraryUnitOfWork(engine) as tx:
            barrier.wait()
            _, created = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(user)))
            results.append(created)
            tx.commit()

    threads = [threading.Thread(target=worker, args=(u,)) for u in ("ada", "bob")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert sorted(results) == [False, True]
    with engine.connect() as conn:
        rows = conn.execute(text("select count(*) from contents where sha256 = :s"), {"s": sha}).scalar_one()
    assert rows == 1


def test_duplicate_document_keeps_content_id_null(engine: Engine) -> None:
    owner = f"ada-{uid()}"
    sha = hashlib.sha256(uid().encode()).hexdigest()
    first, second = start(engine, owner), start(engine, owner)
    with SqlLibraryUnitOfWork(engine) as tx:
        content, _ = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(owner)))
        doc = tx.documents.get_by_upload_for_update(first.upload_id)
        assert doc is not None
        doc.link_content(content.content_id)
        tx.documents.save(doc)
        tx.uploads.record_outcome(first.upload_id, 10, UploadOutcome.STORED)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        _, created = tx.contents.insert_or_get(Content.first_upload(ContentId(uid()), sha, 10, UserId(owner)))
        assert not created
        dup = tx.documents.get_by_upload_for_update(second.upload_id)
        assert dup is not None
        dup.fail(DUPLICATE_UPLOAD)
        tx.documents.save(dup)
        tx.commit()
    with SqlLibraryUnitOfWork(engine) as tx:
        by_id = {d.document_id: d for d in tx.documents.list_readable_by(UserId(owner))}
    assert by_id[first.document_id].content_id == content.content_id
    assert (by_id[second.document_id].state, by_id[second.document_id].content_id) == ("failed", None)
```

- [ ] **Step 6: Run** — needs `docker compose up -d postgres` (from the worktree root; uses host port 10400). `cd backend && uv run pytest -m integration tests/integration/shared/test_migrations.py tests/integration/knowledge/test_sql_library.py -q` → PASS. Unit suite and lint still pass.

- [ ] **Step 7: Commit** — `git commit -m "Store contents, documents, and uploads in PostgreSQL"`; body: PRD §9.4 names plus `file_name`/`failure_reason`, insert-or-get via ON CONFLICT, "General" seeded for the next slice.

---

### Task 4: S3 object store and AWS clients

**Files:**
- Modify: `backend/src/smart_tutor/shared/config.py` (+ `s3_path_style: bool = False`)
- Create: `backend/src/smart_tutor/shared/adapters/aws/clients.py`
- Create: `backend/src/smart_tutor/knowledge/adapters/s3_object_store.py`
- Test: `backend/tests/unit/knowledge/test_s3_object_store.py`, `backend/tests/integration/knowledge/test_s3_object_store.py`

**Interfaces:**
- Produces: `s3_client(settings: Settings) -> S3Client`, `sqs_client(settings: Settings) -> SQSClient`; `S3ObjectStore(client: S3Client, bucket: str)`.

- [ ] **Step 1: Settings** — in `Settings`, after `documents_bucket`:

```python
    # LocalStack serves buckets by path (http://localhost:10402/<bucket>); AWS uses virtual-hosted URLs.
    s3_path_style: bool = False
```

- [ ] **Step 2: Clients** — `shared/adapters/aws/clients.py`:

```python
"""boto3 clients. Endpoints come from AWS_ENDPOINT_URL_S3 / AWS_ENDPOINT_URL_SQS (LocalStack) when set."""

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from smart_tutor.shared.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_sqs import SQSClient


def s3_client(settings: Settings) -> "S3Client":
    style = "path" if settings.s3_path_style else "auto"
    return boto3.client(
        "s3", region_name=settings.aws_region, config=Config(signature_version="s3v4", s3={"addressing_style": style})
    )


def sqs_client(settings: Settings) -> "SQSClient":
    return boto3.client("sqs", region_name=settings.aws_region)
```

If `mypy_boto3_s3`/`mypy_boto3_sqs` aren't importable, add `boto3-stubs[s3,sqs]` to the dev group (`uv add --dev "boto3-stubs[s3,sqs]>=1.40"`) and commit `uv.lock`. Import them under `if TYPE_CHECKING:` so the runtime images don't need the stubs.

- [ ] **Step 3: Unit test with botocore's Stubber-free check of the policy** — `tests/unit/knowledge/test_s3_object_store.py` (no network: presigning is local):

```python
import base64
import json

import boto3

from smart_tutor.knowledge.adapters.s3_object_store import S3ObjectStore


def test_presigned_post_binds_key_type_and_size() -> None:
    client = boto3.client(
        "s3", region_name="us-east-1", aws_access_key_id="test", aws_secret_access_key="test",
        endpoint_url="http://localhost:10402",
    )
    post = S3ObjectStore(client, "bucket").presign_post(
        "uploads/ada/u1.pdf", content_type="application/pdf", max_bytes=52_428_800, expires_in=600
    )
    policy = json.loads(base64.b64decode(post.fields["policy"]))
    assert post.fields["key"] == "uploads/ada/u1.pdf"
    assert post.fields["Content-Type"] == "application/pdf"
    assert {"key": "uploads/ada/u1.pdf"} in policy["conditions"]
    assert {"Content-Type": "application/pdf"} in policy["conditions"]
    assert ["content-length-range", 1, 52_428_800] in policy["conditions"]
```

Run → FAIL (module missing).

- [ ] **Step 4: Adapter** — `knowledge/adapters/s3_object_store.py`:

```python
"""ObjectStore on S3 (LocalStack locally)."""

from typing import TYPE_CHECKING

from botocore.exceptions import ClientError

from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, ObjectStore, PresignedPost

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class S3ObjectStore(ObjectStore):
    def __init__(self, client: "S3Client", bucket: str) -> None:
        self._client, self._bucket = client, bucket

    def presign_post(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedPost:
        # boto3 adds {"bucket": …} and {"key": key} to the policy, so the browser can't pick another key.
        post = self._client.generate_presigned_post(
            Bucket=self._bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[{"Content-Type": content_type}, ["content-length-range", 1, max_bytes]],
            ExpiresIn=expires_in,
        )
        return PresignedPost(url=post["url"], fields={k: str(v) for k, v in post["fields"].items()})

    def read(self, key: str) -> bytes:
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                raise ObjectNotFoundError(key) from None
            raise

    def copy(self, source_key: str, dest_key: str) -> None:
        self._client.copy_object(Bucket=self._bucket, Key=dest_key, CopySource={"Bucket": self._bucket, "Key": source_key})

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)
```

Run the unit test → PASS.

- [ ] **Step 5: Integration test against LocalStack** — `tests/integration/knowledge/test_s3_object_store.py`:

```python
"""S3ObjectStore against LocalStack (`make up`): the POST policy is enforced by S3, not by our code."""

import uuid

import boto3
import httpx
import pytest
from botocore.config import Config

from smart_tutor.knowledge.adapters.s3_object_store import S3ObjectStore
from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, PresignedPost

pytestmark = pytest.mark.integration

ENDPOINT = "http://localhost:10402"
BUCKET = "smart-tutor-documents"


@pytest.fixture
def store() -> S3ObjectStore:
    client = boto3.client(
        "s3", region_name="us-east-1", endpoint_url=ENDPOINT, aws_access_key_id="test",
        aws_secret_access_key="test", config=Config(s3={"addressing_style": "path"}),
    )
    return S3ObjectStore(client, BUCKET)


def post(p: PresignedPost, data: bytes, content_type: str = "application/pdf", **override: str) -> httpx.Response:
    fields = {**p.fields, "Content-Type": content_type, **override}
    return httpx.post(p.url, data=fields, files={"file": ("x.pdf", data, content_type)})


def presign(store: S3ObjectStore, max_bytes: int = 1024) -> tuple[str, PresignedPost]:
    key = f"uploads/it-{uuid.uuid4()}/{uuid.uuid4()}.pdf"
    return key, store.presign_post(key, content_type="application/pdf", max_bytes=max_bytes, expires_in=600)


def test_a_pdf_within_the_limit_is_stored_then_copied_and_deleted(store: S3ObjectStore) -> None:
    key, p = presign(store)
    assert post(p, b"%PDF ok").status_code in (200, 201, 204)
    assert store.read(key) == b"%PDF ok"
    dest = f"contents/it-{uuid.uuid4()}.pdf"
    store.copy(key, dest)
    store.delete(key)
    assert store.read(dest) == b"%PDF ok"
    with pytest.raises(ObjectNotFoundError):
        store.read(key)
    store.delete(dest)


def test_over_the_size_limit_is_rejected(store: S3ObjectStore) -> None:
    key, p = presign(store, max_bytes=1024)
    assert post(p, b"x" * 1025).status_code in (400, 403)
    with pytest.raises(ObjectNotFoundError):
        store.read(key)


def test_another_content_type_is_rejected(store: S3ObjectStore) -> None:
    key, p = presign(store)
    assert post(p, b"hello", content_type="text/plain").status_code in (400, 403)


def test_another_key_is_rejected(store: S3ObjectStore) -> None:
    _, p = presign(store)
    other = f"uploads/someone-else/{uuid.uuid4()}.pdf"
    assert post(p, b"%PDF", key=other).status_code in (400, 403)
    with pytest.raises(ObjectNotFoundError):
        store.read(other)
```

Run: `docker compose up -d localstack` then `uv run pytest -m integration tests/integration/knowledge/test_s3_object_store.py -q` → PASS. If LocalStack does not enforce a condition, record which one in the PR description and keep the unit-level policy test; do not weaken the assertion silently.

- [ ] **Step 6: Commit** — `git commit -m "Presign PDF uploads and store contents in S3"`.

---

### Task 5: API routes `POST /uploads` and `GET /documents`

**Files:**
- Create: `backend/src/smart_tutor/shared/adapters/clock.py`, `backend/src/smart_tutor/apps/api/services.py`, `backend/src/smart_tutor/apps/api/routes/knowledge.py`
- Modify: `backend/src/smart_tutor/apps/api/main.py`, `backend/src/smart_tutor/apps/api/deps.py`
- Test: `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/isolation/test_documents.py`
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`

**Interfaces:**
- Consumes: Task 2 services; Task 3 `SqlLibraryUnitOfWork`, `create_db_engine`; Task 4 `S3ObjectStore`, `s3_client`.
- Produces: `create_app(settings=None, verifier=None, services: ApiServices | None = None)`; `ApiServices(uploads: UploadService, documents: DocumentService)`; `build_services(settings) -> ApiServices`; HTTP: `POST /uploads` (operationId `start_upload`, body `{file_name}`, 201 → `{document_id, upload_id, url, fields}`), `GET /documents` (operationId `list_documents`, 200 → `[{document_id, title, state, failure_reason, created_at}]`); generated web functions `startUpload`, `listDocuments`, types `StartUploadResponse`, `DocumentResponse`.

- [ ] **Step 1: `SystemClock`** — `shared/adapters/clock.py`:

```python
from datetime import UTC, datetime

from smart_tutor.shared.ports.clock import Clock


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(UTC)
```

- [ ] **Step 2: Failing route tests** — `tests/unit/apps/api/test_knowledge_routes.py`:

```python
import pytest
from fastapi.testclient import TestClient

from fakes import FakeObjectStore, FakeTokenVerifier, FixedClock, InMemoryLibrary
from smart_tutor.apps.api.main import create_app
from smart_tutor.apps.api.services import ApiServices
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

AUTH = {"Authorization": "Bearer ada-token"}


@pytest.fixture
def client() -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add("ada-token", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library = InMemoryLibrary()
    services = ApiServices(
        uploads=UploadService(library.unit_of_work, FakeObjectStore(), FixedClock()),
        documents=DocumentService(library.unit_of_work),
    )
    return TestClient(create_app(Settings(), verifier=verifier, services=services))


def test_start_upload_returns_the_presigned_post(client: TestClient) -> None:
    r = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH)
    assert r.status_code == 201
    body = r.json()
    assert body["url"] == "http://s3.test/bucket"
    assert body["fields"]["key"] == f"uploads/ada/{body['upload_id']}.pdf"
    assert set(body) == {"document_id", "upload_id", "url", "fields"}


def test_the_new_document_is_listed_as_processing(client: TestClient) -> None:
    started = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH).json()
    [doc] = client.get("/documents", headers=AUTH).json()
    assert doc["document_id"] == started["document_id"]
    assert (doc["title"], doc["state"], doc["failure_reason"]) == ("paper.pdf", "processing", None)
    assert doc["created_at"].startswith("2026-10-04T09:00:00")


def test_blank_file_name_is_422(client: TestClient) -> None:
    assert client.post("/uploads", json={"file_name": "   "}, headers=AUTH).status_code == 422
    assert client.post("/uploads", json={}, headers=AUTH).status_code == 422


def test_openapi_names_the_operations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/uploads"]["post"]["operationId"] == "start_upload"
    assert paths["/documents"]["get"]["operationId"] == "list_documents"
```

Isolation test — `tests/isolation/test_documents.py`:

```python
"""US-12: a learner never sees another learner's documents, and can't get a presigned POST for their key."""

from fastapi.testclient import TestClient

from fakes import FakeObjectStore, FakeTokenVerifier, FixedClock, InMemoryLibrary
from smart_tutor.apps.api.main import create_app
from smart_tutor.apps.api.services import ApiServices
from smart_tutor.knowledge.application import DocumentService, IngestionService, UploadService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}


def setup() -> tuple[TestClient, FakeObjectStore, IngestionService]:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    library, objects = InMemoryLibrary(), FakeObjectStore()
    services = ApiServices(
        uploads=UploadService(library.unit_of_work, objects, FixedClock()),
        documents=DocumentService(library.unit_of_work),
    )
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))
    return client, objects, IngestionService(library.unit_of_work, objects)


def test_b_never_sees_a_documents_in_any_state() -> None:
    client, objects, ingestion = setup()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    client.post("/uploads", json={"file_name": "a2.pdf"}, headers=A)  # stays processing
    objects.objects[stored["fields"]["key"]] = b"%PDF a"
    ingestion.ingest_upload(stored["fields"]["key"])

    assert client.get("/documents", headers=B).json() == []
    assert client.get("/documents", headers=B, params={"user_id": "learner-a"}).json() == []
    assert {d["title"] for d in client.get("/documents", headers=A).json()} == {"a1.pdf", "a2.pdf"}


def test_b_cannot_get_a_presigned_post_for_a_key() -> None:
    client, objects, _ = setup()
    forged = client.post(
        "/uploads", json={"file_name": "x.pdf", "user_id": "learner-a", "key": "uploads/learner-a/x.pdf"}, headers=B
    )
    assert forged.status_code == 422  # unknown fields are refused, not ignored
    own = client.post("/uploads", json={"file_name": "x.pdf"}, headers=B, params={"user_id": "learner-a"}).json()
    assert own["fields"]["key"].startswith("uploads/learner-b/")
    assert all(key.startswith("uploads/learner-b/") for key, *_ in objects.presigned)
```

Run → FAIL (`ApiServices` missing).

- [ ] **Step 3: Services wiring** — `apps/api/services.py`:

```python
"""Services the API's routes call, built once per process (tests pass fakes to create_app instead)."""

from dataclasses import dataclass

from smart_tutor.knowledge.adapters.s3_object_store import S3ObjectStore
from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.adapters.aws.clients import s3_client
from smart_tutor.shared.adapters.clock import SystemClock
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.config import Settings


@dataclass(frozen=True)
class ApiServices:
    uploads: UploadService
    documents: DocumentService


def build_services(settings: Settings) -> ApiServices:
    engine = create_db_engine(settings.database_url)

    def library() -> SqlLibraryUnitOfWork:
        return SqlLibraryUnitOfWork(engine)

    objects = S3ObjectStore(s3_client(settings), settings.documents_bucket)
    return ApiServices(uploads=UploadService(library, objects, SystemClock()), documents=DocumentService(library))
```

- [ ] **Step 4: `create_app`** — in `main.py` add parameter `services: ApiServices | None = None`; after `app.state.verifier = verifier` add `if services is not None: app.state.services = services`; in the lifespan's real branch, before `async with httpx…`, add `if services is None: app.state.services = build_services(settings)`. Register `include_protected(app, knowledge.router)` after accounts. Import `from smart_tutor.apps.api.routes import accounts, knowledge` and `from smart_tutor.apps.api.services import ApiServices, build_services`.

The lifespan becomes:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if verifier is not None:
            yield
            return
        if not settings.keycloak_client_secret.get_secret_value():
            raise RuntimeError("SMART_TUTOR_KEYCLOAK_CLIENT_SECRET is not set")
        if services is None:
            app.state.services = build_services(settings)
        async with httpx.AsyncClient(timeout=5) as http:
            app.state.verifier = keycloak_verifier(settings, http)
            yield
```

- [ ] **Step 5: deps** — append to `apps/api/deps.py`:

```python
def _services(request: Request) -> "ApiServices":
    services: ApiServices = request.app.state.services
    return services


def _uploads(request: Request) -> UploadService:
    return _services(request).uploads


def _documents(request: Request) -> DocumentService:
    return _services(request).documents


Uploads = Annotated[UploadService, Depends(_uploads)]
Documents = Annotated[DocumentService, Depends(_documents)]
```

with imports `from smart_tutor.apps.api.services import ApiServices` and `from smart_tutor.knowledge.application import DocumentService, UploadService` (drop the quotes once imported).

- [ ] **Step 6: Routes** — `apps/api/routes/knowledge.py`:

```python
"""Library routes (knowledge module): start an upload, list the caller's documents."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from smart_tutor.apps.api.deps import CurrentPrincipal, Documents, Uploads
from smart_tutor.knowledge.application import InvalidFileNameError

router = APIRouter(tags=["knowledge"])


class StartUploadRequest(BaseModel):
    # No user id or key: the key comes from the token (PRD §9.3). Unknown fields are refused.
    model_config = ConfigDict(extra="forbid")
    file_name: str = Field(min_length=1, max_length=1024)


class StartUploadResponse(BaseModel):
    document_id: str
    upload_id: str
    url: str
    fields: dict[str, str]


class DocumentResponse(BaseModel):
    document_id: str
    title: str
    state: Literal["processing", "awaiting_subjects", "ready", "failed"]
    failure_reason: str | None
    created_at: datetime


@router.post("/uploads", operation_id="start_upload", status_code=status.HTTP_201_CREATED)
def start_upload(body: StartUploadRequest, principal: CurrentPrincipal, uploads: Uploads) -> StartUploadResponse:
    try:
        started = uploads.start_upload(principal.user_id, body.file_name)
    except InvalidFileNameError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    return StartUploadResponse(
        document_id=started.document_id, upload_id=started.upload_id, url=started.url, fields=started.fields
    )


@router.get("/documents", operation_id="list_documents")
def list_documents(principal: CurrentPrincipal, documents: Documents) -> list[DocumentResponse]:
    return [
        DocumentResponse(
            document_id=d.document_id, title=d.title, state=d.state,  # type: ignore[arg-type]
            failure_reason=d.failure_reason, created_at=d.created_at,
        )
        for d in documents.list_documents(principal.user_id)
    ]
```

(Prefer narrowing `DocumentView.state` to the same `Literal` in Task 2's `DocumentView` if mypy needs it, instead of the ignore.)

- [ ] **Step 7: Run** — `uv run pytest -q` (route, isolation, auth `test_every_route_requires_a_token` now covers the new routes) → PASS except `test_web_openapi_snapshot_is_current`.

- [ ] **Step 8: Regenerate the web client** — from `backend/`: `uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Then `uv run pytest -q` → all PASS; `cd web && npm run build` → PASS.

- [ ] **Step 9: Commit** — `git commit -m "Add POST /uploads and GET /documents"`; include the regenerated `web/src/api/`.

---

### Task 6: Ingestion worker

**Files:**
- Create: `backend/src/smart_tutor/shared/ports/message_queue.py`, `backend/src/smart_tutor/shared/adapters/aws/sqs_queue.py`, `backend/src/smart_tutor/apps/worker/events.py`
- Modify: `backend/src/smart_tutor/apps/worker/main.py`
- Create: `backend/tests/fakes/queue.py` (export `FakeQueue` from `fakes/__init__.py`)
- Test: `backend/tests/unit/apps/worker/__init__.py`, `backend/tests/unit/apps/worker/test_worker.py`

**Interfaces:**
- Consumes: Task 2 `IngestionService`; Task 3/4 adapters.
- Produces: `QueueMessage(receipt: str, body: str)`, `MessageQueue.receive() -> list[QueueMessage]`, `.delete(message)`; `SqsMessageQueue(client, queue_url, wait_seconds=20)`; `upload_keys(body: str) -> list[str]`; `run_once(queue, ingestion) -> int`.

- [ ] **Step 1: Port** — `shared/ports/message_queue.py`:

```python
"""A work queue (SQS): receive, then delete once handled; undeleted messages come back after a timeout."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class QueueMessage:
    receipt: str
    body: str


class MessageQueue(ABC):
    @abstractmethod
    def receive(self) -> list[QueueMessage]:
        """Wait briefly for messages, oldest first; may return none."""

    @abstractmethod
    def delete(self, message: QueueMessage) -> None: ...
```

- [ ] **Step 2: Fake** — `tests/fakes/queue.py`:

```python
from smart_tutor.shared.ports.message_queue import MessageQueue, QueueMessage


class FakeQueue(MessageQueue):
    def __init__(self, *bodies: str) -> None:
        self.waiting = [QueueMessage(f"r{i}", body) for i, body in enumerate(bodies)]
        self.deleted: list[QueueMessage] = []

    def receive(self) -> list[QueueMessage]:
        return self.waiting[:1]  # one at a time, in order

    def delete(self, message: QueueMessage) -> None:
        self.waiting.remove(message)
        self.deleted.append(message)
```

- [ ] **Step 3: Failing tests** — `tests/unit/apps/worker/test_worker.py`:

```python
import json

from fakes import FakeObjectStore, FakeQueue, FixedClock, InMemoryLibrary
from smart_tutor.apps.worker.events import upload_keys
from smart_tutor.apps.worker.main import run_once
from smart_tutor.knowledge.application import IngestionService, UploadService
from smart_tutor.shared.domain.ids import UserId


def s3_event(key: str, name: str = "ObjectCreated:Post") -> str:
    return json.dumps({"Records": [{"eventName": name, "s3": {"bucket": {"name": "b"}, "object": {"key": key}}}]})


def world() -> tuple[InMemoryLibrary, FakeObjectStore, UploadService, IngestionService]:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    return library, objects, UploadService(library.unit_of_work, objects, FixedClock()), IngestionService(
        library.unit_of_work, objects
    )


def test_upload_keys_reads_created_events_and_decodes_keys() -> None:
    assert upload_keys(s3_event("uploads/ada/u+1%21.pdf")) == ["uploads/ada/u 1!.pdf"]
    assert upload_keys(s3_event("uploads/ada/u1.pdf", name="ObjectRemoved:Delete")) == []
    assert upload_keys(json.dumps({"Event": "s3:TestEvent"})) == []
    assert upload_keys("not json") == []


def test_an_upload_event_is_ingested_and_its_message_deleted() -> None:
    library, objects, uploads, ingestion = world()
    started = uploads.start_upload(UserId("ada"), "paper.pdf")
    objects.objects[started.fields["key"]] = b"%PDF"
    queue = FakeQueue(s3_event(started.fields["key"]))

    assert run_once(queue, ingestion) == 1
    assert queue.waiting == [] and len(queue.deleted) == 1
    assert library.state.documents[started.document_id].content_id is not None


def test_s3_test_event_is_deleted_without_ingesting() -> None:
    library, _, _, ingestion = world()
    queue = FakeQueue(json.dumps({"Event": "s3:TestEvent"}))
    run_once(queue, ingestion)
    assert len(queue.deleted) == 1 and library.commits == 0


def test_a_failing_message_stays_for_redelivery_and_the_next_is_handled() -> None:
    library, objects, uploads, ingestion = world()
    started = uploads.start_upload(UserId("ada"), "paper.pdf")
    objects.objects[started.fields["key"]] = b"%PDF"

    def broken(source_key: str, dest_key: str) -> None:
        raise RuntimeError("S3 down")

    objects.copy = broken  # type: ignore[method-assign]
    queue = FakeQueue(s3_event(started.fields["key"]))
    run_once(queue, ingestion)
    assert len(queue.waiting) == 1 and queue.deleted == []


def test_no_messages_is_fine() -> None:
    *_, ingestion = world()
    assert run_once(FakeQueue(), ingestion) == 0
```

Run → FAIL (modules missing).

- [ ] **Step 4: Events** — `apps/worker/events.py`:

```python
"""S3 event notifications (via SQS) → upload keys."""

import json
import logging
from typing import Any
from urllib.parse import unquote_plus

logger = logging.getLogger(__name__)


def upload_keys(body: str) -> list[str]:
    """Keys of created objects. S3 test events and unreadable bodies give none (and are then deleted)."""
    try:
        event: Any = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("dropping a message that isn't JSON")
        return []
    records = event.get("Records", []) if isinstance(event, dict) else []
    return [
        unquote_plus(r["s3"]["object"]["key"])  # S3 URL-encodes keys in events
        for r in records
        if str(r.get("eventName", "")).startswith("ObjectCreated:")
    ]
```

- [ ] **Step 5: Loop and entrypoint** — `apps/worker/main.py`:

```python
"""Ingestion worker: read S3 upload events from SQS in order and hand each upload to IngestionService (PRD §9.5).

One message at a time (plain FIFO, no per-learner fairness). A message is deleted only after it was handled;
a failure leaves it to come back after the visibility timeout, and the queue's redrive policy moves it to the
DLQ after 5 receives.
"""

import logging
import signal
import threading

from smart_tutor.apps.worker.events import upload_keys
from smart_tutor.knowledge.adapters.s3_object_store import S3ObjectStore
from smart_tutor.knowledge.adapters.sql_library import SqlLibraryUnitOfWork
from smart_tutor.knowledge.application import IngestionService
from smart_tutor.shared.adapters.aws.clients import s3_client, sqs_client
from smart_tutor.shared.adapters.aws.sqs_queue import SqsMessageQueue
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.config import Settings
from smart_tutor.shared.ports.message_queue import MessageQueue

logger = logging.getLogger(__name__)


def run_once(queue: MessageQueue, ingestion: IngestionService) -> int:
    messages = queue.receive()
    for message in messages:
        try:
            for key in upload_keys(message.body):
                ingestion.ingest_upload(key)
        except Exception:
            logger.exception("ingestion failed; the message will be redelivered")
            continue
        queue.delete(message)
    return len(messages)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = Settings()
    engine = create_db_engine(settings.database_url)

    def library() -> SqlLibraryUnitOfWork:
        return SqlLibraryUnitOfWork(engine)

    ingestion = IngestionService(library, S3ObjectStore(s3_client(settings), settings.documents_bucket))
    queue = SqsMessageQueue(sqs_client(settings), settings.ingest_queue_url)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    logger.info("worker started")
    while not stop.is_set():
        run_once(queue, ingestion)


if __name__ == "__main__":
    main()
```

`shared/adapters/aws/sqs_queue.py`:

```python
"""MessageQueue on SQS (long polling)."""

from typing import TYPE_CHECKING

from smart_tutor.shared.ports.message_queue import MessageQueue, QueueMessage

if TYPE_CHECKING:
    from mypy_boto3_sqs import SQSClient


class SqsMessageQueue(MessageQueue):
    def __init__(self, client: "SQSClient", queue_url: str, wait_seconds: int = 20) -> None:
        self._client, self._url, self._wait = client, queue_url, wait_seconds

    def receive(self) -> list[QueueMessage]:
        response = self._client.receive_message(
            QueueUrl=self._url, MaxNumberOfMessages=1, WaitTimeSeconds=self._wait
        )
        return [QueueMessage(m["ReceiptHandle"], m["Body"]) for m in response.get("Messages", [])]

    def delete(self, message: QueueMessage) -> None:
        self._client.delete_message(QueueUrl=self._url, ReceiptHandle=message.receipt)
```

- [ ] **Step 6: Run** — `uv run pytest -q && uv run mypy && PYTHONUTF8=1 uv run lint-imports` → PASS.

- [ ] **Step 7: Commit** — `git commit -m "Run the ingestion worker on S3 upload events"`.

---

### Task 7: Library page — upload and processing rows

**Files:**
- Create: `web/src/api/documents.ts`, `web/src/api/documents.test.ts`
- Modify: `web/src/components/StateBadge/StateBadge.tsx`, `.module.css`, `.test.tsx`
- Create: `web/src/features/library/useDocuments.ts`, `DocumentTable.tsx`, `DocumentTable.module.css`, `LibraryPage.module.css`, `LibraryPage.test.tsx`
- Modify: `web/src/features/library/LibraryPage.tsx`

**Interfaces:**
- Consumes: generated `listDocuments`, `startUpload`, types `DocumentResponse`, `StartUploadResponse` (Task 5).
- Produces: `loadDocuments(apiClient?) -> Promise<DocumentResponse[]>`; `uploadPdf(file: File, apiClient?, post?: typeof fetch) -> Promise<void>`; `useDocuments(load, pollMs)`; `LibraryPage({ load?, upload?, pollMs? })`.

Read first: `DESIGN.md` (Document states, accessibility), the rendered `library-first-processing` state (`make design-shots ROUND=v0.4 STATES="library-first-processing" THEME=both`).

- [ ] **Step 1: API wrapper tests** — `web/src/api/documents.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import { SessionExpiredError } from "../auth/authClient";
import { configureApiClient } from "./client";
import { loadDocuments, uploadPdf } from "./documents";
import { createClient, createConfig } from "./generated/client";

function api(handler: (request: Request) => Response) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => handler(input as Request));
  const apiClient = createClient(createConfig({ fetch }));
  configureApiClient({ baseUrl: "http://api.test", getToken: async () => "t", onUnauthorized: vi.fn(), apiClient });
  return { apiClient, fetch };
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

describe("loadDocuments", () => {
  it("returns the caller's documents", async () => {
    const doc = { document_id: "d1", title: "a.pdf", state: "processing", failure_reason: null, created_at: "2026-10-04T09:00:00Z" };
    const { apiClient } = api(() => json([doc]));
    await expect(loadDocuments(apiClient)).resolves.toEqual([doc]);
  });

  it("rejects with SessionExpiredError on 401", async () => {
    const { apiClient } = api(() => json({ detail: "Not authenticated" }, 401));
    await expect(loadDocuments(apiClient)).rejects.toBeInstanceOf(SessionExpiredError);
  });
});

describe("uploadPdf", () => {
  const started = { document_id: "d1", upload_id: "u1", url: "http://s3.test/bucket", fields: { key: "uploads/ada/u1.pdf", policy: "p" } };

  it("asks for a presigned POST with the file name, then posts the fields and the file last", async () => {
    const { apiClient, fetch } = api(() => json(started, 201));
    const post = vi.fn(async () => new Response(null, { status: 204 }));
    const file = new File(["%PDF"], "paper.pdf", { type: "application/pdf" });

    await uploadPdf(file, apiClient, post);

    const request = fetch.mock.calls[0]![0] as Request;
    expect(request.url).toBe("http://api.test/uploads");
    expect(await request.json()).toEqual({ file_name: "paper.pdf" });
    const [url, init] = post.mock.calls[0]! as unknown as [string, RequestInit];
    expect(url).toBe("http://s3.test/bucket");
    const form = init.body as FormData;
    expect([...form.keys()]).toEqual(["key", "policy", "file"]);
    expect(form.get("file")).toBe(file);
  });

  it("rejects when S3 refuses the file", async () => {
    const { apiClient } = api(() => json(started, 201));
    const post = vi.fn(async () => new Response("<Error/>", { status: 403 }));
    await expect(uploadPdf(new File(["x"], "x.pdf"), apiClient, post)).rejects.toThrow("403");
  });
});
```

Run `cd web && npx vitest run src/api/documents.test.ts` → FAIL (module missing).

- [ ] **Step 2: Implement** — `web/src/api/documents.ts`:

```ts
import { SessionExpiredError } from "../auth/authClient";
import type { Client } from "./generated/client";
import { client } from "./generated/client.gen";
import { listDocuments, startUpload } from "./generated/sdk.gen";
import type { DocumentResponse } from "./generated/types.gen";

export type { DocumentResponse };

function sessionOver(error: unknown, response: Response | undefined): boolean {
  return error instanceof SessionExpiredError || response?.status === 401;
}

export async function loadDocuments(apiClient: Client = client): Promise<DocumentResponse[]> {
  const { data, error, response } = await listDocuments({ client: apiClient, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /documents failed (${response?.status ?? "no response"})`);
  return data;
}

// The API presigns a POST for this learner's key; the browser then sends the file straight to S3 (PRD §9.3).
export async function uploadPdf(file: File, apiClient: Client = client, post: typeof fetch = fetch): Promise<void> {
  const { data, error, response } = await startUpload({ client: apiClient, body: { file_name: file.name }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`POST /uploads failed (${response?.status ?? "no response"})`);
  const form = new FormData();
  for (const [name, value] of Object.entries(data.fields)) form.append(name, value);
  form.append("file", file); // S3 ignores fields after the file
  const stored = await post(data.url, { method: "POST", body: form });
  if (!stored.ok) throw new Error(`Upload to storage failed (${stored.status})`);
}
```

Run → PASS.

- [ ] **Step 3: StateBadge gains "Choose subjects"** — extend the type and `LOOK` (DESIGN.md: needs action uses `--attn-soft` / `--attn`):

```tsx
import { CircleAlert, CircleCheck, ListChecks, LoaderCircle, type LucideIcon } from "lucide-react";
// …
export type DocumentState = "processing" | "awaiting_subjects" | "ready" | "failed";

const LOOK: Record<DocumentState, { label: string; icon: LucideIcon }> = {
  processing: { label: "Processing", icon: LoaderCircle },
  awaiting_subjects: { label: "Choose subjects", icon: ListChecks },
  ready: { label: "Ready", icon: CircleCheck },
  failed: { label: "Failed", icon: CircleAlert },
};
```

CSS: `.awaiting_subjects { background: var(--attn-soft); color: var(--attn); }`. Update the comment above the type ("uploading" and "archived" arrive with their stories). Add `["awaiting_subjects", "Choose subjects"]` to the test table.

- [ ] **Step 4: Page tests** — `web/src/features/library/LibraryPage.test.tsx`:

```tsx
import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { DocumentResponse } from "../../api/documents";
import { LibraryPage } from "./LibraryPage";

const today = new Date().toISOString();
const processing: DocumentResponse = { document_id: "d1", title: "lewis-rag-2020.pdf", state: "processing", failure_reason: null, created_at: today };
const duplicate: DocumentResponse = { document_id: "d2", title: "copy.pdf", state: "failed", failure_reason: "Duplicate uploads aren't supported yet", created_at: today };

afterEach(() => vi.useRealTimers());

describe("LibraryPage", () => {
  it("shows the first-run card when the library is empty", async () => {
    render(<LibraryPage load={async () => []} upload={vi.fn()} />);
    expect(await screen.findByText("Upload your first document")).toBeVisible();
    expect(screen.getByRole("button", { name: "Choose PDFs" })).toBeEnabled();
  });

  it("lists a processing document by its file name with the subjects hint", async () => {
    render(<LibraryPage load={async () => [processing]} upload={vi.fn()} />);
    const row = (await screen.findByText("lewis-rag-2020.pdf")).closest("tr")!;
    expect(within(row).getByText("Processing")).toBeVisible();
    expect(within(row).getByText("Not chosen yet")).toBeVisible();
    expect(within(row).getByText("You can choose subjects when processing finishes.")).toBeVisible();
    expect(within(row).getByText("Today")).toBeVisible();
  });

  it("shows a failed document's reason", async () => {
    render(<LibraryPage load={async () => [duplicate]} upload={vi.fn()} />);
    const row = (await screen.findByText("copy.pdf")).closest("tr")!;
    expect(within(row).getByText("Failed")).toBeVisible();
    expect(within(row).getByText("Duplicate uploads aren't supported yet")).toBeVisible();
  });

  it("uploads the picked PDF and refreshes the list", async () => {
    const load = vi.fn().mockResolvedValueOnce([]).mockResolvedValue([processing]);
    const upload = vi.fn(async () => {});
    render(<LibraryPage load={load} upload={upload} />);
    await screen.findByText("Upload your first document");
    const file = new File(["%PDF"], "lewis-rag-2020.pdf", { type: "application/pdf" });
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), file);
    expect(upload).toHaveBeenCalledWith(file);
    expect(await screen.findByText("lewis-rag-2020.pdf")).toBeVisible();
  });

  it("shows an error when the upload fails", async () => {
    const upload = vi.fn(async () => {
      throw new Error("Upload to storage failed (403)");
    });
    render(<LibraryPage load={async () => []} upload={upload} />);
    await screen.findByText("Upload your first document");
    await userEvent.upload(screen.getByLabelText("Upload PDFs"), new File(["x"], "big.pdf", { type: "application/pdf" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Couldn't upload big.pdf. Try again.");
  });

  it("refreshes every 2 seconds", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const load = vi.fn(async () => [processing]);
    render(<LibraryPage load={load} upload={vi.fn()} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4100);
    });
    expect(load.mock.calls.length).toBeGreaterThanOrEqual(3);
  });
});
```

Run → FAIL.

- [ ] **Step 5: Polling hook** — `web/src/features/library/useDocuments.ts`:

```ts
import { useCallback, useEffect, useState } from "react";

import type { DocumentResponse } from "../../api/documents";

export type DocumentsState = { documents: DocumentResponse[] | null; unavailable: boolean; refresh: () => Promise<void> };

// Loads the library now and every `pollMs`, so processing states update without a reload.
export function useDocuments(load: () => Promise<DocumentResponse[]>, pollMs: number): DocumentsState {
  const [documents, setDocuments] = useState<DocumentResponse[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);

  const refresh = useCallback(async () => {
    try {
      setDocuments(await load());
      setUnavailable(false);
    } catch {
      setUnavailable(true); // a 401 is handled by the API client (SessionProvider shows "Please sign in again")
    }
  }, [load]);

  useEffect(() => {
    void refresh();
    const timer = setInterval(() => void refresh(), pollMs);
    return () => clearInterval(timer);
  }, [refresh, pollMs]);

  return { documents, unavailable, refresh };
}
```

- [ ] **Step 6: Table** — `web/src/features/library/DocumentTable.tsx`:

```tsx
import { FileText } from "lucide-react";

import type { DocumentResponse } from "../../api/documents";
import { StateBadge } from "../../components/StateBadge/StateBadge";
import styles from "./DocumentTable.module.css";

function uploadedOn(iso: string, now = new Date()): string {
  const date = new Date(iso);
  if (date.toDateString() === now.toDateString()) return "Today";
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}

function StateCell({ doc }: { doc: DocumentResponse }) {
  return (
    <>
      <StateBadge state={doc.state} />
      {doc.state === "processing" && <p className={styles.hint}>You can choose subjects when processing finishes.</p>}
      {doc.state === "failed" && doc.failure_reason && <p className={styles.reason}>{doc.failure_reason}</p>}
    </>
  );
}

export function DocumentTable({ documents }: { documents: DocumentResponse[] }) {
  return (
    <table className={styles.table}>
      <thead>
        <tr>
          <th scope="col">Document</th>
          <th scope="col">Subjects</th>
          <th scope="col">State</th>
          <th scope="col">Uploaded</th>
        </tr>
      </thead>
      <tbody>
        {documents.map((doc) => (
          <tr key={doc.document_id}>
            <td>
              <span className={styles.doc}>
                <span className={styles.fileIcon}>
                  <FileText strokeWidth={1.5} aria-hidden="true" />
                </span>
                <span className={styles.title}>{doc.title}</span>
              </span>
            </td>
            <td className={styles.muted}>Not chosen yet</td>
            <td>
              <StateCell doc={doc} />
            </td>
            <td className={styles.muted}>{uploadedOn(doc.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

`DocumentTable.module.css` (tokens only, matches the mockup: bordered surface card, uppercase header on `--surface-2`):

```css
.table {
  width: 100%; border-collapse: separate; border-spacing: 0;
  background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden;
}
.table th {
  text-align: left; padding: var(--sp-3) var(--sp-5); background: var(--surface-2); color: var(--text-2);
  font-size: var(--fs-12); font-weight: 650; letter-spacing: 0.06em; text-transform: uppercase;
  border-bottom: 1px solid var(--border);
}
.table td { padding: var(--sp-4) var(--sp-5); vertical-align: middle; border-bottom: 1px solid var(--border); }
.table tbody tr:last-child td { border-bottom: 0; }
.doc { display: flex; align-items: center; gap: var(--sp-3); }
.fileIcon {
  display: inline-grid; place-items: center; width: 32px; height: 36px; flex: none;
  border: 1px solid var(--border-strong); border-radius: var(--r-sm); color: var(--text-2);
}
.fileIcon svg { width: 18px; height: 18px; }
.title { font-weight: 650; color: var(--text); overflow-wrap: anywhere; }
.muted { color: var(--text-2); }
.hint, .reason { margin: var(--sp-1) 0 0; font-size: var(--fs-12); max-width: 22ch; }
.hint { color: var(--text-2); }
.reason { color: var(--danger); }
```

If a token named here (e.g. `--sp-5`, `--fs-12`) is missing from `web/src/styles/tokens.css`, use the nearest existing one; do not add literal colors or sizes.

- [ ] **Step 7: Page** — `web/src/features/library/LibraryPage.tsx`:

```tsx
import { Upload } from "lucide-react";
import { useRef, useState, type ChangeEvent } from "react";

import { loadDocuments, uploadPdf, type DocumentResponse } from "../../api/documents";
import { Button } from "../../components/Button/Button";
import { EmptyState } from "../../components/EmptyState/EmptyState";
import { PageHeader } from "../../components/PageHeader/PageHeader";
import { DocumentTable } from "./DocumentTable";
import styles from "./LibraryPage.module.css";
import { useDocuments } from "./useDocuments";

type Props = {
  load?: () => Promise<DocumentResponse[]>;
  upload?: (file: File) => Promise<void>;
  pollMs?: number;
};

const defaultUpload = (file: File) => uploadPdf(file);

// Library with a plain file picker (US-2 first slice). Drop zone, upload tray, tabs and filters come later.
export function LibraryPage({ load = loadDocuments, upload = defaultUpload, pollMs = 2000 }: Props) {
  const { documents, unavailable, refresh } = useDocuments(load, pollMs);
  const input = useRef<HTMLInputElement>(null);
  const [status, setStatus] = useState("");
  const [failed, setFailed] = useState<string | null>(null);

  async function onPick(event: ChangeEvent<HTMLInputElement>) {
    const files = [...(event.target.files ?? [])];
    event.target.value = ""; // picking the same file again fires change again
    for (const file of files) {
      setFailed(null);
      setStatus(`Uploading ${file.name}…`);
      try {
        await upload(file);
        setStatus(`Uploaded ${file.name}. Processing.`);
      } catch {
        setStatus("");
        setFailed(file.name);
      }
      await refresh();
    }
  }

  const pick = () => input.current?.click();

  return (
    <>
      <PageHeader
        title="Library"
        description="Your documents. They're private to you, and the tutor answers only from them."
        actions={documents?.length ? <Button variant="primary" icon={Upload} onClick={pick}>Upload</Button> : undefined}
      />
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        multiple
        hidden
        aria-label="Upload PDFs"
        onChange={(e) => void onPick(e)}
      />
      <p role="status" aria-live="polite" className={styles.status}>
        {status}
      </p>
      {failed && (
        <p role="alert" className={styles.error}>
          Couldn't upload {failed}. Try again.
        </p>
      )}
      {unavailable && documents === null && (
        <p role="alert" className={styles.error}>
          Can't load your library. Retrying…
        </p>
      )}
      {documents?.length === 0 && (
        <EmptyState
          variant="dropzone"
          icon={Upload}
          title="Upload your first document"
          note="You can pick several PDFs at once."
          actions={
            <Button variant="primary" size="lg" icon={Upload} onClick={pick}>
              Choose PDFs
            </Button>
          }
        >
          <p>PDFs up to 50 MB and 500 pages. Your documents stay private to you.</p>
        </EmptyState>
      )}
      {documents && documents.length > 0 && <DocumentTable documents={documents} />}
    </>
  );
}
```

`LibraryPage.module.css`:

```css
.status { margin: 0 0 var(--sp-3); min-height: 1lh; color: var(--text-2); font-size: var(--fs-14); }
.error {
  margin: 0 0 var(--sp-4); padding: var(--sp-3) var(--sp-4); border-radius: var(--r-md);
  background: var(--danger-soft); color: var(--danger);
}
```

Note: `userEvent.upload` respects `accept`; the test files have type `application/pdf`. If `hidden` inputs can't be targeted by `getByLabelText`, keep `hidden` (Testing Library finds hidden inputs by label) — if it fails, use a visually-hidden class instead of the `hidden` attribute.

- [ ] **Step 8: Run** — `cd web && npm test && npm run build` → PASS (fix the prettier-free TS errors the build reports). Render both themes and compare with the mockup: `make design-shots` isn't for the app; run `npm run dev` only if you need to eyeball it — otherwise rely on tests.

- [ ] **Step 9: Commit** — `git commit -m "Upload PDFs from the Library and show their processing state"`.

---

### Task 8: Compose wiring, docs, PRD, and the end-to-end check

**Files:**
- Modify: `compose.yaml`, `.env.example`, `backend/README.md`, `backend/src/smart_tutor/knowledge/README.md`, `sdd/prd.md`

- [ ] **Step 1: Compose** — `api` service: add `AWS_ENDPOINT_URL_S3: http://localhost:10402` (the browser POSTs to this URL; the API only signs) and `SMART_TUTOR_S3_PATH_STYLE: "true"`; `worker`: add `SMART_TUTOR_S3_PATH_STYLE: "true"` and `depends_on` `migrate: {condition: service_completed_successfully}` plus `localstack`. Both talk to LocalStack, which accepts any credentials: add `AWS_ACCESS_KEY_ID: test` and `AWS_SECRET_ACCESS_KEY: test` to `worker`; for `api` add the same only if the end-to-end check (Step 4) shows the container has no credentials (a `.env` `AWS_PROFILE` that doesn't exist in the container raises `ProfileNotFound`; then also set `AWS_PROFILE: ""` is NOT enough — instead override with `AWS_CONFIG_FILE`/credentials or drop `AWS_PROFILE` from that service's env). Record what was needed in the PR.
- [ ] **Step 2: `.env.example`** — add `SMART_TUTOR_S3_PATH_STYLE=true` under the local services block.
- [ ] **Step 3: Docs** — `backend/README.md`: a "Compose check: upload a PDF" section:

```markdown
## Compose check: upload a PDF (#60)

1. `docker compose --profile app up -d --build` and open http://localhost:10453; sign in as `learner@example.com` / `learner`.
2. Library → **Choose PDFs** → pick a PDF under 50 MB. A row with the file name shows **Processing** within a few seconds.
3. `docker compose logs worker` shows `upload <id>: stored`; the object is in `contents/`, not in `uploads/`:
   `aws --endpoint-url http://localhost:10402 s3 ls s3://smart-tutor-documents/ --recursive`
4. Upload the same file again (or as `learner2@example.com`): the new row shows **Failed — Duplicate uploads aren't supported yet**, and `select count(*) from contents` is unchanged.
```

`knowledge/README.md`: add a line under Rules: "Upload keys are `uploads/<user_id>/<upload_id>.pdf`; the worker hashes the bytes and stores new contents at `contents/<sha256>.pdf`. Until US-11, a known hash fails the document with "Duplicate uploads aren't supported yet"."

- [ ] **Step 4: PRD** — §9.4 Document row: add `file_name` (the picked file's name; the title until the first-pages step) and `failure_reason` to the column list. Status line → `Draft v2.9 …`; add a `Changes from v2.8` row: "Data model only: `documents` gains `file_name` (the display title's last fallback, §9.4) and `failure_reason` (why this learner's document failed, e.g. a duplicate before US-11 links it). No product behavior changes."
- [ ] **Step 5: End-to-end** — from the worktree root: `docker compose --profile app up -d --build`; follow the README check with a small PDF; also run `cd backend && uv run pytest -m integration -q`. If the Compose ports are taken by another checkout's stack, stop that stack first only if it's this repo's (`docker compose ls`), otherwise report.
- [ ] **Step 6: Full checks** — backend checks, `cd web && npm run build && npm test`.
- [ ] **Step 7: Commit** — `git commit -m "Wire uploads through Compose and document the check"`.

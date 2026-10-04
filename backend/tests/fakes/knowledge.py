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
            d.owner_id == document.owner_id
            and d.content_id == document.content_id
            and d.document_id != document.document_id
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

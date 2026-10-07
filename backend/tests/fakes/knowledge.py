"""In-memory library and object store. A unit of work edits a copy and publishes it on commit."""

import copy
import math
import uuid
from collections.abc import Collection
from types import TracebackType
from typing import Self

from smart_tutor.knowledge.domain.chunk import Chunk
from smart_tutor.knowledge.domain.content import Content
from smart_tutor.knowledge.domain.document import Document, DocumentState
from smart_tutor.knowledge.domain.search import ChunkHit
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.knowledge.ports.library import (
    ChunkRepository,
    ContentRepository,
    DocumentRepository,
    LibraryUnitOfWork,
    UploadRepository,
)
from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, ObjectStore, PresignedPost
from smart_tutor.shared.domain.ids import ContentId, DocumentId, SubjectId, UploadId, UserId


class _State:
    def __init__(self) -> None:
        self.contents: dict[str, Content] = {}
        self.documents: dict[str, Document] = {}
        self.uploads: dict[str, Upload] = {}
        self.chunks: dict[str, list[Chunk]] = {}


class InMemoryLibrary:
    def __init__(self) -> None:
        self.state = _State()
        self.commits = 0
        self.locked_contents: list[str] = []  # ids read with get_for_update, in order

    def unit_of_work(self) -> "FakeLibraryUnitOfWork":
        return FakeLibraryUnitOfWork(self)


class _Contents(ContentRepository):
    def __init__(self, state: _State, library: InMemoryLibrary) -> None:
        self._s, self._library = state, library

    def insert_or_get(self, content: Content) -> tuple[Content, bool]:
        for existing in self._s.contents.values():
            if existing.sha256 == content.sha256:
                return copy.deepcopy(existing), False
        self._s.contents[content.content_id] = copy.deepcopy(content)
        return content, True

    def get(self, content_id: ContentId) -> Content | None:
        found = self._s.contents.get(content_id)
        return copy.deepcopy(found) if found else None

    def get_for_update(self, content_id: ContentId) -> Content | None:
        self._library.locked_contents.append(content_id)
        return self.get(content_id)

    def save(self, content: Content) -> None:
        self._s.contents[content.content_id] = copy.deepcopy(content)


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

    def get(self, document_id: DocumentId) -> Document | None:
        found = self._s.documents.get(document_id)
        return copy.deepcopy(found) if found else None

    def list_failed_for_content_for_update(self, content_id: ContentId) -> list[Document]:
        return [
            copy.deepcopy(d)
            for d in self._s.documents.values()
            if d.content_id == content_id and d.state is DocumentState.FAILED
        ]

    def list_processing_for_content_for_update(self, content_id: ContentId) -> list[Document]:
        return [
            copy.deepcopy(d)
            for d in self._s.documents.values()
            if d.content_id == content_id and d.state is DocumentState.PROCESSING
        ]

    def list_readable_by(self, user_id: UserId) -> list[Document]:
        mine = [copy.deepcopy(d) for d in self._s.documents.values() if d.can_be_read_by(user_id) and not d.archived]
        for d in mine:
            content = self._s.contents.get(d.content_id) if d.content_id is not None else None
            d.content_title = content.title if content else None
            d.content_attempts = content.attempts if content else None
        return sorted(mine, key=lambda d: d.created_at, reverse=True)

    def find_readable_by_sha256(self, user_id: UserId, sha256: str) -> DocumentId | None:
        mine = sorted(
            (
                d
                for d in self._s.documents.values()
                if d.can_be_read_by(user_id)
                and d.content_id is not None
                and self._s.contents[d.content_id].sha256 == sha256
            ),
            key=lambda d: d.created_at,
        )
        return mine[0].document_id if mine else None

    def get_readable(self, user_id: UserId, document_id: DocumentId, *, for_update: bool = False) -> Document | None:
        found = self._s.documents.get(document_id)
        if found is None or not found.can_be_read_by(user_id):
            return None
        doc = copy.deepcopy(found)
        content = self._s.contents.get(doc.content_id) if doc.content_id is not None else None
        doc.content_title = content.title if content else None
        doc.content_attempts = content.attempts if content else None
        return doc

    def subject_ids_readable_by(self, user_id: UserId) -> set[SubjectId]:
        return {
            sid
            for d in self._s.documents.values()
            if d.can_be_read_by(user_id) and d.state is DocumentState.READY
            for sid in d.subject_ids
        }


class _Uploads(UploadRepository):
    def __init__(self, state: _State) -> None:
        self._s = state

    def add(self, upload: Upload) -> None:
        self._s.uploads[upload.upload_id] = copy.deepcopy(upload)

    def record_outcome(self, upload_id: UploadId, size: int, outcome: UploadOutcome) -> None:
        upload = self._s.uploads[upload_id]
        upload.size, upload.outcome = size, outcome


def _cosine(a: list[float], b: list[float]) -> float:
    norms = math.hypot(*a) * math.hypot(*b)
    return sum(x * y for x, y in zip(a, b, strict=True)) / norms if norms else 0.0


class _Chunks(ChunkRepository):
    def __init__(self, state: _State) -> None:
        self._s = state

    def replace(self, content_id: ContentId, chunks: list[Chunk]) -> None:
        self._s.chunks[content_id] = copy.deepcopy(chunks)

    def search(
        self, user_id: UserId, embedding: list[float], subject_ids: Collection[SubjectId], k: int
    ) -> list[ChunkHit]:
        def title(d: Document) -> str:
            content = self._s.contents.get(d.content_id) if d.content_id is not None else None
            return d.title_override or (content.title if content else None) or d.file_name

        hits = [
            ChunkHit(
                str(uuid.uuid5(uuid.NAMESPACE_URL, f"{c.content_id}:{c.seq}")),
                d.document_id,
                title(d),
                c.page,
                c.text,
                _cosine(embedding, c.embedding),
            )
            for d in self._s.documents.values()
            if d.content_id is not None and d.searchable_by(user_id, subject_ids)
            for c in self._s.chunks.get(d.content_id, [])
        ]
        return sorted(hits, key=lambda h: (-h.score, h.chunk_id))[:k]


class FakeLibraryUnitOfWork(LibraryUnitOfWork):
    def __init__(self, library: InMemoryLibrary) -> None:
        self._library = library
        self._staged = copy.deepcopy(library.state)
        self.contents = _Contents(self._staged, library)
        self.documents = _Documents(self._staged)
        self.uploads = _Uploads(self._staged)
        self.chunks = _Chunks(self._staged)

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
        self.content_types: dict[str, str] = {}  # of objects stored with `put`
        self.presigned: list[tuple[str, str, int, int]] = []  # key, content type, max bytes, expires in

    def presign_post(self, key: str, *, content_type: str, max_bytes: int, expires_in: int) -> PresignedPost:
        self.presigned.append((key, content_type, max_bytes, expires_in))
        return PresignedPost(url="http://s3.test/bucket", fields={"key": key, "Content-Type": content_type})

    def read(self, key: str) -> bytes:
        try:
            return self.objects[key]
        except KeyError:
            raise ObjectNotFoundError(key) from None

    def put(self, key: str, data: bytes, content_type: str) -> None:
        self.objects[key] = data
        self.content_types[key] = content_type

    def copy(self, source_key: str, dest_key: str) -> None:
        self.objects[dest_key] = self.read(source_key)

    def delete(self, key: str) -> None:
        self.objects.pop(key, None)

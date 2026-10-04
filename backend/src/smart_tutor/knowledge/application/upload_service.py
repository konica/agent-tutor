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

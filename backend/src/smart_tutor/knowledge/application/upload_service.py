"""Start an upload: record it, create the processing document, and presign the browser's POST (PRD §9.3, §9.5)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from smart_tutor.accounts.application import UploadBlock, UploadLimitReachedError, UploadLimits
from smart_tutor.knowledge.domain.document import Document
from smart_tutor.knowledge.domain.limits import FileLimits
from smart_tutor.knowledge.domain.upload import Upload, UploadOutcome
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectStore
from smart_tutor.shared.domain.ids import DocumentId, UploadId, UserId
from smart_tutor.shared.ports.clock import Clock

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


@dataclass(frozen=True)
class UploadStatus:
    """What became of an upload: `None` until the worker hashed it; the document it ended in (PRD US-11)."""

    outcome: UploadOutcome | None
    document_id: DocumentId | None
    archived: bool


class UploadService:
    def __init__(
        self,
        uow: Callable[[], LibraryUnitOfWork],
        objects: ObjectStore,
        clock: Clock,
        limits: FileLimits,
        *,
        rate: UploadLimits,
        time_zone: ZoneInfo,
        new_id: Callable[[], str] = new_uuid,
    ) -> None:
        self._uow, self._objects, self._clock, self._limits, self._new_id = uow, objects, clock, limits, new_id
        self._rate, self._tz = rate, time_zone

    @property
    def limits(self) -> FileLimits:
        return self._limits

    @property
    def rate_limits(self) -> UploadLimits:
        return self._rate

    def now(self) -> datetime:
        return self._clock.now()

    def start_upload(self, owner_id: UserId, file_name: str) -> StartedUpload:
        """Refuses with UploadLimitReachedError at the learner's hourly or daily limit; every started upload counts
        (duplicates and failed ones too, PRD §11)."""
        now = self._clock.now()
        upload = Upload(UploadId(self._new_id()), owner_id, now)
        document = Document.start_upload(DocumentId(self._new_id()), owner_id, upload.upload_id, file_name, now)
        with self._uow() as tx:
            tx.uploads.lock_learner(owner_id)
            block = self._rate.check(tx.uploads.created_since(owner_id, self._rate.since(now, self._tz)), now, self._tz)
            if block:
                raise UploadLimitReachedError(block, self._rate, self._tz)
            post = self._objects.presign_post(
                upload.key, content_type=PDF_CONTENT_TYPE, max_bytes=self._limits.max_bytes, expires_in=PRESIGN_SECONDS
            )
            tx.uploads.add(upload)
            tx.documents.add(document)
            tx.commit()
        return StartedUpload(document.document_id, upload.upload_id, post.url, post.fields)

    def upload_block(self, user_id: UserId) -> UploadBlock | None:
        """Whether the caller has reached an upload limit now, and until when (their own uploads only)."""
        now = self._clock.now()
        with self._uow() as tx:
            created = tx.uploads.created_since(user_id, self._rate.since(now, self._tz))
        return self._rate.check(created, now, self._tz)

    def upload_status(self, user_id: UserId, upload_id: UploadId) -> UploadStatus | None:
        """The caller's upload only; another learner's reads as unknown (None)."""
        with self._uow() as tx:
            upload = tx.uploads.get(upload_id)
            if upload is None or upload.user_id != user_id:
                return None
            document = tx.documents.get(upload.document_id) if upload.document_id else None
        if document is None or not document.can_be_read_by(user_id):
            return UploadStatus(upload.outcome, None, False)
        return UploadStatus(upload.outcome, document.document_id, document.archived)

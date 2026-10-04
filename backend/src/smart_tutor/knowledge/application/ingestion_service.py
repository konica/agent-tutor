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

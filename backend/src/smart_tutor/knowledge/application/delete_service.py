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
            # Runs on its own connection while this transaction holds the row locks (deletes are rare).
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

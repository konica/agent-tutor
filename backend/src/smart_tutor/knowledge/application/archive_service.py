"""Archive and restore a document (PRD §8 US-10, §9.5). Reads go through `can_read`."""

from collections.abc import Callable

from smart_tutor.knowledge.application.document_service import DocumentView, document_view
from smart_tutor.knowledge.domain.document import Document
from smart_tutor.knowledge.domain.errors import DocumentNotFoundError
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import DocumentId, UserId
from smart_tutor.shared.ports.clock import Clock


class ArchiveService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], clock: Clock, max_attempts: int) -> None:
        self._uow, self._clock, self._max_attempts = uow, clock, max_attempts

    def archive(self, user_id: UserId, document_id: DocumentId) -> DocumentView:
        return self._change(user_id, document_id, lambda d: d.archive(self._clock.now()))

    def restore(self, user_id: UserId, document_id: DocumentId) -> DocumentView:
        return self._change(user_id, document_id, Document.restore)

    def _change(self, user_id: UserId, document_id: DocumentId, change: Callable[[Document], None]) -> DocumentView:
        with self._uow() as tx:
            document = tx.documents.get_readable(user_id, document_id, for_update=True)
            if document is None:
                raise DocumentNotFoundError("This document isn't in your library")
            change(document)
            tx.documents.save(document)
            tx.commit()
        return document_view(document, self._max_attempts)

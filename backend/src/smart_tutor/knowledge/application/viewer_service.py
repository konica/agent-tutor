"""The document viewer's file link (PRD §8 US-4b, §9.3 step 5). Reads go through `can_read`, archived included."""

from collections.abc import Callable
from dataclasses import dataclass

from smart_tutor.knowledge.application.document_service import DocumentView, document_view
from smart_tutor.knowledge.domain.content import content_key
from smart_tutor.knowledge.domain.document import DocumentState
from smart_tutor.knowledge.domain.errors import DocumentNotFoundError, DocumentStateError
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectStore
from smart_tutor.shared.domain.ids import DocumentId, UserId

VIEWER_LINK_SECONDS = 300  # the viewer renews the link while it stays open
_OPENABLE = (DocumentState.READY, DocumentState.AWAITING_SUBJECTS)


@dataclass(frozen=True)
class DocumentFile:
    view: DocumentView
    url: str
    expires_in: int


class ViewerService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], objects: ObjectStore, max_attempts: int) -> None:
        self._uow, self._objects, self._max_attempts = uow, objects, max_attempts

    def file(self, user_id: UserId, document_id: DocumentId) -> DocumentFile:
        """A short-lived link to the PDF of a processed document the caller can read."""
        with self._uow() as tx:
            found = tx.documents.list_readable_by_ids(user_id, [document_id])
        if not found:
            raise DocumentNotFoundError("This document isn't in your library")
        document = found[0]
        if document.state not in _OPENABLE or document.content_id is None:
            raise DocumentStateError("This document can't be opened until it has been processed")
        url = self._objects.presign_get(
            content_key(document.owner_id, document.content_id), expires_in=VIEWER_LINK_SECONDS
        )
        return DocumentFile(document_view(document, self._max_attempts), url, VIEWER_LINK_SECONDS)

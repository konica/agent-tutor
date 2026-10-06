"""The learner's library as they see it. Reads go through `can_read` (PRD §9.3)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from smart_tutor.knowledge.domain.content import RETRIES_USED_UP
from smart_tutor.knowledge.domain.document import Document, DocumentState
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, UserId

DocumentStateName = Literal["processing", "awaiting_subjects", "ready", "failed"]


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
        attempts = d.content_attempts
        failed = d.state is DocumentState.FAILED and attempts is not None
        used_up = failed and attempts is not None and attempts >= self._max_attempts
        return DocumentView(
            d.document_id,
            d.title,
            d.state.value,
            RETRIES_USED_UP if used_up else d.failure_reason,
            d.created_at,
            tuple(d.subject_ids),
            attempts,
            self._max_attempts,
            failed and not used_up,
        )

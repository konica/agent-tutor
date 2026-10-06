"""The learner's library as they see it. Reads go through `can_read` (PRD §9.3)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from smart_tutor.knowledge.domain.document import DocumentState
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


class DocumentService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork]) -> None:
        self._uow = uow

    def list_documents(self, user_id: UserId) -> list[DocumentView]:
        with self._uow() as tx:
            documents = tx.documents.list_readable_by(user_id)
        return [
            DocumentView(d.document_id, d.title, d.state.value, d.failure_reason, d.created_at, tuple(d.subject_ids))
            for d in documents
        ]

    def learner_subjects(self, user_id: UserId) -> frozenset[SubjectId]:
        """My subjects: those of the learner's ready, non-archived documents (PRD §9.4)."""
        with self._uow() as tx:
            documents = tx.documents.list_readable_by(user_id)
        return frozenset(s for d in documents if d.state is DocumentState.READY for s in d.subject_ids)

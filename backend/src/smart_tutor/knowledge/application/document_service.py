"""The learner's library as they see it. Reads go through `can_read` (PRD §9.3)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import DocumentId, UserId

DocumentStateName = Literal["processing", "awaiting_subjects", "ready", "failed"]


@dataclass(frozen=True)
class DocumentView:
    document_id: DocumentId
    title: str
    state: DocumentStateName
    failure_reason: str | None
    created_at: datetime


class DocumentService:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork]) -> None:
        self._uow = uow

    def list_documents(self, user_id: UserId) -> list[DocumentView]:
        with self._uow() as tx:
            documents = tx.documents.list_readable_by(user_id)
        return [DocumentView(d.document_id, d.title, d.state.value, d.failure_reason, d.created_at) for d in documents]

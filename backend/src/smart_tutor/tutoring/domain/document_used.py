"""A document the conversation drew on, as the learner sees it now (PRD §8 US-4b, US-4c)."""

from dataclasses import dataclass

from smart_tutor.shared.domain.ids import DocumentId
from smart_tutor.tutoring.domain.thread_document import AddedBy

DELETED_DOCUMENT = "Deleted document"


@dataclass(frozen=True)
class DocumentUsed:
    """A document in the conversation's list, as the learner sees it now (US-4b, US-4c)."""

    document_id: DocumentId
    title: str
    authors: tuple[str, ...]
    year: int | None
    archived: bool
    deleted: bool
    added_by: AddedBy
    used: bool  # an answer has used it; false for a document the learner added and no answer has drawn on yet

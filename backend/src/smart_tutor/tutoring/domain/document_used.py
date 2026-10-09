"""A document the conversation drew on, as the learner sees it now (PRD §8 US-4b)."""

from dataclasses import dataclass

from smart_tutor.shared.domain.ids import DocumentId

DELETED_DOCUMENT = "Deleted document"


@dataclass(frozen=True)
class DocumentUsed:
    """A document the conversation drew on, as the learner sees it now (US-4b)."""

    document_id: DocumentId
    title: str
    authors: tuple[str, ...]
    year: int | None
    archived: bool
    deleted: bool

"""A document the thread drew on (PRD §9.4 Thread document); the row outlives the document."""

from dataclasses import dataclass
from datetime import datetime

from smart_tutor.shared.domain.ids import DocumentId, ThreadId


@dataclass(frozen=True)
class ThreadDocument:
    thread_id: ThreadId
    document_id: DocumentId
    first_used_at: datetime
    deleted_title: str | None = None  # the display title, copied when the document is deleted (US-10c)

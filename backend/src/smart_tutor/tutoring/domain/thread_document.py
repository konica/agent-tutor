"""A document in the thread's document list (PRD §9.4 Thread document); the row outlives the document."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from smart_tutor.shared.domain.ids import DocumentId, ThreadId

AddedBy = Literal["answer", "learner"]


@dataclass(frozen=True)
class ThreadDocument:
    thread_id: ThreadId
    document_id: DocumentId
    added_by: AddedBy  # an answer drew on it, or the learner added it (US-4c)
    added_at: datetime
    first_used_at: datetime | None = None  # null until an answer uses it
    deleted_title: str | None = None  # the display title, copied when the document is deleted (US-10c)

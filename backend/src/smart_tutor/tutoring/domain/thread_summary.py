"""One row of the learner's conversations list (PRD §8 US-13)."""

from dataclasses import dataclass
from datetime import datetime

from smart_tutor.shared.domain.ids import SubjectId, ThreadId


@dataclass(frozen=True)
class ThreadSummary:
    thread_id: ThreadId
    title: str | None  # the first question until renamed
    subject_ids: tuple[SubjectId, ...]  # of its listed documents that still exist, archived included (D11)
    documents: int  # rows in its document list, deleted ones included
    last_activity: datetime

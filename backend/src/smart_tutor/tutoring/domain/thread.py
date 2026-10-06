"""One conversation (PRD §9.4 Thread). Subjects: 1 to 3, only ever added (US-3, US-3b)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.tutoring.domain.errors import ThreadSubjectsError

MAX_SUBJECTS = 3


class ThreadStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass
class Thread:
    thread_id: ThreadId
    user_id: UserId
    subject_ids: tuple[SubjectId, ...]
    created_at: datetime
    status: ThreadStatus = ThreadStatus.ACTIVE
    title: str | None = None
    last_learner_message_at: datetime | None = None

    @classmethod
    def start(cls, thread_id: ThreadId, user_id: UserId, subject_ids: Sequence[SubjectId], now: datetime) -> "Thread":
        """A new thread with its first question asked now."""
        if not 1 <= len(subject_ids) <= MAX_SUBJECTS or len(set(subject_ids)) != len(subject_ids):
            raise ThreadSubjectsError("A thread starts with 1 to 3 distinct subjects")
        return cls(thread_id, user_id, tuple(subject_ids), now, last_learner_message_at=now)

    def add_subject(self, subject_id: SubjectId) -> bool:
        """Add a subject; False when the thread already has it. Never more than 3, never removed."""
        if subject_id in self.subject_ids:
            return False
        if len(self.subject_ids) >= MAX_SUBJECTS:
            raise ThreadSubjectsError("A thread has at most 3 subjects")
        self.subject_ids = (*self.subject_ids, subject_id)
        return True

    def is_owned_by(self, user_id: UserId) -> bool:
        return self.user_id == user_id

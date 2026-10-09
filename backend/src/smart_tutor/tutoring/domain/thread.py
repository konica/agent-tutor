"""One conversation (PRD §9.4 Thread). It has no subjects; its documents used (US-4b) are still to come."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from smart_tutor.shared.domain.ids import ThreadId, UserId


class ThreadStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass
class Thread:
    thread_id: ThreadId
    user_id: UserId
    created_at: datetime
    status: ThreadStatus = ThreadStatus.ACTIVE
    title: str | None = None
    last_learner_message_at: datetime | None = None

    @classmethod
    def start(cls, thread_id: ThreadId, user_id: UserId, now: datetime) -> "Thread":
        """A new thread with its first question asked now."""
        return cls(thread_id, user_id, now, last_learner_message_at=now)

    def is_owned_by(self, user_id: UserId) -> bool:
        return self.user_id == user_id

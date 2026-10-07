"""Persistence of threads. Reads are always scoped to the owner."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.tutoring.domain.thread import Thread


class ThreadRepository(ABC):
    @abstractmethod
    def add(self, thread: Thread) -> None:
        """Store a new thread (committed when this returns)."""

    @abstractmethod
    def get_owned(self, thread_id: ThreadId, user_id: UserId) -> Thread | None:
        """The thread if it exists and belongs to this learner; None otherwise."""

    @abstractmethod
    def bind_subjects(self, thread_id: ThreadId, user_id: UserId, subject_ids: Sequence[SubjectId]) -> bool:
        """Give a pending thread of this learner its subjects; False when it isn't theirs or already has subjects."""

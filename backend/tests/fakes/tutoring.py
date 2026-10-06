"""In-memory threads."""

import copy

from smart_tutor.shared.domain.ids import ThreadId, UserId
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository


class InMemoryThreads(ThreadRepository):
    def __init__(self) -> None:
        self.threads: dict[str, Thread] = {}

    def add(self, thread: Thread) -> None:
        self.threads[thread.thread_id] = copy.deepcopy(thread)

    def get_owned(self, thread_id: ThreadId, user_id: UserId) -> Thread | None:
        found = self.threads.get(thread_id)
        return copy.deepcopy(found) if found and found.is_owned_by(user_id) else None

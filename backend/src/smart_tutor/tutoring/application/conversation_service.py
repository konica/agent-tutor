"""Start a thread (PRD §8 US-3): it answers from all of the learner's ready documents."""

import uuid

from smart_tutor.knowledge.application import DocumentService
from smart_tutor.shared.domain.ids import ThreadId, UserId
from smart_tutor.shared.ports.clock import Clock
from smart_tutor.tutoring.domain.errors import NoDocumentsError
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository


class ConversationService:
    def __init__(self, threads: ThreadRepository, documents: DocumentService, clock: Clock) -> None:
        self._threads = threads
        self._documents = documents
        self._clock = clock

    def require_documents(self, user_id: UserId) -> None:
        """No ready, non-archived document → "Upload a document first"."""
        if not self._documents.has_ready_documents(user_id):
            raise NoDocumentsError("Upload a document first")

    def start_thread(self, user_id: UserId) -> Thread:
        """A new thread owned by the learner, persisted."""
        self.require_documents(user_id)
        thread = Thread.start(ThreadId(str(uuid.uuid4())), user_id, self._clock.now())
        self._threads.add(thread)
        return thread

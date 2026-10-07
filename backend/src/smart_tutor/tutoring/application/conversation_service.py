"""Start a thread (PRD §8 US-3): a learner with exactly one subject starts with it; detection comes with US-2b."""

import uuid

from smart_tutor.knowledge.application import DocumentService
from smart_tutor.shared.domain.ids import ThreadId, UserId
from smart_tutor.shared.ports.clock import Clock
from smart_tutor.tutoring.domain.errors import DetectionUnavailableError, NoDocumentsError
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository


class ConversationService:
    def __init__(self, threads: ThreadRepository, documents: DocumentService, clock: Clock) -> None:
        self._threads = threads
        self._documents = documents
        self._clock = clock

    def start_thread(self, user_id: UserId) -> Thread:
        subjects = self._documents.learner_subjects(user_id)
        if not subjects:
            raise NoDocumentsError("Upload a document first")
        if len(subjects) > 1:
            raise DetectionUnavailableError("Subject detection isn't available yet")
        thread = Thread.start(ThreadId(str(uuid.uuid4())), user_id, sorted(subjects), self._clock.now())
        self._threads.add(thread)
        return thread

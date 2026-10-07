"""Start a thread (PRD §8 US-3) with the subjects detected from its first question, all the learner's own."""

import uuid
from collections.abc import Sequence

from smart_tutor.knowledge.application import DocumentService
from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.shared.ports.clock import Clock
from smart_tutor.tutoring.domain.errors import NoDocumentsError, ThreadSubjectsError
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository


class ConversationService:
    def __init__(self, threads: ThreadRepository, documents: DocumentService, clock: Clock) -> None:
        self._threads = threads
        self._documents = documents
        self._clock = clock

    def subjects_for_new_thread(self, user_id: UserId) -> list[SubjectId]:
        """The learner's subjects, sorted: detection chooses among them. None → "Upload a document first"."""
        subjects = self._documents.learner_subjects(user_id)
        if not subjects:
            raise NoDocumentsError("Upload a document first")
        return sorted(subjects)

    def start_thread(self, user_id: UserId, subject_ids: Sequence[SubjectId]) -> Thread:
        """A new thread with 1 to 3 of the learner's own subjects, persisted."""
        if not set(subject_ids) <= set(self.subjects_for_new_thread(user_id)):
            raise ThreadSubjectsError("A thread's subjects are the learner's own")
        thread = Thread.start(ThreadId(str(uuid.uuid4())), user_id, subject_ids, self._clock.now())
        self._threads.add(thread)
        return thread

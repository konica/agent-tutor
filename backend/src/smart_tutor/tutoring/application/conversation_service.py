"""Start a thread (PRD §8 US-3) with the subjects detected from its first question, all the learner's own."""

from collections.abc import Sequence

from smart_tutor.knowledge.application import DocumentService
from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.shared.ports.clock import Clock
from smart_tutor.tutoring.domain.errors import (
    NoDocumentsError,
    ThreadNotFoundError,
    ThreadNotPendingError,
    ThreadSubjectsError,
)
from smart_tutor.tutoring.domain.thread import MAX_SUBJECTS, Thread
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

    def start_thread(
        self, user_id: UserId, subject_ids: Sequence[SubjectId], thread_id: ThreadId, title: str
    ) -> Thread:
        """A new thread with 1 to 3 of the learner's own subjects, persisted."""
        self.check_choice(user_id, subject_ids)
        thread = Thread.start(thread_id, user_id, subject_ids, self._clock.now(), title=title)
        self._threads.add(thread)
        return thread

    def start_pending_thread(self, user_id: UserId, thread_id: ThreadId, title: str) -> Thread:
        """A thread whose first question waits for the learner's pick (detection unsure)."""
        self.subjects_for_new_thread(user_id)  # NoDocumentsError like start_thread
        thread = Thread.pending(thread_id, user_id, title, self._clock.now())
        self._threads.add(thread)
        return thread

    def get_thread(self, user_id: UserId, thread_id: ThreadId) -> Thread:
        thread = self._threads.get_owned(thread_id, user_id)
        if thread is None:
            raise ThreadNotFoundError("No such conversation")
        return thread

    def pending_thread(self, user_id: UserId, thread_id: ThreadId) -> Thread:
        thread = self.get_thread(user_id, thread_id)
        if not thread.awaiting_subjects:
            raise ThreadNotPendingError("This conversation already has its subjects")
        return thread

    def check_choice(self, user_id: UserId, subject_ids: Sequence[SubjectId]) -> None:
        """1 to 3 distinct subjects, all the learner's own; ThreadSubjectsError otherwise."""
        if not 1 <= len(subject_ids) <= MAX_SUBJECTS or len(set(subject_ids)) != len(subject_ids):
            raise ThreadSubjectsError("Pick 1 to 3 subjects")
        if not set(subject_ids) <= set(self.subjects_for_new_thread(user_id)):
            raise ThreadSubjectsError("A thread's subjects are the learner's own")

    def bind_subjects(self, user_id: UserId, thread_id: ThreadId, subject_ids: Sequence[SubjectId]) -> bool:
        """Give a pending thread its subjects; False when it isn't the learner's or already has them."""
        self.check_choice(user_id, subject_ids)
        return self._threads.bind_subjects(thread_id, user_id, subject_ids)

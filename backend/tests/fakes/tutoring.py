"""In-memory threads and a fake retriever."""

import copy
import dataclasses
from collections.abc import Sequence
from dataclasses import replace
from datetime import datetime

from smart_tutor.shared.domain.ids import DocumentId, RunId, ThreadId, UserId
from smart_tutor.tutoring.domain.guard import GUARD_DECLINE, GuardTrip
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk
from smart_tutor.tutoring.domain.thread import NO_THREAD_FILTER, SearchScope, Thread, ThreadFilter, ThreadStatus
from smart_tutor.tutoring.domain.thread_document import ThreadDocument
from smart_tutor.tutoring.domain.turn import Rating, Turn
from smart_tutor.tutoring.ports.answer_feedback import AnswerFeedback
from smart_tutor.tutoring.ports.guard import Guard
from smart_tutor.tutoring.ports.retriever import Retriever
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository


class InMemoryThreads(ThreadRepository):
    def __init__(self) -> None:
        self.threads: dict[str, Thread] = {}
        self.documents_used_rows: dict[str, list[ThreadDocument]] = {}
        self.turn_rows: list[Turn] = []

    def add(self, thread: Thread) -> None:
        self.threads[thread.thread_id] = copy.deepcopy(thread)

    def get_owned(self, thread_id: ThreadId, user_id: UserId) -> Thread | None:
        found = self.threads.get(thread_id)
        return copy.deepcopy(found) if found and found.is_owned_by(user_id) else None

    def list_owned(
        self, user_id: UserId, status: ThreadStatus, thread_filter: ThreadFilter = NO_THREAD_FILTER
    ) -> list[Thread]:
        mine = [
            copy.deepcopy(t)
            for t in self.threads.values()
            if t.user_id == user_id
            and t.status is status
            and t.matches(thread_filter, [r.document_id for r in self.documents_used_rows.get(t.thread_id, [])])
        ]
        mine.sort(key=lambda t: t.thread_id)
        mine.sort(key=lambda t: (t.last_activity, t.created_at), reverse=True)
        return mine

    def documents_used_by_thread(self, thread_ids: Sequence[ThreadId]) -> dict[ThreadId, list[ThreadDocument]]:
        return {tid: list(self.documents_used_rows[tid]) for tid in thread_ids if self.documents_used_rows.get(tid)}

    def set_last_learner_message_at(self, thread_id: ThreadId, at: datetime) -> None:
        self.threads[thread_id].last_learner_message_at = at

    def set_title(self, thread_id: ThreadId, title: str) -> None:
        self.threads[thread_id].title = title

    def set_status(self, thread_id: ThreadId, status: ThreadStatus) -> None:
        self.threads[thread_id].status = status

    def set_search_scope(self, thread_id: ThreadId, scope: SearchScope) -> None:
        self.threads[thread_id].search_scope = scope

    def add_documents_used(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        rows = self.documents_used_rows.setdefault(thread_id, [])
        for document_id in document_ids:
            i = next((i for i, row in enumerate(rows) if row.document_id == document_id), None)
            if i is None:
                rows.append(ThreadDocument(thread_id, document_id, "answer", at, first_used_at=at))
            elif rows[i].first_used_at is None:
                rows[i] = dataclasses.replace(rows[i], first_used_at=at)

    def add_documents(self, thread_id: ThreadId, document_ids: Sequence[DocumentId], at: datetime) -> None:
        rows = self.documents_used_rows.setdefault(thread_id, [])
        for document_id in document_ids:
            if all(row.document_id != document_id for row in rows):
                rows.append(ThreadDocument(thread_id, document_id, "learner", at))

    def remove_document(self, thread_id: ThreadId, document_id: DocumentId) -> None:
        rows = self.documents_used_rows.get(thread_id, [])
        self.documents_used_rows[thread_id] = [row for row in rows if row.document_id != document_id]

    def keep_deleted_title(self, user_id: UserId, document_id: DocumentId, title: str) -> None:
        for thread in self.threads.values():
            if thread.user_id != user_id:
                continue
            rows = self.documents_used_rows.get(thread.thread_id, [])
            rows[:] = [replace(r, deleted_title=title) if r.document_id == document_id else r for r in rows]

    def documents_used(self, thread_id: ThreadId) -> list[ThreadDocument]:
        return list(self.documents_used_rows.get(thread_id, []))

    def add_turn(self, turn: Turn, document_ids: Sequence[DocumentId]) -> None:
        self.turn_rows.append(turn)
        if document_ids:
            self.add_documents_used(turn.thread_id, document_ids, turn.created_at)

    def turns(self, thread_id: ThreadId, user_id: UserId) -> list[Turn]:
        return [t for t in self.turn_rows if t.thread_id == thread_id and t.user_id == user_id]

    def last_turns(self, thread_id: ThreadId, user_id: UserId, limit: int) -> list[Turn]:
        kept = [t for t in self.turns(thread_id, user_id) if not (t.decline and t.decline.code == GUARD_DECLINE)]
        return kept[-limit:] if limit > 0 else []

    def set_rating(self, thread_id: ThreadId, user_id: UserId, run_id: RunId, rating: Rating) -> bool:
        for i, t in enumerate(self.turn_rows):
            if t.thread_id == thread_id and t.user_id == user_id and t.run_id == run_id:
                self.turn_rows[i] = dataclasses.replace(t, rating=rating)
                return True
        return False


class FakeAnswerFeedback(AnswerFeedback):
    """Records each rating sent and whether it was closed; raises `error` from send when given one."""

    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[RunId, Rating]] = []
        self.cleared: list[RunId] = []
        self.closed = False
        self._error = error

    def send(self, run_id: RunId, rating: Rating) -> None:
        if self._error is not None:
            raise self._error
        self.sent.append((run_id, rating))

    def clear(self, run_id: RunId) -> None:
        if self._error is not None:
            raise self._error
        self.cleared.append(run_id)

    def close(self) -> None:
        self.closed = True


class FakeRetriever(Retriever):
    def __init__(self, chunks: list[RetrievedChunk] | None = None, error: Exception | None = None) -> None:
        self._chunks = chunks or []
        self._error = error
        self.calls: list[tuple[str, int, list[str] | None]] = []

    async def search(self, query: str, k: int = 5, document_ids: Sequence[str] | None = None) -> list[RetrievedChunk]:
        self.calls.append((query, k, None if document_ids is None else list(document_ids)))
        if self._error is not None:
            raise self._error
        return list(self._chunks)


class PassingGuard(Guard):
    """Never trips; keeps each question and each answer-so-far it checked."""

    def __init__(self) -> None:
        self.questions: list[str] = []
        self.answers: list[str] = []

    async def check_question(self, question: str) -> GuardTrip | None:
        self.questions.append(question)
        return None

    async def check_answer(self, text: str) -> GuardTrip | None:
        self.answers.append(text)
        return None


class TrippingGuard(PassingGuard):
    """Trips the answer check once the answer so far holds `on`."""

    def __init__(self, on: str) -> None:
        super().__init__()
        self._on = on

    async def check_answer(self, text: str) -> GuardTrip | None:
        await super().check_answer(text)
        return GuardTrip("guard_answer", "system_prompt_leak") if self._on in text else None


class QuestionTrippingGuard(PassingGuard):
    """Trips the question check when the question holds `on`."""

    def __init__(self, on: str) -> None:
        super().__init__()
        self._on = on

    async def check_question(self, question: str) -> GuardTrip | None:
        await super().check_question(question)
        return GuardTrip("guard_question", "prompt_attack") if self._on in question else None

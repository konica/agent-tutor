"""A kept turn of a thread (PRD §9.4 Thread turn, US-13): the question, then the answer and its citations, or the
decline. Only a turn whose answer ended with `done` is kept (US-4b). Citations are ids and a page; titles resolve at
read time, so a deleted document's citation reads "Deleted document"."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from smart_tutor.shared.domain.ids import DocumentId, RunId, ThreadId, UserId


class Rating(StrEnum):
    """The learner's rating of a kept turn (PRD §10.2): helpful or not. One per turn; a new one replaces it."""

    UP = "up"
    DOWN = "down"


@dataclass(frozen=True)
class TurnCitation:
    """What an answer's [n] marker points at."""

    n: int
    document_id: DocumentId
    chunk_id: str
    page: int | None


@dataclass(frozen=True)
class Decline:
    code: str
    message: str


@dataclass(frozen=True)
class HistoryTurn:
    """An earlier turn as the answer model reads it (PRD §9.2 step 3, ADR 0015): the learner's question and the
    tutor's answer text, or the decline message. No citations, chunk text, or ids."""

    question: str
    answer: str


def history_turn(question: str, answer: str, max_answer_chars: int) -> HistoryTurn:
    """An earlier turn as history; an answer longer than `max_answer_chars` is cut and ends with "…"."""
    if len(answer) > max_answer_chars:
        answer = answer[: max_answer_chars - 1].rstrip() + "…"
    return HistoryTurn(question, answer)


@dataclass(frozen=True)
class Turn:
    thread_id: ThreadId
    user_id: UserId  # the thread's owner; reads are scoped by it
    question: str
    answer: str  # empty for a decline
    citations: tuple[TurnCitation, ...]
    decline: Decline | None
    created_at: datetime
    run_id: RunId | None = None  # the ask's trace id in Phoenix (PRD §10.4); None for turns kept before it was recorded
    rating: Rating | None = None  # the learner's 👍/👎 (PRD §10.2); None until rated

    def as_history(self, max_answer_chars: int) -> HistoryTurn:
        """The turn as history; an answer longer than `max_answer_chars` is cut and ends with "…"."""
        answer = self.decline.message if self.decline is not None else self.answer
        return history_turn(self.question, answer, max_answer_chars)


@dataclass(frozen=True)
class AnsweredTurn:
    """What the learner saw of one answer that ended with `done`, and the documents it drew on."""

    question: str
    answer: str = ""
    citations: tuple[TurnCitation, ...] = ()
    decline: Decline | None = None
    document_ids: tuple[DocumentId, ...] = ()
    run_id: RunId | None = None  # the ask's trace id in Phoenix (PRD §10.4); None for turns kept before it was recorded


@dataclass(frozen=True)
class CitationView:
    """A kept citation as the learner sees it now: display title, or "Deleted document"."""

    n: int
    document_id: DocumentId
    chunk_id: str
    page: int | None
    title: str
    archived: bool
    deleted: bool


@dataclass(frozen=True)
class TurnView:
    question: str
    answer: str
    citations: tuple[CitationView, ...]
    decline: Decline | None
    created_at: datetime
    run_id: RunId | None = None  # the ask's trace id in Phoenix (PRD §10.4); None for turns kept before it was recorded
    rating: Rating | None = None  # the learner's 👍/👎 (PRD §10.2); None until rated

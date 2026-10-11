"""A kept turn of a thread (PRD §9.4 Thread turn, US-13): the question, then the answer and its citations, or the
decline. Only a turn whose answer ended with `done` is kept (US-4b). Citations are ids and a page; titles resolve at
read time, so a deleted document's citation reads "Deleted document"."""

from dataclasses import dataclass
from datetime import datetime

from smart_tutor.shared.domain.ids import DocumentId, RunId, ThreadId, UserId


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
class Turn:
    thread_id: ThreadId
    user_id: UserId  # the thread's owner; reads are scoped by it
    question: str
    answer: str  # empty for a decline
    citations: tuple[TurnCitation, ...]
    decline: Decline | None
    created_at: datetime
    run_id: RunId | None = None  # the ask's LangSmith root run (PRD §10.4); None for turns kept before it was recorded


@dataclass(frozen=True)
class AnsweredTurn:
    """What the learner saw of one answer that ended with `done`, and the documents it drew on."""

    question: str
    answer: str = ""
    citations: tuple[TurnCitation, ...] = ()
    decline: Decline | None = None
    document_ids: tuple[DocumentId, ...] = ()
    run_id: RunId | None = None  # the ask's LangSmith root run (PRD §10.4); None for turns kept before it was recorded


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
    run_id: RunId | None = None  # the ask's LangSmith root run (PRD §10.4); None for turns kept before it was recorded

"""tutoring.application: Use-case services. This package is the module's public API for other modules."""

from smart_tutor.tutoring.application.answer import (
    LIMITED_DECLINE,
    NO_DOCUMENTS_DECLINE,
    SYSTEM_PROMPT,
    answer_messages,
    cited_chunks,
    covers,
)
from smart_tutor.tutoring.application.conversation_service import ConversationService
from smart_tutor.tutoring.application.follow_up import search_query
from smart_tutor.tutoring.domain.document_used import DELETED_DOCUMENT, DocumentUsed
from smart_tutor.tutoring.domain.errors import (
    DocumentNotAvailableError,
    InvalidTitleError,
    NoListedDocumentsError,
    RetrievalError,
    ThreadArchivedError,
    ThreadNotFoundError,
    TurnNotFoundError,
)
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk
from smart_tutor.tutoring.domain.thread import SearchScope, Thread
from smart_tutor.tutoring.domain.thread_summary import ThreadSummary
from smart_tutor.tutoring.domain.turn import (
    AnsweredTurn,
    CitationView,
    Decline,
    HistoryTurn,
    Rating,
    Turn,
    TurnCitation,
    TurnView,
    history_turn,
)
from smart_tutor.tutoring.ports.answer_feedback import AnswerFeedback, NoAnswerFeedback
from smart_tutor.tutoring.ports.retriever import Retriever
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository

__all__ = [
    "DELETED_DOCUMENT",
    "LIMITED_DECLINE",
    "NO_DOCUMENTS_DECLINE",
    "SYSTEM_PROMPT",
    "AnswerFeedback",
    "AnsweredTurn",
    "CitationView",
    "ConversationService",
    "Decline",
    "DocumentNotAvailableError",
    "DocumentUsed",
    "HistoryTurn",
    "InvalidTitleError",
    "NoAnswerFeedback",
    "NoListedDocumentsError",
    "Rating",
    "RetrievalError",
    "RetrievedChunk",
    "Retriever",
    "SearchScope",
    "Thread",
    "ThreadArchivedError",
    "ThreadNotFoundError",
    "ThreadRepository",
    "ThreadSummary",
    "Turn",
    "TurnCitation",
    "TurnNotFoundError",
    "TurnView",
    "answer_messages",
    "cited_chunks",
    "covers",
    "history_turn",
    "search_query",
]

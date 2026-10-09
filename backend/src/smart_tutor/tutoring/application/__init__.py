"""tutoring.application: Use-case services. This package is the module's public API for other modules."""

from smart_tutor.tutoring.application.answer import (
    LIMITED_DECLINE,
    NO_CHUNKS_ANSWER,
    answer_messages,
    cited_chunks,
    covers,
)
from smart_tutor.tutoring.application.conversation_service import ConversationService
from smart_tutor.tutoring.domain.document_used import DELETED_DOCUMENT, DocumentUsed
from smart_tutor.tutoring.domain.errors import (
    DocumentNotAvailableError,
    InvalidTitleError,
    NoDocumentsError,
    NoListedDocumentsError,
    RetrievalError,
    ThreadArchivedError,
    ThreadNotFoundError,
)
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk
from smart_tutor.tutoring.domain.thread import SearchScope, Thread
from smart_tutor.tutoring.ports.retriever import Retriever
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository

__all__ = [
    "DELETED_DOCUMENT",
    "LIMITED_DECLINE",
    "NO_CHUNKS_ANSWER",
    "ConversationService",
    "DocumentNotAvailableError",
    "DocumentUsed",
    "InvalidTitleError",
    "NoDocumentsError",
    "NoListedDocumentsError",
    "RetrievalError",
    "RetrievedChunk",
    "Retriever",
    "SearchScope",
    "Thread",
    "ThreadArchivedError",
    "ThreadNotFoundError",
    "ThreadRepository",
    "answer_messages",
    "cited_chunks",
    "covers",
]

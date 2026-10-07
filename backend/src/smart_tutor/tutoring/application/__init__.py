"""tutoring.application: Use-case services. This package is the module's public API for other modules."""

from smart_tutor.tutoring.application.answer import NO_CHUNKS_ANSWER, answer_messages, cited_chunks
from smart_tutor.tutoring.application.conversation_service import ConversationService
from smart_tutor.tutoring.application.detection_settings import load_detection_policy
from smart_tutor.tutoring.application.subject_detector import DETECTION_K, SubjectDetector
from smart_tutor.tutoring.domain.detection import Detection, DetectionPolicy
from smart_tutor.tutoring.domain.errors import (
    NoDocumentsError,
    RetrievalError,
    ThreadNotFoundError,
    ThreadNotPendingError,
    ThreadSubjectsError,
)
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.ports.retriever import Retriever
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository

__all__ = [
    "DETECTION_K",
    "NO_CHUNKS_ANSWER",
    "ConversationService",
    "Detection",
    "DetectionPolicy",
    "NoDocumentsError",
    "RetrievalError",
    "RetrievedChunk",
    "Retriever",
    "SubjectDetector",
    "Thread",
    "ThreadNotFoundError",
    "ThreadNotPendingError",
    "ThreadRepository",
    "ThreadSubjectsError",
    "answer_messages",
    "cited_chunks",
    "load_detection_policy",
]

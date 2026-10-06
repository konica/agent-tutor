"""knowledge.application: Use-case services. This package is the module's public API for other modules."""

from smart_tutor.knowledge.application.describer import FIRST_PAGES, Described, DocumentDescriber
from smart_tutor.knowledge.application.document_service import DocumentService, DocumentView
from smart_tutor.knowledge.application.ingestion_service import IngestionService, ProcessingTools
from smart_tutor.knowledge.application.limits import load_file_limits, load_max_attempts
from smart_tutor.knowledge.application.retry_service import RetryService, retried_content, retry_message
from smart_tutor.knowledge.application.upload_service import (
    PDF_CONTENT_TYPE,
    StartedUpload,
    UploadService,
)
from smart_tutor.knowledge.domain.content import ContentState
from smart_tutor.knowledge.domain.errors import DocumentNotFoundError, InvalidFileNameError, RetryLimitError
from smart_tutor.knowledge.domain.limits import FileLimits
from smart_tutor.knowledge.domain.upload import UploadOutcome
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectStore
from smart_tutor.knowledge.ports.pdf_extractor import PdfExtractor, TooManyPagesError, UnreadablePdfError

__all__ = [
    "FIRST_PAGES",
    "PDF_CONTENT_TYPE",
    "ContentState",
    "Described",
    "DocumentDescriber",
    "DocumentNotFoundError",
    "DocumentService",
    "DocumentView",
    "FileLimits",
    "IngestionService",
    "InvalidFileNameError",
    "LibraryUnitOfWork",
    "ObjectStore",
    "PdfExtractor",
    "ProcessingTools",
    "RetryLimitError",
    "RetryService",
    "StartedUpload",
    "TooManyPagesError",
    "UnreadablePdfError",
    "UploadOutcome",
    "UploadService",
    "load_file_limits",
    "load_max_attempts",
    "retried_content",
    "retry_message",
]

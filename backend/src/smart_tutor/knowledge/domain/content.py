"""A learner's file, keyed by `(owner_id, SHA-256)` the server computed from its bytes (PRD §9.4, §9.5; ADR 0011)."""

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING

from smart_tutor.knowledge.domain.errors import ContentStateError, RetryLimitError
from smart_tutor.shared.domain.ids import ContentId, UserId

if TYPE_CHECKING:
    from smart_tutor.knowledge.domain.description import DocumentDescription

UNREADABLE_PDF = "This file isn't a readable PDF"
NO_TEXT_LAYER = "No text layer (scanned PDFs are not supported yet)"
RETRIES_USED_UP = "This file could not be processed"
MIN_AVERAGE_CHARS = 50  # non-whitespace characters per page below which a PDF counts as scanned
_SHA256 = re.compile(r"[0-9a-f]{64}")


def too_many_pages(pages: int, limit: int) -> str:
    return f"This PDF has {pages} pages; the limit is {limit}"


class ContentState(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


def content_key(owner_id: UserId, content_id: ContentId) -> str:
    return f"contents/{owner_id}/{content_id}.pdf"


def pages_key(owner_id: UserId, content_id: ContentId) -> str:
    return f"contents/{owner_id}/{content_id}.pages.json"


def has_text_layer(pages: list[str]) -> bool:
    """False for zero pages or pages averaging under 50 non-whitespace characters (a scan)."""
    return bool(pages) and sum(len("".join(p.split())) for p in pages) / len(pages) >= MIN_AVERAGE_CHARS


@dataclass
class Content:
    content_id: ContentId
    sha256: str
    s3_key: str
    size: int  # column `bytes`
    state: ContentState
    attempts: int
    owner_id: UserId
    failure_reason: str | None = None
    pages: int | None = None
    text_key: str | None = None
    chunker: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None
    # First-pages step (PRD §9.2 step 4); empty until described, and stay empty if the payload was invalid.
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    doi: str | None = None
    summary: str | None = None
    summary_embedding: list[float] | None = None
    proposed_subject_names: list[str] = field(default_factory=list)
    work_key: str | None = None

    @classmethod
    def first_upload(cls, content_id: ContentId, sha256: str, size: int, owner_id: UserId) -> "Content":
        """The learner's first server-verified upload of these bytes starts processing (attempt 1 of 3)."""
        if not _SHA256.fullmatch(sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        key = content_key(owner_id, content_id)
        return cls(content_id, sha256, key, size, ContentState.PROCESSING, 1, owner_id)

    def ready(self, *, pages: int, text_key: str, chunker: str, embedding_model: str, embedding_dim: int) -> None:
        """processing → ready once its chunks are embedded and stored; records how, so a change can be reprocessed."""
        self._require_processing("become ready")
        self.state = ContentState.READY
        self.pages, self.text_key, self.chunker = pages, text_key, chunker
        self.embedding_model, self.embedding_dim = embedding_model, embedding_dim

    def fail(self, reason: str) -> None:
        self._require_processing("fail")
        self.state = ContentState.FAILED
        self.failure_reason = reason

    def can_retry(self, max_attempts: int) -> bool:
        return self.state is ContentState.FAILED and self.attempts < max_attempts

    def retry(self, max_attempts: int) -> None:
        """failed → processing for another attempt (Retry by the owner). At most `max_attempts` in all."""
        if self.state is not ContentState.FAILED:
            raise ContentStateError("Only failed content can be retried")
        if self.attempts >= max_attempts:
            raise RetryLimitError(RETRIES_USED_UP)
        self.state, self.attempts, self.failure_reason = ContentState.PROCESSING, self.attempts + 1, None

    def _require_processing(self, action: str) -> None:
        if self.state is not ContentState.PROCESSING:
            raise ContentStateError(f"Only processing content can {action}")

    @property
    def described(self) -> bool:
        """The first-pages step stored a description (a valid payload always has a title)."""
        return self.title is not None

    def describe(self, description: "DocumentDescription", summary_embedding: list[float]) -> None:
        """Store the first-pages metadata while processing, so the Library can show the title before it ends."""
        self._require_processing("be described")
        self.title, self.authors = description.title, list(description.authors)
        self.year, self.doi, self.summary = description.year, description.doi, description.summary
        self.summary_embedding = list(summary_embedding)
        self.proposed_subject_names = list(description.proposed_subject_names)
        self.work_key = description.work_key

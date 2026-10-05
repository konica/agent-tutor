"""A unique file, keyed by the SHA-256 the server computed from its bytes (PRD §9.4, §9.5; ADR 0002). No owner."""

import re
from dataclasses import dataclass
from enum import StrEnum

from smart_tutor.knowledge.domain.errors import ContentStateError
from smart_tutor.shared.domain.ids import ContentId, UserId

UNREADABLE_PDF = "This file isn't a readable PDF"
NO_TEXT_LAYER = "No text layer (scanned PDFs are not supported yet)"
MIN_AVERAGE_CHARS = 50  # non-whitespace characters per page below which a PDF counts as scanned
_SHA256 = re.compile(r"[0-9a-f]{64}")


def too_many_pages(pages: int, limit: int) -> str:
    return f"This PDF has {pages} pages; the limit is {limit}"


class ContentState(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


def content_key(sha256: str) -> str:
    return f"contents/{sha256}.pdf"


def pages_key(sha256: str) -> str:
    return f"contents/{sha256}.pages.json"


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
    processed_by_user_id: UserId | None
    failure_reason: str | None = None
    pages: int | None = None
    text_key: str | None = None
    chunker: str | None = None
    embedding_model: str | None = None
    embedding_dim: int | None = None

    @classmethod
    def first_upload(cls, content_id: ContentId, sha256: str, size: int, uploader: UserId) -> "Content":
        """The first server-verified upload of these bytes starts processing (attempt 1 of 3)."""
        if not _SHA256.fullmatch(sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return cls(content_id, sha256, content_key(sha256), size, ContentState.PROCESSING, 1, uploader)

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

    def _require_processing(self, action: str) -> None:
        if self.state is not ContentState.PROCESSING:
            raise ContentStateError(f"Only processing content can {action}")

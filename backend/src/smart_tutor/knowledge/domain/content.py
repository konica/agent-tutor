"""A unique file, keyed by the SHA-256 the server computed from its bytes (PRD §9.4, §9.5; ADR 0002). No owner."""

import re
from dataclasses import dataclass
from enum import StrEnum

from smart_tutor.shared.domain.ids import ContentId, UserId

_SHA256 = re.compile(r"[0-9a-f]{64}")


class ContentState(StrEnum):
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


def content_key(sha256: str) -> str:
    return f"contents/{sha256}.pdf"


@dataclass
class Content:
    content_id: ContentId
    sha256: str
    s3_key: str
    size: int  # column `bytes`
    state: ContentState
    attempts: int
    processed_by_user_id: UserId | None

    @classmethod
    def first_upload(cls, content_id: ContentId, sha256: str, size: int, uploader: UserId) -> "Content":
        """The first server-verified upload of these bytes starts processing (attempt 1 of 3)."""
        if not _SHA256.fullmatch(sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return cls(content_id, sha256, content_key(sha256), size, ContentState.PROCESSING, 1, uploader)

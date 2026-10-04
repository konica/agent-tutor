"""One presigned upload, recorded for rate limits and daily caps (PRD §9.4). The key binds it to its learner."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from smart_tutor.shared.domain.ids import UploadId, UserId

_KEY = re.compile(r"uploads/([^/]+)/([^/]+)\.pdf")


class UploadOutcome(StrEnum):
    STORED = "stored"  # new content stored at contents/<sha256>.pdf
    DUPLICATE = "duplicate"  # bytes already known; the document failed (until US-11)


def upload_key(user_id: UserId, upload_id: UploadId) -> str:
    return f"uploads/{user_id}/{upload_id}.pdf"


def parse_upload_key(key: str) -> tuple[UserId, UploadId] | None:
    match = _KEY.fullmatch(key)
    return (UserId(match[1]), UploadId(match[2])) if match else None


@dataclass
class Upload:
    upload_id: UploadId
    user_id: UserId
    created_at: datetime
    size: int | None = None  # column `bytes`, known once the worker reads the upload
    outcome: UploadOutcome | None = None

    @property
    def key(self) -> str:
        return upload_key(self.user_id, self.upload_id)

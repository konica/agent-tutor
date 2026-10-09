"""One presigned upload, recorded for rate limits and daily caps (PRD §9.4). The key binds it to its learner."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from smart_tutor.shared.domain.ids import DocumentId, UploadId, UserId

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_KEY = re.compile(rf"uploads/([^/]+)/({_UUID})\.pdf", re.IGNORECASE)


class UploadOutcome(StrEnum):
    STORED = "stored"  # new content stored at contents/<owner_id>/<content_id>.pdf
    DUPLICATE = "duplicate"  # the learner already has these bytes; the upload points to their document


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
    document_id: DocumentId | None = None  # the document the upload ended in

    @property
    def key(self) -> str:
        return upload_key(self.user_id, self.upload_id)

"""A learner's library entry (PRD §9.4, §9.5). Access: `can_be_read_by` is the domain half of `can_read`."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from smart_tutor.knowledge.domain.errors import DocumentStateError, InvalidFileNameError
from smart_tutor.shared.domain.ids import ContentId, DocumentId, UploadId, UserId

DUPLICATE_UPLOAD = "Duplicate uploads aren't supported yet"  # until US-11 links duplicates
MAX_FILE_NAME = 255
# C0/C1 controls and bidi controls (which can disguise a file name)
_CONTROL = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]")


class DocumentState(StrEnum):
    PROCESSING = "processing"
    AWAITING_SUBJECTS = "awaiting_subjects"
    READY = "ready"
    FAILED = "failed"


def clean_file_name(raw: str) -> str:
    """The bare name the learner picked: no folders, no control characters, at most 255 characters."""
    name = _CONTROL.sub("", raw.replace("\\", "/").rsplit("/", 1)[-1]).strip()[:MAX_FILE_NAME]
    if not name:
        raise InvalidFileNameError("The file needs a name")
    return name


@dataclass
class Document:
    document_id: DocumentId
    owner_id: UserId
    upload_id: UploadId
    file_name: str
    state: DocumentState
    created_at: datetime
    content_id: ContentId | None = None
    failure_reason: str | None = None
    title_override: str | None = None

    @classmethod
    def start_upload(
        cls, document_id: DocumentId, owner_id: UserId, upload_id: UploadId, file_name: str, created_at: datetime
    ) -> "Document":
        """(none) → processing when the upload starts; content_id stays null until the worker hashes the bytes."""
        return cls(document_id, owner_id, upload_id, clean_file_name(file_name), DocumentState.PROCESSING, created_at)

    @property
    def title(self) -> str:
        # Display title = title_override, else contents.title (first-pages step, US-2b), else the file name.
        return self.title_override or self.file_name

    @property
    def awaiting_upload(self) -> bool:
        """Still waiting for the worker to hash its upload."""
        return self.state is DocumentState.PROCESSING and self.content_id is None

    def can_be_read_by(self, user_id: UserId) -> bool:
        return self.owner_id == user_id  # Release 1: owner only (PRD §9.3)

    def link_content(self, content_id: ContentId) -> None:
        if not self.awaiting_upload:
            raise DocumentStateError("This document already has its content")
        self.content_id = content_id

    def fail(self, reason: str) -> None:
        if self.state is not DocumentState.PROCESSING:
            raise DocumentStateError("Only a processing document can fail")
        self.state = DocumentState.FAILED
        self.failure_reason = reason

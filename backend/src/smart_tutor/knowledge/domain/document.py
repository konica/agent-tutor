"""A learner's library entry (PRD §9.4, §9.5). Access: `can_be_read_by` is the domain half of `can_read`."""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from smart_tutor.knowledge.domain.errors import DocumentStateError, InvalidFileNameError, InvalidSubjectsError
from smart_tutor.shared.domain.ids import ContentId, DocumentId, SubjectId, UploadId, UserId

MAX_FILE_NAME = 255
MAX_SUBJECTS = 3
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


@dataclass(frozen=True)
class DocumentFilter:
    """What the Library narrows to (PRD US-10); an empty set or `None` puts no constraint on that part."""

    subject_ids: frozenset[SubjectId] = frozenset()  # a document matches when it has any of them
    states: frozenset[DocumentState] = frozenset()
    uploaded_from: datetime | None = None  # inclusive
    uploaded_before: datetime | None = None  # exclusive
    archived: bool | None = None  # True: only archived; False: only active; None: both


NO_FILTER = DocumentFilter()


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
    content_title: str | None = None  # contents.title, filled when listing; never saved
    content_attempts: int | None = None  # contents.attempts, filled when listing; never saved
    content_authors: list[str] = field(default_factory=list)  # contents.authors, filled when listing; never saved
    content_year: int | None = None  # contents.year, filled when listing; never saved
    subject_ids: list[SubjectId] = field(default_factory=list)
    archived: bool = False

    @classmethod
    def start_upload(
        cls, document_id: DocumentId, owner_id: UserId, upload_id: UploadId, file_name: str, created_at: datetime
    ) -> "Document":
        """(none) → processing when the upload starts; content_id stays null until the worker hashes the bytes."""
        return cls(document_id, owner_id, upload_id, clean_file_name(file_name), DocumentState.PROCESSING, created_at)

    @property
    def title(self) -> str:
        """Display title (PRD §9.4): the learner's override, else the extracted title, else the file name."""
        return self.title_override or self.content_title or self.file_name

    @property
    def awaiting_upload(self) -> bool:
        """Still waiting for the worker to hash its upload."""
        return self.state is DocumentState.PROCESSING and self.content_id is None

    def can_be_read_by(self, user_id: UserId) -> bool:
        return self.owner_id == user_id  # Release 1: owner only (PRD §9.3)

    def searchable_by(self, user_id: UserId) -> bool:
        """`can_read` plus search's own filter: ready and not archived (PRD §9.3 step 4)."""
        return self.can_be_read_by(user_id) and self.state is DocumentState.READY and not self.archived

    def matches(self, document_filter: DocumentFilter) -> bool:
        """The Library filter (PRD US-10); the SQL `WHERE` of `list_readable_by` is its twin."""
        f = document_filter
        return (
            (not f.subject_ids or not f.subject_ids.isdisjoint(self.subject_ids))
            and (not f.states or self.state in f.states)
            and (f.uploaded_from is None or self.created_at >= f.uploaded_from)
            and (f.uploaded_before is None or self.created_at < f.uploaded_before)
            and (f.archived is None or self.archived is f.archived)
        )

    def link_content(self, content_id: ContentId) -> None:
        if not self.awaiting_upload:
            raise DocumentStateError("This document already has its content")
        self.content_id = content_id

    def fail(self, reason: str) -> None:
        if self.state is not DocumentState.PROCESSING:
            raise DocumentStateError("Only a processing document can fail")
        self.state = DocumentState.FAILED
        self.failure_reason = reason

    def await_subjects(self) -> None:
        """processing → awaiting_subjects when its content is ready (PRD §9.5).

        The learner then chooses 1-3 subjects.
        """
        if self.state is not DocumentState.PROCESSING or self.content_id is None:
            raise DocumentStateError("Only a processing document with content can wait for subjects")
        self.state = DocumentState.AWAITING_SUBJECTS

    def choose_subjects(self, subject_ids: list[SubjectId]) -> None:
        """awaiting_subjects (or ready, to change them) → ready with 1-3 different subjects (PRD §9.4, US-2b)."""
        if self.state not in (DocumentState.AWAITING_SUBJECTS, DocumentState.READY):
            raise DocumentStateError("Subjects can be chosen once processing has finished")
        if not 1 <= len(subject_ids) <= MAX_SUBJECTS or len(set(subject_ids)) != len(subject_ids):
            raise InvalidSubjectsError("Choose 1 to 3 different subjects")
        self.subject_ids = list(subject_ids)
        self.state = DocumentState.READY

    def retry(self) -> None:
        """failed → processing when its content is retried."""
        if self.state is not DocumentState.FAILED or self.content_id is None:
            raise DocumentStateError("Only a failed document with content can be retried")
        self.state, self.failure_reason = DocumentState.PROCESSING, None

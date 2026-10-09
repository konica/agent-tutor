"""The learner's library as they see it. Reads go through `can_read` (PRD §9.3)."""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Literal
from zoneinfo import ZoneInfo

from smart_tutor.knowledge.domain.content import RETRIES_USED_UP
from smart_tutor.knowledge.domain.document import Document, DocumentFilter, DocumentState
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, UserId

DocumentStateName = Literal["processing", "awaiting_subjects", "ready", "failed"]
DEFAULT_TIME_ZONE = ZoneInfo("Asia/Ho_Chi_Minh")  # GMT+7 (PRD D27); the API passes the SSM value


@dataclass(frozen=True)
class DocumentView:
    document_id: DocumentId
    title: str
    state: DocumentStateName
    failure_reason: str | None
    created_at: datetime
    subject_ids: tuple[SubjectId, ...]
    authors: tuple[str, ...]  # of the learner's own content; empty until it is described
    year: int | None
    attempt: int | None  # of the learner's own content; None until the upload is hashed
    max_attempts: int
    can_retry: bool
    archived: bool = False


def document_view(d: Document, max_attempts: int) -> DocumentView:
    """How the learner sees a document; a failed one can be retried until its content used up `max_attempts`."""
    attempts = d.content_attempts
    failed = d.state is DocumentState.FAILED and attempts is not None
    used_up = failed and attempts is not None and attempts >= max_attempts
    return DocumentView(
        d.document_id,
        d.title,
        d.state.value,
        RETRIES_USED_UP if used_up else d.failure_reason,
        d.created_at,
        tuple(d.subject_ids),
        tuple(d.content_authors),
        d.content_year,
        attempts,
        max_attempts,
        failed and not used_up,
        d.archived,
    )


class DocumentService:
    def __init__(
        self, uow: Callable[[], LibraryUnitOfWork], max_attempts: int, time_zone: tzinfo = DEFAULT_TIME_ZONE
    ) -> None:
        self._uow, self._max_attempts, self._tz = uow, max_attempts, time_zone

    def list_documents(
        self,
        user_id: UserId,
        *,
        subject_ids: Collection[SubjectId] = (),
        states: Collection[DocumentStateName] = (),
        uploaded_from: date | None = None,
        uploaded_to: date | None = None,
    ) -> list[DocumentView]:
        """The learner's documents, newest first, narrowed by any of the subjects and states and by upload dates.

        Both dates are inclusive calendar days in the app time zone (PRD US-10, D24, D27).
        """
        document_filter = DocumentFilter(
            frozenset(subject_ids),
            frozenset(DocumentState(s) for s in states),
            None if uploaded_from is None else datetime.combine(uploaded_from, time(), tzinfo=self._tz),
            None if uploaded_to is None else datetime.combine(uploaded_to + timedelta(days=1), time(), tzinfo=self._tz),
        )
        with self._uow() as tx:
            documents = tx.documents.list_readable_by(user_id, document_filter)
        return [document_view(d, self._max_attempts) for d in documents]

    def documents_by_id(self, user_id: UserId, document_ids: Collection[DocumentId]) -> dict[DocumentId, DocumentView]:
        """The learner's documents among these ids, archived included; others' and unknown ids are absent."""
        if not document_ids:
            return {}
        with self._uow() as tx:
            documents = tx.documents.list_readable_by_ids(user_id, document_ids)
        return {d.document_id: document_view(d, self._max_attempts) for d in documents}

    def learner_subjects(self, user_id: UserId) -> frozenset[SubjectId]:
        """My subjects: those of the learner's ready, non-archived documents (PRD §9.4)."""
        with self._uow() as tx:
            documents = tx.documents.list_readable_by(user_id)
        return frozenset(s for d in documents if d.state is DocumentState.READY for s in d.subject_ids)

    def has_ready_documents(self, user_id: UserId) -> bool:
        """Whether the learner has a ready, non-archived document to answer from (PRD §8 US-3)."""
        with self._uow() as tx:
            documents = tx.documents.list_readable_by(user_id)
        return any(d.state is DocumentState.READY for d in documents)

    def find_in_library(self, user_id: UserId, sha256: str) -> DocumentId | None:
        """The caller's document holding this file, so the browser can skip uploading it (US-2, D19).

        Answers only from the caller's own documents; it never links content.
        """
        with self._uow() as tx:
            return tx.documents.find_readable_by_sha256(user_id, sha256)

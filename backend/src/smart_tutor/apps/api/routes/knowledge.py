"""Library routes (knowledge module): start an upload, report what became of it (US-11), list the caller's
documents, check a file hash against them, retry a failed one, suggest and save its subjects."""

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from smart_tutor.apps.api.deps import CurrentPrincipal, Documents, Retries, SubjectChoice, Subjects, Uploads
from smart_tutor.knowledge.application import (
    DocumentNotFoundError,
    DocumentStateError,
    DocumentView,
    InvalidFileNameError,
    InvalidSubjectsError,
    RetryLimitError,
)
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, UploadId

router = APIRouter(tags=["knowledge"])


class StartUploadRequest(BaseModel):
    # No user id or key: the key comes from the token (PRD §9.3). Unknown fields are refused.
    model_config = ConfigDict(extra="forbid")
    file_name: str = Field(min_length=1, max_length=1024)


class StartUploadResponse(BaseModel):
    document_id: str
    upload_id: str
    url: str
    fields: dict[str, str]


class UploadLimitsResponse(BaseModel):
    max_bytes: int
    max_pages: int


class UploadStatusResponse(BaseModel):
    upload_id: str
    outcome: Literal["stored", "duplicate"] | None  # null until the worker has hashed the file
    document_id: str | None  # the upload's document, or the learner's existing one for a duplicate
    archived: bool


class DuplicateCheckRequest(BaseModel):
    # Only the hash: the library searched is the caller's, from the token (PRD D19).
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DuplicateCheckResponse(BaseModel):
    document_id: str | None


class SubjectResponse(BaseModel):
    subject_id: str
    name: str


DocumentState = Literal["processing", "awaiting_subjects", "ready", "failed"]


class DocumentResponse(BaseModel):
    document_id: str
    title: str
    state: DocumentState
    failure_reason: str | None
    attempt: int | None  # processing attempts of the learner's own content so far; null until the upload is hashed
    max_attempts: int
    can_retry: bool
    created_at: datetime
    subjects: list[SubjectResponse]
    authors: list[str]  # from the learner's own content; empty when the PDF names none
    year: int | None


class SuggestionResponse(BaseModel):
    subject_id: str | None
    name: str
    origin: Literal["shared", "yours", "new"]


class SubjectSuggestionsResponse(BaseModel):
    document_id: str
    title: str
    summary: str | None
    suggestions: list[SuggestionResponse]


class ChooseSubjectsRequest(BaseModel):
    # Ids of existing subjects and typed or suggested names; a name equal to an existing subject reuses it (PRD D20).
    model_config = ConfigDict(extra="forbid")
    subject_ids: list[UUID] = Field(default_factory=list, max_length=3)
    new_names: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]] = Field(
        default_factory=list, max_length=3
    )


@router.post("/uploads", operation_id="start_upload", status_code=status.HTTP_201_CREATED)
def start_upload(body: StartUploadRequest, principal: CurrentPrincipal, uploads: Uploads) -> StartUploadResponse:
    try:
        started = uploads.start_upload(principal.user_id, body.file_name)
    except InvalidFileNameError as e:
        raise HTTPException(422, str(e)) from None
    return StartUploadResponse(
        document_id=started.document_id, upload_id=started.upload_id, url=started.url, fields=started.fields
    )


@router.get("/uploads/limits", operation_id="get_upload_limits")
def get_upload_limits(uploads: Uploads) -> UploadLimitsResponse:
    """The per-file limits, so the browser can refuse a file before uploading it (PRD §8 US-2)."""
    return UploadLimitsResponse(max_bytes=uploads.limits.max_bytes, max_pages=uploads.limits.max_pages)


@router.get("/uploads/{upload_id}", operation_id="get_upload")
def get_upload(upload_id: UUID, principal: CurrentPrincipal, uploads: Uploads) -> UploadStatusResponse:
    """What became of the caller's upload; a duplicate points to the document they already have (PRD §8 US-11)."""
    found = uploads.upload_status(principal.user_id, UploadId(str(upload_id)))
    if found is None:
        raise HTTPException(404, "Upload not found")
    return UploadStatusResponse(
        upload_id=str(upload_id),
        outcome=found.outcome.value if found.outcome else None,
        document_id=found.document_id,
        archived=found.archived,
    )


@router.post("/documents/duplicate-check", operation_id="check_duplicate")
def check_duplicate(
    body: DuplicateCheckRequest, principal: CurrentPrincipal, documents: Documents
) -> DuplicateCheckResponse:
    """Whether the caller's own library already holds this file, so the browser can skip the upload (PRD §8 US-2).

    Another learner's copy is never reported or linked; the server-side hash decides after upload (D19).
    """
    return DuplicateCheckResponse(document_id=documents.find_in_library(principal.user_id, body.sha256))


def _document_response(view: DocumentView, names: dict[SubjectId, str]) -> DocumentResponse:
    return DocumentResponse(
        document_id=view.document_id,
        title=view.title,
        state=view.state,
        failure_reason=view.failure_reason,
        attempt=view.attempt,
        max_attempts=view.max_attempts,
        can_retry=view.can_retry,
        created_at=view.created_at,
        subjects=[SubjectResponse(subject_id=s, name=names[s]) for s in view.subject_ids if s in names],
        authors=list(view.authors),
        year=view.year,
    )


@router.get("/documents", operation_id="list_documents")
def list_documents(
    principal: CurrentPrincipal,
    documents: Documents,
    subjects: Subjects,
    subject_id: Annotated[list[UUID], Query(max_length=100)] = [],  # noqa: B006 - FastAPI copies the default
    state: Annotated[list[DocumentState], Query()] = [],  # noqa: B006
    uploaded_from: date | None = None,
    uploaded_to: date | None = None,
) -> list[DocumentResponse]:
    """The caller's documents, newest first, narrowed by any subset of the filters (PRD §8 US-10).

    `subject_id` and `state` repeat; a document matches when it has any of the subjects and is in any of the states.
    `uploaded_from` and `uploaded_to` are inclusive calendar days in the app time zone (D27). The filters combine.
    """
    views = documents.list_documents(
        principal.user_id,
        subject_ids=[SubjectId(str(s)) for s in subject_id],
        states=state,
        uploaded_from=uploaded_from,
        uploaded_to=uploaded_to,
    )
    names = subjects.names_for(principal.user_id, {s for d in views for s in d.subject_ids})
    return [_document_response(d, names) for d in views]


@router.get("/documents/{document_id}/subject-suggestions", operation_id="get_subject_suggestions")
def get_subject_suggestions(
    document_id: UUID, principal: CurrentPrincipal, choice: SubjectChoice
) -> SubjectSuggestionsResponse:
    """Three ranked subjects for a processed document, for the learner to choose from (PRD §8 US-2b)."""
    try:
        offered = choice.suggestions(principal.user_id, DocumentId(str(document_id)))
    except DocumentNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except DocumentStateError as e:
        raise HTTPException(409, str(e)) from None
    return SubjectSuggestionsResponse(
        document_id=offered.document_id,
        title=offered.title,
        summary=offered.summary,
        suggestions=[
            SuggestionResponse(subject_id=s.subject_id, name=s.name, origin=s.origin.value) for s in offered.suggestions
        ],
    )


@router.put("/documents/{document_id}/subjects", operation_id="choose_subjects")
def choose_subjects(
    document_id: UUID,
    body: ChooseSubjectsRequest,
    principal: CurrentPrincipal,
    choice: SubjectChoice,
    subjects: Subjects,
) -> DocumentResponse:
    """Save the learner's 1-3 subjects; the document becomes ready to use (PRD §8 US-2b)."""
    try:
        view = choice.choose(
            principal.user_id,
            DocumentId(str(document_id)),
            [SubjectId(str(s)) for s in body.subject_ids],
            body.new_names,
        )
    except DocumentNotFoundError as e:
        raise HTTPException(404, str(e)) from None
    except DocumentStateError as e:
        raise HTTPException(409, str(e)) from None
    except InvalidSubjectsError as e:
        raise HTTPException(422, str(e)) from None
    return _document_response(view, subjects.names_for(principal.user_id, set(view.subject_ids)))


@router.post("/documents/{document_id}/retry", operation_id="retry_document", status_code=status.HTTP_204_NO_CONTENT)
def retry_document(document_id: UUID, principal: CurrentPrincipal, retries: Retries) -> None:
    """Process a failed document's stored file again (PRD §9.5); a document that isn't failed is left as it is."""
    try:
        retries.retry(principal.user_id, DocumentId(str(document_id)))
    except DocumentNotFoundError:
        raise HTTPException(404, "Document not found") from None
    except RetryLimitError as e:
        raise HTTPException(409, str(e)) from None

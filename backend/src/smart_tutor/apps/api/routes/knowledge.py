"""Library routes (knowledge module): upload, list documents, check a file hash, suggest and save subjects."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from smart_tutor.apps.api.deps import CurrentPrincipal, Documents, SubjectChoice, Subjects, Uploads
from smart_tutor.knowledge.application import (
    DocumentNotFoundError,
    DocumentStateError,
    DocumentView,
    InvalidFileNameError,
    InvalidSubjectsError,
)
from smart_tutor.shared.domain.ids import DocumentId, SubjectId

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


class DuplicateCheckRequest(BaseModel):
    # Only the hash: the library searched is the caller's, from the token (PRD D19).
    model_config = ConfigDict(extra="forbid")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DuplicateCheckResponse(BaseModel):
    document_id: str | None


class SubjectResponse(BaseModel):
    subject_id: str
    name: str


class DocumentResponse(BaseModel):
    document_id: str
    title: str
    state: Literal["processing", "awaiting_subjects", "ready", "failed"]
    failure_reason: str | None
    created_at: datetime
    subjects: list[SubjectResponse]


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
    # Ids of existing subjects and names of new ones; both are checked against the suggestions (PRD D20).
    model_config = ConfigDict(extra="forbid")
    subject_ids: list[UUID] = Field(default_factory=list, max_length=3)
    new_names: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(default_factory=list, max_length=3)


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
        created_at=view.created_at,
        subjects=[SubjectResponse(subject_id=s, name=names[s]) for s in view.subject_ids if s in names],
    )


@router.get("/documents", operation_id="list_documents")
def list_documents(principal: CurrentPrincipal, documents: Documents, subjects: Subjects) -> list[DocumentResponse]:
    views = documents.list_documents(principal.user_id)
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

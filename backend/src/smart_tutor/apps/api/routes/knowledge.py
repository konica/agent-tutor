"""Library routes (knowledge module): start an upload, list the caller's documents, retry a failed one."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from smart_tutor.apps.api.deps import CurrentPrincipal, Documents, Retries, Subjects, Uploads
from smart_tutor.knowledge.application import DocumentNotFoundError, InvalidFileNameError, RetryLimitError
from smart_tutor.shared.domain.ids import DocumentId

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


class SubjectResponse(BaseModel):
    subject_id: str
    name: str


class DocumentResponse(BaseModel):
    document_id: str
    title: str
    state: Literal["processing", "awaiting_subjects", "ready", "failed"]
    failure_reason: str | None
    attempt: int | None  # processing attempts of the shared content so far; null until the upload is hashed
    max_attempts: int
    can_retry: bool
    created_at: datetime
    subjects: list[SubjectResponse]


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


@router.get("/documents", operation_id="list_documents")
def list_documents(principal: CurrentPrincipal, documents: Documents, subjects: Subjects) -> list[DocumentResponse]:
    views = documents.list_documents(principal.user_id)
    names = subjects.names_for(principal.user_id, {s for d in views for s in d.subject_ids})
    return [
        DocumentResponse(
            document_id=d.document_id,
            title=d.title,
            state=d.state,
            failure_reason=d.failure_reason,
            attempt=d.attempt,
            max_attempts=d.max_attempts,
            can_retry=d.can_retry,
            created_at=d.created_at,
            subjects=[SubjectResponse(subject_id=s, name=names[s]) for s in d.subject_ids if s in names],
        )
        for d in views
    ]


@router.post("/documents/{document_id}/retry", operation_id="retry_document", status_code=status.HTTP_204_NO_CONTENT)
def retry_document(document_id: UUID, principal: CurrentPrincipal, retries: Retries) -> None:
    """Process a failed document's stored file again (PRD §9.5); a document that isn't failed is left as it is."""
    try:
        retries.retry(principal.user_id, DocumentId(str(document_id)))
    except DocumentNotFoundError:
        raise HTTPException(404, "Document not found") from None
    except RetryLimitError as e:
        raise HTTPException(409, str(e)) from None

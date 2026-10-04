"""Library routes (knowledge module): start an upload, list the caller's documents."""

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from smart_tutor.apps.api.deps import CurrentPrincipal, Documents, Uploads
from smart_tutor.knowledge.application import InvalidFileNameError

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


class DocumentResponse(BaseModel):
    document_id: str
    title: str
    state: Literal["processing", "awaiting_subjects", "ready", "failed"]
    failure_reason: str | None
    created_at: datetime


@router.post("/uploads", operation_id="start_upload", status_code=status.HTTP_201_CREATED)
def start_upload(body: StartUploadRequest, principal: CurrentPrincipal, uploads: Uploads) -> StartUploadResponse:
    try:
        started = uploads.start_upload(principal.user_id, body.file_name)
    except InvalidFileNameError as e:
        raise HTTPException(422, str(e)) from None
    return StartUploadResponse(
        document_id=started.document_id, upload_id=started.upload_id, url=started.url, fields=started.fields
    )


@router.get("/documents", operation_id="list_documents")
def list_documents(principal: CurrentPrincipal, documents: Documents) -> list[DocumentResponse]:
    return [
        DocumentResponse(
            document_id=d.document_id,
            title=d.title,
            state=d.state,
            failure_reason=d.failure_reason,
            created_at=d.created_at,
        )
        for d in documents.list_documents(principal.user_id)
    ]

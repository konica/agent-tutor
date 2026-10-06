"""Request dependencies: who is calling (PRD §9.3, ADR 0007)."""

from typing import Annotated

from fastapi import Depends, Request

from smart_tutor.apps.api.services import ApiServices
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.adapters.auth.bearer import BearerToken, CurrentPrincipal, current_principal
from smart_tutor.subjects.application import SubjectNames

__all__ = ["BearerToken", "CurrentPrincipal", "Documents", "Subjects", "Uploads", "current_principal"]


def _services(request: Request) -> ApiServices:
    services: ApiServices = request.app.state.services
    return services


def _uploads(request: Request) -> UploadService:
    return _services(request).uploads


def _documents(request: Request) -> DocumentService:
    return _services(request).documents


def _subject_names(request: Request) -> SubjectNames:
    return _services(request).subjects


Uploads = Annotated[UploadService, Depends(_uploads)]
Documents = Annotated[DocumentService, Depends(_documents)]
Subjects = Annotated[SubjectNames, Depends(_subject_names)]

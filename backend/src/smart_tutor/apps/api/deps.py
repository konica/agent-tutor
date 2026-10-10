"""Request dependencies: who is calling (PRD §9.3, ADR 0007)."""

from typing import Annotated

from fastapi import Depends, Request

from smart_tutor.apps.api.agent_client import AgentClient
from smart_tutor.apps.api.services import ApiServices
from smart_tutor.insights.application import HighlightMissService
from smart_tutor.knowledge.application import (
    ArchiveService,
    DeleteService,
    DocumentService,
    RetryService,
    SubjectChoiceService,
    UploadService,
    ViewerService,
)
from smart_tutor.shared.adapters.auth.bearer import BearerToken, CurrentPrincipal, current_principal
from smart_tutor.subjects.application import SubjectNames
from smart_tutor.tutoring.application import ConversationService

__all__ = [
    "Agent",
    "Archive",
    "Deletion",
    "BearerToken",
    "Conversations",
    "CurrentPrincipal",
    "Documents",
    "HighlightMisses",
    "Retries",
    "SubjectChoice",
    "Subjects",
    "Uploads",
    "Viewer",
    "current_principal",
]


def _services(request: Request) -> ApiServices:
    services: ApiServices = request.app.state.services
    return services


def _uploads(request: Request) -> UploadService:
    return _services(request).uploads


def _documents(request: Request) -> DocumentService:
    return _services(request).documents


def _retries(request: Request) -> RetryService:
    return _services(request).retries


def _archive(request: Request) -> ArchiveService:
    return _services(request).archive


def _deletion(request: Request) -> DeleteService:
    return _services(request).deletion


def _viewer(request: Request) -> ViewerService:
    return _services(request).viewer


def _subject_choice(request: Request) -> SubjectChoiceService:
    return _services(request).subject_choice


def _subject_names(request: Request) -> SubjectNames:
    return _services(request).subjects


def _conversations(request: Request) -> ConversationService:
    return _services(request).conversations


def _highlight_misses(request: Request) -> HighlightMissService:
    return _services(request).highlight_misses


def _agent(request: Request) -> AgentClient:
    return _services(request).agent


Uploads = Annotated[UploadService, Depends(_uploads)]
Documents = Annotated[DocumentService, Depends(_documents)]
Retries = Annotated[RetryService, Depends(_retries)]
Archive = Annotated[ArchiveService, Depends(_archive)]
Deletion = Annotated[DeleteService, Depends(_deletion)]
Viewer = Annotated[ViewerService, Depends(_viewer)]
Subjects = Annotated[SubjectNames, Depends(_subject_names)]
SubjectChoice = Annotated[SubjectChoiceService, Depends(_subject_choice)]
Conversations = Annotated[ConversationService, Depends(_conversations)]
HighlightMisses = Annotated[HighlightMissService, Depends(_highlight_misses)]
Agent = Annotated[AgentClient, Depends(_agent)]

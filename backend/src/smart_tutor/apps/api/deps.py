"""Request dependencies: who is calling (PRD §9.3, ADR 0007)."""

from typing import Annotated

from fastapi import Depends, Request

from smart_tutor.apps.api.agent_client import AgentClient
from smart_tutor.apps.api.services import ApiServices
from smart_tutor.knowledge.application import DocumentService, RetryService, UploadService
from smart_tutor.shared.adapters.auth.bearer import BearerToken, CurrentPrincipal, current_principal
from smart_tutor.subjects.application import SubjectNames
from smart_tutor.tutoring.application import ConversationService

__all__ = [
    "Agent",
    "BearerToken",
    "Conversations",
    "CurrentPrincipal",
    "Documents",
    "Retries",
    "Subjects",
    "Uploads",
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


def _subject_names(request: Request) -> SubjectNames:
    return _services(request).subjects


def _conversations(request: Request) -> ConversationService:
    return _services(request).conversations


def _agent(request: Request) -> AgentClient:
    return _services(request).agent


Uploads = Annotated[UploadService, Depends(_uploads)]
Documents = Annotated[DocumentService, Depends(_documents)]
Retries = Annotated[RetryService, Depends(_retries)]
Subjects = Annotated[SubjectNames, Depends(_subject_names)]
Conversations = Annotated[ConversationService, Depends(_conversations)]
Agent = Annotated[AgentClient, Depends(_agent)]

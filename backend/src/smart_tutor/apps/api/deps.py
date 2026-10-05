"""Request dependencies: who is calling (PRD §9.3, ADR 0007)."""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from smart_tutor.apps.api.services import ApiServices
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.domain.errors import IntrospectionUnavailableError, UnauthenticatedError
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.shared.ports.token_verifier import TokenVerifier
from smart_tutor.subjects.application import SubjectNames

logger = logging.getLogger(__name__)

# auto_error=False: we answer 401 ourselves (FastAPI's default for a missing header is 403).
_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


async def current_principal(
    request: Request, credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials.strip():
        raise _unauthorized()
    verifier: TokenVerifier = request.app.state.verifier
    try:
        return await verifier.verify(credentials.credentials.strip())
    except IntrospectionUnavailableError as e:
        # Keycloak outage or a wrong client secret: ours to fix, so louder than a bad token.
        logger.warning("token check unavailable for %s: %s", request.url.path, e)  # the reason only, never the token
        raise _unauthorized() from None
    except UnauthenticatedError as e:
        logger.info("rejected request to %s: %s", request.url.path, e)  # the reason only, never the token
        raise _unauthorized() from None


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


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

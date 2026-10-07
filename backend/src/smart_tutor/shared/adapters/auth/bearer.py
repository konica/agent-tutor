"""FastAPI dependencies for the caller's bearer token (PRD §9.3, ADR 0007), shared by the API and the agent.

The app puts its `TokenVerifier` on `app.state.verifier`. Every failure is a 401 with `WWW-Authenticate: Bearer`,
and logs carry the reason only, never the token.
"""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from smart_tutor.shared.domain.errors import IntrospectionUnavailableError, UnauthenticatedError
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.shared.ports.token_verifier import TokenVerifier

logger = logging.getLogger(__name__)

# auto_error=False: we answer 401 ourselves (FastAPI's default for a missing header is 403).
_bearer = HTTPBearer(auto_error=False)


def _unauthorized() -> HTTPException:
    return HTTPException(status_code=401, detail="Not authenticated", headers={"WWW-Authenticate": "Bearer"})


def bearer_token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]) -> str:
    """The raw token from `Authorization: Bearer <token>`; 401 when missing, blank, or another scheme."""
    if credentials is None or credentials.scheme.lower() != "bearer" or not credentials.credentials.strip():
        raise _unauthorized()
    return credentials.credentials.strip()


BearerToken = Annotated[str, Depends(bearer_token)]


async def current_principal(request: Request, token: BearerToken) -> Principal:
    verifier: TokenVerifier = request.app.state.verifier
    try:
        return await verifier.verify(token)
    except IntrospectionUnavailableError as e:
        # Keycloak outage or a wrong client secret: ours to fix, so louder than a bad token.
        logger.warning("token check unavailable for %s: %s", request.url.path, e)  # the reason only, never the token
        raise _unauthorized() from None
    except UnauthenticatedError as e:
        logger.info("rejected request to %s: %s", request.url.path, e)  # the reason only, never the token
        raise _unauthorized() from None


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]

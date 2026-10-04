"""Keycloak token introspection (RFC 7662), the token check on every hop (ADR 0007).

Ported from the #29 prototype (`prototype/29-jwt-forwarding`, verify.py).
"""

from typing import Any

import httpx

from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.shared.ports.token_verifier import TokenVerifier


class KeycloakIntrospectionVerifier(TokenVerifier):
    def __init__(
        self,
        *,
        introspection_url: str,
        issuer: str,
        audience: str,
        client_id: str,
        client_secret: str,
        http: httpx.AsyncClient,
    ) -> None:
        self._url = introspection_url
        self._issuer = issuer
        self._audience = audience
        self._auth = (client_id, client_secret)
        self._http = http

    async def verify(self, token: str) -> Principal:
        if not token:
            raise UnauthenticatedError("empty token")
        try:
            response = await self._http.post(
                self._url, data={"token": token, "token_type_hint": "access_token"}, auth=self._auth
            )
            response.raise_for_status()
            claims: Any = response.json()
        except (httpx.HTTPError, ValueError) as e:
            raise UnauthenticatedError(f"introspection failed: {type(e).__name__}") from None
        if not isinstance(claims, dict) or claims.get("active") is not True:
            raise UnauthenticatedError("inactive token")
        aud = claims.get("aud", [])
        audiences = [aud] if isinstance(aud, str) else list(aud)
        if self._audience not in audiences:
            raise UnauthenticatedError("token is for another audience")
        if claims.get("iss") != self._issuer:
            raise UnauthenticatedError("token from another issuer")
        sub = claims.get("sub")
        if not isinstance(sub, str) or not sub:
            raise UnauthenticatedError("token has no subject")
        roles = claims.get("realm_access", {}).get("roles", [])
        return Principal(user_id=UserId(sub), name=_display_name(claims), roles=frozenset(roles))


def _display_name(claims: dict[str, Any]) -> str:
    given = " ".join(p for p in (claims.get("given_name"), claims.get("family_name")) if p)
    return str(claims.get("name") or given or claims.get("preferred_username") or "Learner")


def keycloak_verifier(settings: Settings, http: httpx.AsyncClient) -> KeycloakIntrospectionVerifier:
    return KeycloakIntrospectionVerifier(
        introspection_url=settings.keycloak_introspection_url,
        issuer=settings.keycloak_issuer,
        audience=settings.keycloak_audience,
        client_id=settings.keycloak_client_id,
        client_secret=settings.keycloak_client_secret.get_secret_value(),
        http=http,
    )

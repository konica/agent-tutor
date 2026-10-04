"""Against the Compose Keycloak (`make up`, realm re-imported after Task 1)."""

import httpx
import pytest

from smart_tutor.shared.adapters.auth.keycloak_introspection import KeycloakIntrospectionVerifier
from smart_tutor.shared.domain.errors import IntrospectionUnavailableError, UnauthenticatedError

pytestmark = pytest.mark.integration

ISSUER = "http://localhost:10480/realms/smart-tutor"


def verifier(secret: str) -> KeycloakIntrospectionVerifier:
    return KeycloakIntrospectionVerifier(
        introspection_url=f"{ISSUER}/protocol/openid-connect/token/introspect",
        issuer=ISSUER,
        audience="smart-tutor-api",
        client_id="smart-tutor-api",
        client_secret=secret,
        http=httpx.AsyncClient(timeout=5),
    )


async def test_a_made_up_token_is_inactive() -> None:
    with pytest.raises(UnauthenticatedError, match="inactive"):
        await verifier("local-api-secret").verify("not-a-real-token")


async def test_a_wrong_client_secret_is_rejected() -> None:
    with pytest.raises(IntrospectionUnavailableError, match="introspection failed"):
        await verifier("wrong-secret").verify("not-a-real-token")

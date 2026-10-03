"""PROTOTYPE (#29) — throwaway. Keycloak JWT check shared by the three prototype services.

Two settings, on purpose: the *issuer* the token claims (the URL the browser used) and the
*JWKS URL* the service can actually reach. In Compose they differ: the browser talks to
localhost:8080, containers must talk to keycloak:8080.
"""

import os

import jwt

ISSUER = os.environ.get("PROTO_ISSUER", "http://localhost:8080/realms/smart-tutor")
JWKS_URL = os.environ.get("PROTO_JWKS_URL", f"{ISSUER}/protocol/openid-connect/certs")

_jwks = jwt.PyJWKClient(JWKS_URL, cache_keys=True, lifespan=300)


class Unauthorized(Exception):
    pass


def verify(token: str, audience: str) -> dict:
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        return jwt.decode(
            token,
            key,
            algorithms=["RS256"],
            audience=audience,
            issuer=ISSUER,
            options={"require": ["exp", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as e:  # includes PyJWKClientError (JWKS unreachable)
        raise Unauthorized(f"{type(e).__name__}: {e}") from e


def bearer(header: str | None) -> str:
    if not header or not header.lower().startswith("bearer "):
        raise Unauthorized("missing bearer token")
    return header[7:]

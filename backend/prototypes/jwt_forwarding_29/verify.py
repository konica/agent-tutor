"""PROTOTYPE (#29) — throwaway. Token check shared by the three prototype services.

Keycloak decides (PR #37 review): each service sends the token to Keycloak's introspection endpoint
(RFC 7662) as its own confidential client, so logged-out or revoked tokens fail immediately.

Two URLs, on purpose: the *issuer* the token claims (the URL the browser used) and the *internal URL* a
container can reach. In Compose they differ: the browser talks to localhost:8080, containers to keycloak:8080.
Keycloak must pin its hostname (KC_HOSTNAME) or it reports such tokens as inactive.
"""

import os
import time

import httpx

ISSUER = os.environ.get("PROTO_ISSUER", "http://localhost:8080/realms/smart-tutor")
INTERNAL = os.environ.get("PROTO_KEYCLOAK_INTERNAL_URL", ISSUER)
INTROSPECT_URL = f"{INTERNAL}/protocol/openid-connect/token/introspect"
CLIENT_ID = os.environ["PROTO_CLIENT_ID"]
CLIENT_SECRET = os.environ["PROTO_CLIENT_SECRET"]

_http = httpx.AsyncClient(timeout=5, auth=(CLIENT_ID, CLIENT_SECRET))


class Unauthorized(Exception):
    pass


async def verify(token: str, audience: str) -> dict:
    t0 = time.perf_counter()
    try:
        r = await _http.post(INTROSPECT_URL, data={"token": token, "token_type_hint": "access_token"})
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise Unauthorized(f"introspection failed: {type(e).__name__}") from e
    claims = r.json()
    ms = (time.perf_counter() - t0) * 1000
    aud = claims.get("aud", [])
    aud = [aud] if isinstance(aud, str) else aud
    if not claims.get("active"):
        raise Unauthorized(f"inactive ({ms:.1f} ms)")
    if audience not in aud or claims.get("iss") != ISSUER or not claims.get("sub"):
        raise Unauthorized(f"wrong aud/iss/sub ({ms:.1f} ms)")
    print(f"[{CLIENT_ID}] introspected active token in {ms:.1f} ms", flush=True)
    return claims


def bearer(header: str | None) -> str:
    if not header or not header.lower().startswith("bearer "):
        raise Unauthorized("missing bearer token")
    return header[7:]

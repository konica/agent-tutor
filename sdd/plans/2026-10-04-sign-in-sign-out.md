# Sign in and sign out; the API rejects unauthenticated calls — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A learner signs in through Keycloak, lands on the empty Library with their real name in the UserMenu, and can sign out; the API accepts only tokens Keycloak says are active, answers `401` otherwise, and serves `GET /me`.

**Architecture:** One `TokenVerifier` port in `shared.ports`, implemented by a Keycloak token-introspection adapter in `shared.adapters.auth` (ADR 0007), used by a FastAPI dependency that guards every non-public route. Alembic starts with an empty baseline run by a `migrate` job. The web app gets a typed client generated from the API's OpenAPI schema (`@hey-api/openapi-ts`) and a `SessionProvider` that signs in with `keycloak-js` (code + PKCE), refreshes the token before every call, loads `/me`, and shows "Please sign in again" on a 401.

**Tech Stack:** FastAPI, httpx, pydantic-settings, Alembic, SQLAlchemy 2, pytest; React 19, React Router 8, `keycloak-js` 26, `@hey-api/openapi-ts` 0.99, Vitest + Testing Library; Keycloak 26.3 in Docker Compose.

**Spec:** GitHub issue #45 (slice 1 of US-1 #8; PRD §8 US-1, §9.3), the walking-skeleton decision in #31, ADR 0007 (`sdd/adr/0007-*.md`), prototype findings on branch `prototype/29-jwt-forwarding` (`backend/prototypes/jwt_forwarding_29/README.md`).

## Global Constraints

- Every service checks a token by **Keycloak introspection** (`<internal realm URL>/protocol/openid-connect/token/introspect`, HTTP Basic as its own confidential client). Accept only: `active: true`; `aud` (string or list) contains the service's audience; `iss` equals the configured public issuer; non-empty `sub`. Anything else — including Keycloak unreachable, 5xx, or non-JSON — is `401`.
- `401` responses carry `WWW-Authenticate: Bearer`.
- Public issuer `http://localhost:8080/realms/smart-tutor`; services in Compose call Keycloak at `http://keycloak:8080/realms/smart-tutor`; outside Compose the internal URL defaults to the issuer.
- Compose Keycloak pins `KC_HOSTNAME=http://localhost:8080` and `KC_HOSTNAME_BACKCHANNEL_DYNAMIC=true`.
- The API and agent introspect as `smart-tutor-api`; the MCP server as `rag-mcp`. Both are confidential clients with local-only secrets `local-api-secret` / `local-mcp-secret`.
- Tokens never appear in logs, exception messages, prompts, or traces.
- The web app calls `updateToken(60)` before every API call; a `401` (or a failed refresh) shows **"Please sign in again"**.
- Web API calls go only through the generated client in `web/src/api/`; no hand-written `fetch`.
- UI: rebuild with `web/src/components/` and `var(--…)` tokens only (`DESIGN.md`); copy strings: "Upload your first document", "Sign out", "Please sign in again".
- Endpoints take no user id; the caller is always the token's `sub`.
- Backend layering (`backend/AGENTS.md`): vendor SDKs (httpx, sqlalchemy, alembic, fastapi) only in `adapters/` and `apps/`; `shared` imports no feature module.
- Commits: imperative subject, body says why, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **A 401 without CORS headers** — the browser hides the status and the app shows a network error instead of "Please sign in again". Pinned in Task 3 (`test_401_carries_cors_headers`).
2. **Keycloak down or answering 5xx/garbage** — must be `401`, never `500` or a hang. Pinned in Task 2 (`test_rejects_when_keycloak_unreachable`, `..._returns_500`, `..._returns_non_json`).
3. **React StrictMode double-mounting** — `keycloak-js` throws if `init` runs twice. Pinned in Task 6 (`init runs keycloak once`).
4. **Refresh fails after a long idle (refresh token expired)** — must show "Please sign in again", not a silent failure or a request without a token. Pinned in Task 6 (`getToken failure notifies and sends nothing`).
5. **A route added later without auth** — every non-public route must answer `401` without a token. Pinned in Task 3 (`test_every_route_requires_a_token`).

---

## File structure

```
backend/
  alembic.ini                                                    # dev entry for `alembic revision`
  src/smart_tutor/shared/config.py                               # + Keycloak internal URL, client creds, CORS
  src/smart_tutor/shared/domain/principal.py                     # Principal (caller identity, no token)
  src/smart_tutor/shared/domain/errors.py                        # + UnauthenticatedError
  src/smart_tutor/shared/ports/token_verifier.py                 # TokenVerifier ABC
  src/smart_tutor/shared/adapters/auth/keycloak_introspection.py # KeycloakIntrospectionVerifier
  src/smart_tutor/shared/adapters/postgres/migrate.py            # upgrade_to_head()
  src/smart_tutor/shared/adapters/postgres/migrations/           # env.py, script.py.mako, versions/0001_baseline.py
  src/smart_tutor/apps/api/main.py                               # create_app(): CORS, auth, routers
  src/smart_tutor/apps/api/deps.py                               # current_principal dependency
  src/smart_tutor/apps/api/routes/accounts.py                    # GET /me
  src/smart_tutor/apps/api/openapi_export.py                     # writes web/src/api/openapi.json
  src/smart_tutor/apps/jobs/migrate.py                           # `python -m ... migrate`
  tests/fakes/auth.py                                            # FakeTokenVerifier
  tests/unit/shared/auth/test_keycloak_introspection.py
  tests/unit/shared/test_config.py
  tests/unit/test_local_realm.py
  tests/unit/apps/api/test_auth.py
  tests/unit/apps/api/test_openapi_snapshot.py
  tests/isolation/test_me.py
  tests/integration/shared/test_keycloak_introspection.py
  tests/integration/shared/test_migrations.py
web/
  openapi-ts.config.ts
  src/vite-env.d.ts
  src/api/openapi.json, src/api/generated/**                     # generated, committed
  src/api/client.ts, src/api/client.test.ts                      # token + 401 interceptors
  src/api/me.ts                                                  # loadMe()
  src/auth/authClient.ts                                         # AuthClient type, SessionExpiredError, sessionExpiry
  src/auth/keycloakClient.ts, keycloakClient.test.ts             # keycloak-js adapter
  src/auth/SessionProvider.tsx, SessionProvider.test.tsx, SessionProvider.module.css
  src/components/SideNav/SideNav.tsx                             # real name + Sign out
  src/main.tsx                                                   # wiring
local/keycloak/realm-smart-tutor.json, compose.yaml, .env.example, Makefile, .github/workflows/ci.yml
```

---

### Task 1: Keycloak clients, Compose hostname, and settings

**Files:**
- Modify: `local/keycloak/realm-smart-tutor.json` (clients `smart-tutor-api`, `rag-mcp`)
- Modify: `compose.yaml` (keycloak env; api/agent/mcp env)
- Modify: `.env.example`
- Modify: `backend/src/smart_tutor/shared/config.py`
- Test: `backend/tests/unit/test_local_realm.py`, `backend/tests/unit/shared/test_config.py`

**Interfaces:**
- Produces: `Settings.keycloak_internal_url: str | None`, `Settings.keycloak_client_id: str` (default `"smart-tutor-api"`), `Settings.keycloak_client_secret: SecretStr`, `Settings.cors_origins: list[str]`, property `Settings.keycloak_introspection_url -> str`. Existing `keycloak_issuer`, `keycloak_audience` unchanged.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/shared/test_config.py`:

```python
from smart_tutor.shared.config import Settings

ISSUER = "http://localhost:8080/realms/smart-tutor"


def test_introspection_url_defaults_to_the_issuer() -> None:
    s = Settings(keycloak_issuer=ISSUER, keycloak_internal_url=None)
    assert s.keycloak_introspection_url == f"{ISSUER}/protocol/openid-connect/token/introspect"


def test_introspection_url_uses_the_internal_url_when_set() -> None:
    s = Settings(keycloak_issuer=ISSUER, keycloak_internal_url="http://keycloak:8080/realms/smart-tutor/")
    assert s.keycloak_introspection_url == (
        "http://keycloak:8080/realms/smart-tutor/protocol/openid-connect/token/introspect"
    )


def test_client_secret_is_not_printed() -> None:
    s = Settings(keycloak_client_secret="local-api-secret")
    assert "local-api-secret" not in repr(s)
```

`backend/tests/unit/test_local_realm.py`:

```python
"""The Compose realm matches ADR 0007: resource clients are confidential so they can introspect."""

import json
from pathlib import Path
from typing import Any

REALM = Path(__file__).parents[3] / "local" / "keycloak" / "realm-smart-tutor.json"


def _client(client_id: str) -> dict[str, Any]:
    realm = json.loads(REALM.read_text(encoding="utf-8"))
    return next(c for c in realm["clients"] if c["clientId"] == client_id)


def test_resource_clients_are_confidential_without_login_flows() -> None:
    for client_id in ("smart-tutor-api", "rag-mcp"):
        c = _client(client_id)
        assert c["publicClient"] is False
        assert c["bearerOnly"] is False
        assert c["clientAuthenticatorType"] == "client-secret"
        assert c["secret"]
        assert c["standardFlowEnabled"] is False
        assert c["directAccessGrantsEnabled"] is False
        assert c["serviceAccountsEnabled"] is False


def test_web_client_can_log_out_back_to_the_app() -> None:
    c = _client("smart-tutor-web")
    assert c["publicClient"] is True
    assert c["attributes"]["pkce.code.challenge.method"] == "S256"
    assert c["attributes"]["post.logout.redirect.uris"] == "http://localhost:5173/*"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/shared/test_config.py tests/unit/test_local_realm.py -v`
Expected: FAIL (`keycloak_introspection_url` missing; `bearerOnly` is `True`).

- [ ] **Step 3: Implement**

In `config.py`, import `SecretStr` from pydantic and add to `Settings` (after `keycloak_audience`):

```python
    # How services reach Keycloak. In Compose this differs from the issuer the browser sees (ADR 0007).
    keycloak_internal_url: str | None = None
    # This service's confidential client for token introspection: smart-tutor-api (API, agent) or rag-mcp (MCP).
    keycloak_client_id: str = "smart-tutor-api"
    keycloak_client_secret: SecretStr = SecretStr("")
    cors_origins: list[str] = ["http://localhost:5173"]
```

and, at the end of the class:

```python
    @property
    def keycloak_introspection_url(self) -> str:
        base = (self.keycloak_internal_url or self.keycloak_issuer).rstrip("/")
        return f"{base}/protocol/openid-connect/token/introspect"
```

In the realm file, replace the two resource clients with:

```json
    {
      "clientId": "smart-tutor-api",
      "name": "Smart Tutor API and agent (token introspection)",
      "publicClient": false,
      "bearerOnly": false,
      "clientAuthenticatorType": "client-secret",
      "secret": "local-api-secret",
      "standardFlowEnabled": false,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": false
    },
    {
      "clientId": "rag-mcp",
      "name": "RAG MCP server (token introspection)",
      "publicClient": false,
      "bearerOnly": false,
      "clientAuthenticatorType": "client-secret",
      "secret": "local-mcp-secret",
      "standardFlowEnabled": false,
      "implicitFlowEnabled": false,
      "directAccessGrantsEnabled": false,
      "serviceAccountsEnabled": false
    }
```

In `compose.yaml`, add to `keycloak.environment`:

```yaml
      # Tokens are issued to the browser at localhost:8080; containers introspect them at keycloak:8080.
      # Without a pinned hostname Keycloak reports such tokens as inactive (ADR 0007).
      KC_HOSTNAME: http://localhost:8080
      KC_HOSTNAME_BACKCHANNEL_DYNAMIC: "true"
```

Add to `api.environment` and `agent.environment`:

```yaml
      SMART_TUTOR_KEYCLOAK_ISSUER: http://localhost:8080/realms/smart-tutor
      SMART_TUTOR_KEYCLOAK_INTERNAL_URL: http://keycloak:8080/realms/smart-tutor
      SMART_TUTOR_KEYCLOAK_CLIENT_ID: smart-tutor-api
      SMART_TUTOR_KEYCLOAK_CLIENT_SECRET: local-api-secret
```

(`api` already has the issuer line; don't duplicate it.) Add to `mcp.environment`:

```yaml
      SMART_TUTOR_KEYCLOAK_ISSUER: http://localhost:8080/realms/smart-tutor
      SMART_TUTOR_KEYCLOAK_INTERNAL_URL: http://keycloak:8080/realms/smart-tutor
      SMART_TUTOR_KEYCLOAK_CLIENT_ID: rag-mcp
      SMART_TUTOR_KEYCLOAK_CLIENT_SECRET: local-mcp-secret
      SMART_TUTOR_KEYCLOAK_AUDIENCE: rag-mcp
```

In `.env.example`, after `SMART_TUTOR_KEYCLOAK_ISSUER=...`:

```bash
# Token introspection client (local realm secret; ADR 0007). On the host the internal URL defaults to the issuer.
SMART_TUTOR_KEYCLOAK_CLIENT_ID=smart-tutor-api
SMART_TUTOR_KEYCLOAK_CLIENT_SECRET=local-api-secret
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/shared/test_config.py tests/unit/test_local_realm.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add local/keycloak/realm-smart-tutor.json compose.yaml .env.example backend/src/smart_tutor/shared/config.py backend/tests/unit/shared/test_config.py backend/tests/unit/test_local_realm.py
git commit -m "Make the API and MCP clients confidential and pin Keycloak's hostname" -m "Token introspection (ADR 0007) needs client credentials, and Compose containers must see browser-issued tokens as active. Run docker compose down -v to re-import the realm."
```

---

### Task 2: Token verifier (port and Keycloak introspection adapter)

**Files:**
- Create: `backend/src/smart_tutor/shared/domain/principal.py`
- Modify: `backend/src/smart_tutor/shared/domain/errors.py`
- Create: `backend/src/smart_tutor/shared/ports/token_verifier.py`
- Create: `backend/src/smart_tutor/shared/adapters/auth/keycloak_introspection.py`
- Create: `backend/tests/fakes/auth.py`; modify `backend/tests/fakes/__init__.py`
- Test: `backend/tests/unit/shared/auth/test_keycloak_introspection.py`, `backend/tests/integration/shared/test_keycloak_introspection.py`

**Interfaces:**
- Consumes: `Settings.keycloak_introspection_url`, `keycloak_issuer`, `keycloak_audience`, `keycloak_client_id`, `keycloak_client_secret` (Task 1); `UserId` from `shared.domain.ids`.
- Produces:
  - `Principal(user_id: UserId, name: str, roles: frozenset[str])` — frozen dataclass.
  - `UnauthenticatedError(Exception)` in `shared.domain.errors`.
  - `TokenVerifier` ABC: `async def verify(self, token: str) -> Principal` (raises `UnauthenticatedError`).
  - `KeycloakIntrospectionVerifier(*, introspection_url: str, issuer: str, audience: str, client_id: str, client_secret: str, http: httpx.AsyncClient)`.
  - `keycloak_verifier(settings: Settings, http: httpx.AsyncClient) -> KeycloakIntrospectionVerifier`.
  - Test fake `FakeTokenVerifier` with `add(token: str, principal: Principal) -> None`, `revoke(token: str) -> None`, `calls: int`; exported from `fakes`.

- [ ] **Step 1: Write the failing unit tests**

`backend/tests/unit/shared/auth/test_keycloak_introspection.py`:

```python
import base64
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from smart_tutor.shared.adapters.auth.keycloak_introspection import KeycloakIntrospectionVerifier
from smart_tutor.shared.domain.errors import UnauthenticatedError

ISSUER = "http://localhost:8080/realms/smart-tutor"
URL = "http://keycloak:8080/realms/smart-tutor/protocol/openid-connect/token/introspect"
TOKEN = "eyJ.secret-token-value.sig"


def active(**overrides: Any) -> dict[str, Any]:
    claims: dict[str, Any] = {
        "active": True,
        "sub": "user-1",
        "aud": ["smart-tutor-api", "rag-mcp", "account"],
        "iss": ISSUER,
        "name": "Local Learner",
        "realm_access": {"roles": ["learner", "offline_access"]},
    }
    claims.update(overrides)
    return claims


def verifier(handler: Callable[[httpx.Request], httpx.Response]) -> KeycloakIntrospectionVerifier:
    return KeycloakIntrospectionVerifier(
        introspection_url=URL,
        issuer=ISSUER,
        audience="smart-tutor-api",
        client_id="smart-tutor-api",
        client_secret="s3cret",
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def returning(claims: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    return lambda _req: httpx.Response(200, json=claims)


async def test_accepts_an_active_token() -> None:
    principal = await verifier(returning(active())).verify(TOKEN)
    assert principal.user_id == "user-1"
    assert principal.name == "Local Learner"
    assert principal.roles == frozenset({"learner", "offline_access"})


async def test_sends_the_token_as_form_data_with_client_credentials() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=active())

    await verifier(handler).verify(TOKEN)
    req = seen[0]
    assert str(req.url) == URL
    assert req.method == "POST"
    assert parse_qs(req.content.decode()) == {"token": [TOKEN], "token_type_hint": ["access_token"]}
    assert req.headers["Authorization"] == "Basic " + base64.b64encode(b"smart-tutor-api:s3cret").decode()


async def test_accepts_a_single_string_audience() -> None:
    principal = await verifier(returning(active(aud="smart-tutor-api"))).verify(TOKEN)
    assert principal.user_id == "user-1"


@pytest.mark.parametrize(
    "claims",
    [
        {"active": False},
        active(active="true"),  # only the JSON boolean counts
        active(aud=["rag-mcp", "account"]),
        active(aud="rag-mcp"),
        active(iss="http://evil.example/realms/smart-tutor"),
        active(sub=""),
        {k: v for k, v in active().items() if k != "sub"},
    ],
    ids=["inactive", "active-as-string", "wrong-aud-list", "wrong-aud-string", "wrong-iss", "empty-sub", "no-sub"],
)
async def test_rejects_tokens_that_fail_a_check(claims: dict[str, Any]) -> None:
    with pytest.raises(UnauthenticatedError):
        await verifier(returning(claims)).verify(TOKEN)


async def test_rejects_when_keycloak_returns_500() -> None:
    with pytest.raises(UnauthenticatedError):
        await verifier(lambda _req: httpx.Response(500)).verify(TOKEN)


async def test_rejects_when_keycloak_returns_non_json() -> None:
    with pytest.raises(UnauthenticatedError):
        await verifier(lambda _req: httpx.Response(200, text="<html>")).verify(TOKEN)


async def test_rejects_when_keycloak_unreachable() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(UnauthenticatedError):
        await verifier(handler).verify(TOKEN)


async def test_rejects_an_empty_token_without_calling_keycloak() -> None:
    def handler(_req: httpx.Request) -> httpx.Response:
        raise AssertionError("Keycloak must not be called")

    with pytest.raises(UnauthenticatedError):
        await verifier(handler).verify("")


async def test_error_messages_never_contain_the_token() -> None:
    with pytest.raises(UnauthenticatedError) as err:
        await verifier(returning({"active": False})).verify(TOKEN)
    assert "secret-token-value" not in str(err.value)


@pytest.mark.parametrize(
    ("claims", "name"),
    [
        (active(name="Ada Lovelace"), "Ada Lovelace"),
        ({**{k: v for k, v in active().items() if k != "name"}, "given_name": "Ada", "family_name": "L"}, "Ada L"),
        ({**{k: v for k, v in active().items() if k != "name"}, "preferred_username": "ada@example.com"}, "ada@example.com"),
        ({k: v for k, v in active().items() if k != "name"}, "Learner"),
    ],
    ids=["name", "given-family", "username", "fallback"],
)
async def test_display_name(claims: dict[str, Any], name: str) -> None:
    assert (await verifier(returning(claims)).verify(TOKEN)).name == name


async def test_missing_roles_mean_no_roles() -> None:
    claims = {k: v for k, v in active().items() if k != "realm_access"}
    assert (await verifier(returning(claims)).verify(TOKEN)).roles == frozenset()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/shared/auth -v`
Expected: FAIL with `ModuleNotFoundError: smart_tutor.shared.adapters.auth.keycloak_introspection`.

- [ ] **Step 3: Implement**

`backend/src/smart_tutor/shared/domain/principal.py`:

```python
"""The signed-in caller."""

from dataclasses import dataclass

from smart_tutor.shared.domain.ids import UserId


@dataclass(frozen=True)
class Principal:
    """Who is calling, from a token Keycloak says is active (ADR 0007). Never holds the token itself."""

    user_id: UserId
    name: str
    roles: frozenset[str]
```

Append to `backend/src/smart_tutor/shared/domain/errors.py`:

```python


class UnauthenticatedError(Exception):
    """No valid credentials: the token is missing, inactive, for another audience, or can't be checked.

    Messages give the reason only, never the token.
    """
```

`backend/src/smart_tutor/shared/ports/token_verifier.py`:

```python
"""Checks a bearer token and returns the caller (PRD §9.3, ADR 0007)."""

from abc import ABC, abstractmethod

from smart_tutor.shared.domain.principal import Principal


class TokenVerifier(ABC):
    @abstractmethod
    async def verify(self, token: str) -> Principal:
        """Return the caller for an active token; raise UnauthenticatedError otherwise."""
```

`backend/src/smart_tutor/shared/adapters/auth/keycloak_introspection.py`:

```python
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
```

`backend/tests/fakes/auth.py`:

```python
"""A token verifier for tests: tokens are whatever the test registers."""

from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.shared.ports.token_verifier import TokenVerifier


class FakeTokenVerifier(TokenVerifier):
    def __init__(self) -> None:
        self._tokens: dict[str, Principal] = {}
        self.calls = 0

    def add(self, token: str, principal: Principal) -> None:
        self._tokens[token] = principal

    def revoke(self, token: str) -> None:
        """Like a Keycloak logout: the token stops being active."""
        self._tokens.pop(token, None)

    async def verify(self, token: str) -> Principal:
        self.calls += 1
        try:
            return self._tokens[token]
        except KeyError:
            raise UnauthenticatedError("unknown token") from None
```

In `backend/tests/fakes/__init__.py`, add `from fakes.auth import FakeTokenVerifier` and add `"FakeTokenVerifier"` to `__all__` (create `__all__` if missing, listing the existing exports too).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/shared/auth -v && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: all PASS; contracts kept.

- [ ] **Step 5: Add the Compose integration test**

`backend/tests/integration/shared/test_keycloak_introspection.py`:

```python
"""Against the Compose Keycloak (`make up`, realm re-imported after Task 1)."""

import httpx
import pytest

from smart_tutor.shared.adapters.auth.keycloak_introspection import KeycloakIntrospectionVerifier
from smart_tutor.shared.domain.errors import UnauthenticatedError

pytestmark = pytest.mark.integration

ISSUER = "http://localhost:8080/realms/smart-tutor"


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
    with pytest.raises(UnauthenticatedError, match="introspection failed"):
        await verifier("wrong-secret").verify("not-a-real-token")
```

Run (with `docker compose down -v && docker compose up -d` done): `cd backend && uv run pytest -m integration tests/integration/shared/test_keycloak_introspection.py -v`
Expected: PASS. (If Compose isn't available to the implementer, note it in the task report; CI doesn't run integration tests.)

- [ ] **Step 6: Commit**

```bash
git add backend/src/smart_tutor/shared backend/tests/fakes backend/tests/unit/shared/auth backend/tests/integration/shared
git commit -m "Check tokens by Keycloak introspection behind a TokenVerifier port" -m "ADR 0007: every hop asks Keycloak, so logged-out tokens fail at once. Anything Keycloak doesn't vouch for, including an outage, is unauthenticated."
```

---

### Task 3: API authentication, CORS, and `GET /me`

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/main.py`
- Create: `backend/src/smart_tutor/apps/api/deps.py`
- Create: `backend/src/smart_tutor/apps/api/routes/accounts.py`
- Test: `backend/tests/unit/apps/api/test_auth.py`, `backend/tests/isolation/test_me.py`

**Interfaces:**
- Consumes: `TokenVerifier`, `Principal`, `UnauthenticatedError`, `keycloak_verifier` (Task 2); `Settings.cors_origins` (Task 1); `FakeTokenVerifier` (tests).
- Produces:
  - `create_app(settings: Settings | None = None, verifier: TokenVerifier | None = None) -> FastAPI`; module-level `app = create_app()`.
  - `PUBLIC_PATHS: frozenset[str]` in `apps/api/main.py` = `{"/healthz", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}`.
  - `GET /me` → `MeResponse {user_id: str, name: str, roles: list[str]}` (roles sorted), `operation_id="get_me"`, tag `accounts`.
  - OpenAPI has an `HTTPBearer` security scheme on protected operations.

- [ ] **Step 1: Write the failing tests**

`backend/tests/unit/apps/api/test_auth.py`:

```python
import logging

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier
from smart_tutor.apps.api.main import PUBLIC_PATHS, create_app
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

ORIGIN = "http://localhost:5173"
TOKEN = "secret-token-value"
ADA = Principal(user_id=UserId("user-ada"), name="Ada Lovelace", roles=frozenset({"learner", "offline_access"}))


@pytest.fixture
def verifier() -> FakeTokenVerifier:
    v = FakeTokenVerifier()
    v.add(TOKEN, ADA)
    return v


@pytest.fixture
def client(verifier: FakeTokenVerifier) -> TestClient:
    return TestClient(create_app(Settings(cors_origins=[ORIGIN]), verifier=verifier))


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_me_returns_the_caller(client: TestClient) -> None:
    r = client.get("/me", headers=bearer(TOKEN))
    assert r.status_code == 200
    assert r.json() == {"user_id": "user-ada", "name": "Ada Lovelace", "roles": ["learner", "offline_access"]}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic dXNlcjpwdw=="}, {"Authorization": "Bearer "}, bearer("unknown")],
    ids=["missing", "basic", "empty-bearer", "unknown-token"],
)
def test_me_rejects_bad_credentials(client: TestClient, headers: dict[str, str]) -> None:
    r = client.get("/me", headers=headers)
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"


def test_a_revoked_token_is_rejected(client: TestClient, verifier: FakeTokenVerifier) -> None:
    assert client.get("/me", headers=bearer(TOKEN)).status_code == 200
    verifier.revoke(TOKEN)  # learner signed out
    assert client.get("/me", headers=bearer(TOKEN)).status_code == 401


def test_healthz_is_public(client: TestClient) -> None:
    assert client.get("/healthz").status_code == 200


def test_every_route_requires_a_token(client: TestClient) -> None:
    protected = [
        (route.path, method)
        for route in client.app.routes  # type: ignore[attr-defined]
        if isinstance(route, APIRoute) and route.path not in PUBLIC_PATHS
        for method in route.methods
    ]
    assert protected, "expected at least GET /me"
    for path, method in protected:
        r = client.request(method, path)
        assert r.status_code == 401, f"{method} {path} answered {r.status_code} without a token"


def test_401_carries_cors_headers(client: TestClient) -> None:
    r = client.get("/me", headers={"Origin": ORIGIN})
    assert r.status_code == 401
    assert r.headers["access-control-allow-origin"] == ORIGIN


def test_preflight_allows_the_authorization_header(client: TestClient) -> None:
    r = client.options(
        "/me",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"},
    )
    assert r.status_code == 200
    assert "authorization" in r.headers["access-control-allow-headers"].lower()


def test_other_origins_are_not_allowed(client: TestClient) -> None:
    r = client.get("/me", headers={"Origin": "http://evil.example", **bearer(TOKEN)})
    assert "access-control-allow-origin" not in r.headers


def test_tokens_never_reach_the_logs(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    client.get("/me", headers=bearer(TOKEN))
    client.get("/me", headers=bearer("another-secret-token"))
    assert "secret-token-value" not in caplog.text
    assert "another-secret-token" not in caplog.text


def test_openapi_declares_bearer_auth(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert schema["paths"]["/me"]["get"]["operationId"] == "get_me"
```

`backend/tests/isolation/test_me.py`:

```python
"""US-12: /me answers only for the caller; there is no way to ask about someone else."""

from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal


def test_each_learner_sees_only_themselves() -> None:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "Learner A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "Learner B", frozenset({"learner"})))
    client = TestClient(create_app(verifier=verifier))

    a = client.get("/me", headers={"Authorization": "Bearer token-a"}, params={"user_id": "learner-b"})
    b = client.get("/me", headers={"Authorization": "Bearer token-b"}, params={"user_id": "learner-a"})

    assert a.json()["user_id"] == "learner-a"
    assert b.json()["user_id"] == "learner-b"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/apps tests/isolation -v`
Expected: FAIL (`create_app` not importable).

- [ ] **Step 3: Implement**

`backend/src/smart_tutor/apps/api/deps.py`:

```python
"""Request dependencies: who is calling (PRD §9.3, ADR 0007)."""

import logging
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.shared.ports.token_verifier import TokenVerifier

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
    except UnauthenticatedError as e:
        logger.info("rejected request to %s: %s", request.url.path, e)  # the reason only, never the token
        raise _unauthorized() from None


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]
```

`backend/src/smart_tutor/apps/api/routes/accounts.py`:

```python
"""Learner profile routes (accounts module)."""

from fastapi import APIRouter
from pydantic import BaseModel

from smart_tutor.apps.api.deps import CurrentPrincipal

router = APIRouter(tags=["accounts"])


class MeResponse(BaseModel):
    user_id: str
    name: str
    roles: list[str]


@router.get("/me", operation_id="get_me")
async def get_me(principal: CurrentPrincipal) -> MeResponse:
    return MeResponse(user_id=principal.user_id, name=principal.name, roles=sorted(principal.roles))
```

`backend/src/smart_tutor/apps/api/main.py`:

```python
"""API server (FastAPI). Routes per module live in ``routes/``; request wiring in ``deps.py``."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from smart_tutor.apps.api.deps import current_principal
from smart_tutor.apps.api.routes import accounts
from smart_tutor.shared.adapters.auth.keycloak_introspection import keycloak_verifier
from smart_tutor.shared.config import Settings
from smart_tutor.shared.ports.token_verifier import TokenVerifier

# Everything else needs a token Keycloak says is active (tests/unit/apps/api/test_auth.py checks every route).
PUBLIC_PATHS = frozenset({"/healthz", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"})


def create_app(settings: Settings | None = None, verifier: TokenVerifier | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if verifier is not None:
            yield
            return
        async with httpx.AsyncClient(timeout=5) as http:
            app.state.verifier = keycloak_verifier(settings, http)
            yield

    app = FastAPI(title="Smart Tutor API", lifespan=lifespan)
    if verifier is not None:
        app.state.verifier = verifier
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    protected = APIRouter(dependencies=[Depends(current_principal)])
    protected.include_router(accounts.router)
    app.include_router(protected)
    return app


app = create_app()
```

Note: `/healthz` had no `include_in_schema=False` before; hiding it keeps the generated web client to real endpoints. If you prefer to keep it in the schema, drop the flag — the snapshot in Task 5 follows either way.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/unit/apps tests/isolation -v && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: PASS. If `test_preflight_allows_the_authorization_header` fails on header case, compare case-insensitively as written (Starlette echoes the requested headers).

- [ ] **Step 5: Commit**

```bash
git add backend/src/smart_tutor/apps/api backend/tests/unit/apps backend/tests/isolation/test_me.py
git commit -m "Require an active Keycloak token on every API route and add GET /me" -m "US-1: unauthenticated calls get 401. CORS wraps 401s too, so the web app can tell an expired session from a network error."
```

---

### Task 4: Alembic baseline and the migrate job

**Files:**
- Modify: `backend/pyproject.toml` (dependency `alembic>=1.16`; mypy exclude for migration versions), `backend/uv.lock`
- Create: `backend/alembic.ini`
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/env.py`, `script.py.mako`, `versions/0001_baseline.py`
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrate.py`
- Create: `backend/src/smart_tutor/apps/jobs/migrate.py`
- Modify: `compose.yaml` (`migrate` service; `api` waits for it), `Makefile` (`migrate`), `.github/workflows/ci.yml` (Postgres service + migrate step)
- Test: `backend/tests/integration/shared/test_migrations.py`

**Interfaces:**
- Consumes: `Settings.database_url`.
- Produces: `upgrade_to_head(database_url: str) -> None` in `smart_tutor.shared.adapters.postgres.migrate`; revision id `"0001"`; command `python -m smart_tutor.apps.jobs.migrate`.

- [ ] **Step 1: Write the failing integration test**

`backend/tests/integration/shared/test_migrations.py`:

```python
"""Against the Compose Postgres (`make up`)."""

import pytest
from sqlalchemy import create_engine, text

from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings

pytestmark = pytest.mark.integration


def test_upgrade_to_head_reaches_the_baseline_and_is_repeatable() -> None:
    url = Settings().database_url
    upgrade_to_head(url)
    upgrade_to_head(url)  # running twice is a no-op
    with create_engine(url).connect() as conn:
        assert conn.execute(text("select version_num from alembic_version")).scalar_one() == "0001"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && uv run pytest -m integration tests/integration/shared/test_migrations.py -v`
Expected: FAIL (`ModuleNotFoundError` for `migrate`).

- [ ] **Step 3: Implement**

`cd backend && uv add "alembic>=1.16"` (updates `pyproject.toml` and `uv.lock`).

Add to `[tool.mypy]` in `pyproject.toml`:

```toml
exclude = ["shared/adapters/postgres/migrations/versions/"]
```

`backend/alembic.ini` (for `uv run alembic revision -m "..."` during development):

```ini
# Migrations live in the package so every image can run them: python -m smart_tutor.apps.jobs.migrate
# The database URL comes from Settings (SMART_TUTOR_DATABASE_URL), not from this file.
[alembic]
script_location = %(here)s/src/smart_tutor/shared/adapters/postgres/migrations
prepend_sys_path = src

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARNING
handlers = console

[logger_sqlalchemy]
level = WARNING
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

`backend/src/smart_tutor/shared/adapters/postgres/migrations/env.py`:

```python
"""Alembic environment. Tables arrive with the slices that need them (US-2 onward), using PRD §9.4 names."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from smart_tutor.shared.config import Settings

config = context.config
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", Settings().database_url)

target_metadata = None


def run_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()
```

`backend/src/smart_tutor/shared/adapters/postgres/migrations/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

`backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0001_baseline.py`:

```python
"""Baseline: an empty schema under Alembic's control.

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
```

`backend/src/smart_tutor/shared/adapters/postgres/migrate.py`:

```python
"""Run Alembic migrations from inside the package (no alembic.ini needed in images)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).parent / "migrations"


def upgrade_to_head(database_url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
```

`backend/src/smart_tutor/apps/jobs/migrate.py`:

```python
"""Bring the database schema to the latest revision. Runs before the API starts (Compose `migrate`, a Helm hook later)."""

from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings


def main() -> None:
    upgrade_to_head(Settings().database_url)


if __name__ == "__main__":
    main()
```

`compose.yaml` — add under the app profile (before `api`), and make `api` wait for it:

```yaml
  migrate:
    profiles: [app]
    build: {context: ./backend, target: api}
    command: ["python", "-m", "smart_tutor.apps.jobs.migrate"]
    environment:
      SMART_TUTOR_DATABASE_URL: postgresql+psycopg://smart_tutor:smart_tutor@postgres:5432/smart_tutor
    depends_on:
      postgres: {condition: service_healthy}
```

and replace `api.depends_on` with:

```yaml
    depends_on:
      migrate: {condition: service_completed_successfully}
      keycloak: {condition: service_started}
      agent: {condition: service_started}
```

`Makefile` — add `migrate` to the first `.PHONY` line and, after `sync:`:

```make
migrate:       ## bring the local database to the latest Alembic revision (needs `make up`)
	$(BACKEND) uv run python -m smart_tutor.apps.jobs.migrate
```

`.github/workflows/ci.yml` — in the `backend` job, add before `steps:`:

```yaml
    services:
      postgres:
        image: pgvector/pgvector:pg17
        env:
          POSTGRES_USER: smart_tutor
          POSTGRES_PASSWORD: smart_tutor
          POSTGRES_DB: smart_tutor
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U smart_tutor -d smart_tutor" --health-interval 5s --health-retries 20
```

and after the `Unit tests` step:

```yaml
      - name: Migrations apply
        run: uv run python -m smart_tutor.apps.jobs.migrate
        env:
          SMART_TUTOR_DATABASE_URL: postgresql+psycopg://smart_tutor:smart_tutor@localhost:5432/smart_tutor
```

- [ ] **Step 4: Verify**

Run: `cd backend && uv run pytest -m integration tests/integration/shared/test_migrations.py -v` (Compose `make up`)
Expected: PASS.
Run: `cd backend && uv build --wheel -o /tmp/st-wheel && python -c "import zipfile,glob; n=zipfile.ZipFile(glob.glob('/tmp/st-wheel/*.whl')[0]).namelist(); assert any(p.endswith('migrations/env.py') for p in n) and any(p.endswith('0001_baseline.py') for p in n), 'migrations missing from wheel'; print('ok')"`
Expected: `ok` (the images install the wheel, so the migrations must ship in it). Use `$CLAUDE_JOB_DIR/tmp` or another scratch dir instead of `/tmp` if needed.
Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/alembic.ini backend/src/smart_tutor/shared/adapters/postgres backend/src/smart_tutor/apps/jobs/migrate.py backend/tests/integration/shared/test_migrations.py compose.yaml Makefile .github/workflows/ci.yml
git commit -m "Put the database under Alembic with an empty baseline" -m "The walking skeleton (#31) uses Alembic from day one. Migrations ship inside the package so any image can run them; CI applies them to a real Postgres."
```

---

### Task 5: OpenAPI snapshot and the generated web client

**Files:**
- Create: `backend/src/smart_tutor/apps/api/openapi_export.py`
- Test: `backend/tests/unit/apps/api/test_openapi_snapshot.py`
- Create: `web/src/api/openapi.json` (generated), `web/src/api/generated/**` (generated), `web/openapi-ts.config.ts`
- Delete: `web/src/api/.gitkeep`
- Modify: `web/package.json` (devDependency `@hey-api/openapi-ts`, script `api:generate`), `web/package-lock.json`, `Makefile` (`api-client`), `.github/workflows/ci.yml` (web job: generated client is current)

**Interfaces:**
- Consumes: `create_app` (Task 3).
- Produces: `python -m smart_tutor.apps.api.openapi_export <path>`; `make api-client`; generated `getMe()` SDK function and `client` instance under `web/src/api/generated/` (`sdk.gen.ts`, `client.gen.ts`, `types.gen.ts` with type `MeResponse`), plus `createClient`/`createConfig` from `web/src/api/generated/client`. **Check the exact export names after generating** and use them in Tasks 6–7; the plan assumes `getMe`, `client`, `createClient`, `createConfig`, `MeResponse`.

- [ ] **Step 1: Write the failing snapshot test**

`backend/tests/unit/apps/api/test_openapi_snapshot.py`:

```python
"""The web client is generated from web/src/api/openapi.json; it must match the API. Fix: make api-client."""

import json
from pathlib import Path

from smart_tutor.apps.api.openapi_export import openapi_json

SNAPSHOT = Path(__file__).parents[5] / "web" / "src" / "api" / "openapi.json"


def test_web_openapi_snapshot_is_current() -> None:
    assert SNAPSHOT.exists(), "run `make api-client`"
    assert json.loads(SNAPSHOT.read_text(encoding="utf-8")) == json.loads(openapi_json()), "run `make api-client`"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd backend && uv run pytest tests/unit/apps/api/test_openapi_snapshot.py -v`
Expected: FAIL (`ModuleNotFoundError: ...openapi_export`).

- [ ] **Step 3: Implement the export**

`backend/src/smart_tutor/apps/api/openapi_export.py`:

```python
"""Write the API's OpenAPI schema for the web client generator: python -m smart_tutor.apps.api.openapi_export <path>."""

import json
import sys
from pathlib import Path

from smart_tutor.apps.api.main import create_app


def openapi_json() -> str:
    return json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    Path(sys.argv[1]).write_text(openapi_json(), encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Set up the generator**

```bash
cd web && npm install --save-dev --save-exact @hey-api/openapi-ts@0.99.0
```

`web/openapi-ts.config.ts`:

```ts
import { defineConfig } from "@hey-api/openapi-ts";

// Generated from the API's schema; regenerate with `make api-client`. Never edit src/api/generated by hand.
export default defineConfig({
  input: "src/api/openapi.json",
  output: "src/api/generated",
  plugins: ["@hey-api/client-fetch"],
});
```

In `web/package.json` scripts add `"api:generate": "openapi-ts"`.

`Makefile` — add `api-client` to the first `.PHONY` line and:

```make
api-client:    ## regenerate web/src/api from the API's OpenAPI schema
	$(BACKEND) uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm run api:generate
```

Run: `rm web/src/api/.gitkeep && make api-client` (or the two commands directly).
Expected: `web/src/api/openapi.json` and `web/src/api/generated/` exist; `grep -n "getMe" web/src/api/generated/sdk.gen.ts` finds the function. Record the actual export names.

`.github/workflows/ci.yml`, `web` job, after `npm ci`:

```yaml
      - name: Generated API client is current
        run: npm run api:generate && git diff --exit-code -- src/api
```

- [ ] **Step 5: Verify**

Run: `cd backend && uv run pytest tests/unit/apps/api/test_openapi_snapshot.py -v` → PASS.
Run: `cd web && npm run build && npm test` → PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/src/smart_tutor/apps/api/openapi_export.py backend/tests/unit/apps/api/test_openapi_snapshot.py web/openapi-ts.config.ts web/package.json web/package-lock.json web/src/api Makefile .github/workflows/ci.yml
git commit -m "Generate the web API client from the API's OpenAPI schema" -m "Web code calls the API only through src/api (structure spec §9). A backend test and a CI step keep the snapshot and the generated code current. @hey-api/openapi-ts because openapi-typescript requires TypeScript 5."
```

---

### Task 6: Keycloak sign-in and the API client's token handling (web)

**Files:**
- Modify: `web/package.json`, `web/package-lock.json` (dependency `keycloak-js`)
- Create: `web/src/vite-env.d.ts`
- Create: `web/src/auth/authClient.ts`
- Create: `web/src/auth/keycloakClient.ts`, `web/src/auth/keycloakClient.test.ts`
- Create: `web/src/api/client.ts`, `web/src/api/client.test.ts`
- Delete: `web/src/auth/.gitkeep`

**Interfaces:**
- Consumes: generated `client`, `createClient`, `createConfig`, `getMe` (Task 5).
- Produces:
  - `type AuthClient = { init(): Promise<void>; getToken(): Promise<string>; signIn(): Promise<void>; signOut(): Promise<void> }`
  - `class SessionExpiredError extends Error`
  - `sessionExpiry: { notify(): void; subscribe(listener: () => void): () => void }`
  - `createKeycloakClient(config?: AuthConfig): AuthClient`; `authConfig(): AuthConfig` where `AuthConfig = { url: string; realm: string; clientId: string }`
  - `configureApiClient(options: { baseUrl: string; getToken: () => Promise<string>; onUnauthorized: () => void; apiClient?: Client }): void`; `apiBaseUrl(): string`

- [ ] **Step 1: Install and declare env**

```bash
cd web && npm install keycloak-js@^26.2.4 && rm src/auth/.gitkeep
```

`web/src/vite-env.d.ts`:

```ts
/// <reference types="vite/client" />

// Defaults match Docker Compose (AGENTS.md → Local development); set these at build time elsewhere.
interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_KEYCLOAK_URL?: string;
  readonly VITE_KEYCLOAK_REALM?: string;
  readonly VITE_KEYCLOAK_CLIENT_ID?: string;
}
```

- [ ] **Step 2: Write the failing tests**

`web/src/auth/keycloakClient.test.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from "vitest";

const kc = {
  init: vi.fn(),
  updateToken: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  token: undefined as string | undefined,
};
vi.mock("keycloak-js", () => ({ default: vi.fn(() => kc) }));

const { createKeycloakClient } = await import("./keycloakClient");
const config = { url: "http://localhost:8080", realm: "smart-tutor", clientId: "smart-tutor-web" };

describe("keycloak client", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    kc.init.mockResolvedValue(true);
    kc.updateToken.mockResolvedValue(false);
    kc.token = "access-token";
  });

  it("signs in with PKCE and login-required", async () => {
    await createKeycloakClient(config).init();
    expect(kc.init).toHaveBeenCalledWith({ onLoad: "login-required", pkceMethod: "S256", checkLoginIframe: false });
  });

  it("init runs keycloak once", async () => {
    const auth = createKeycloakClient(config);
    await Promise.all([auth.init(), auth.init()]); // StrictMode mounts effects twice
    await auth.init();
    expect(kc.init).toHaveBeenCalledOnce();
  });

  it("refreshes a token that expires within 60 seconds before handing it out", async () => {
    await expect(createKeycloakClient(config).getToken()).resolves.toBe("access-token");
    expect(kc.updateToken).toHaveBeenCalledWith(60);
  });

  it("fails getToken when the refresh fails", async () => {
    kc.updateToken.mockRejectedValue(new Error("refresh token expired"));
    await expect(createKeycloakClient(config).getToken()).rejects.toThrow();
  });

  it("signs out back to the app", async () => {
    await createKeycloakClient(config).signOut();
    expect(kc.logout).toHaveBeenCalledWith({ redirectUri: `${window.location.origin}/` });
  });
});
```

`web/src/api/client.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import { configureApiClient } from "./client";
import { createClient, createConfig } from "./generated/client";
import { getMe } from "./generated/sdk.gen";

function setup(status: number, getToken: () => Promise<string> = async () => "access-token") {
  const fetch = vi.fn(async (_req: Request) =>
    new Response(JSON.stringify({ user_id: "u1", name: "Ada Lovelace", roles: ["learner"] }), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
  const apiClient = createClient(createConfig({ fetch }));
  const onUnauthorized = vi.fn();
  configureApiClient({ baseUrl: "http://api.test", getToken, onUnauthorized, apiClient });
  return { apiClient, fetch, onUnauthorized };
}

describe("API client", () => {
  it("sends a fresh bearer token", async () => {
    const { apiClient, fetch } = setup(200);
    const { data } = await getMe({ client: apiClient });
    expect(data?.name).toBe("Ada Lovelace");
    const request = fetch.mock.calls[0]![0];
    expect(request.url).toBe("http://api.test/me");
    expect(request.headers.get("Authorization")).toBe("Bearer access-token");
  });

  it("reports a 401", async () => {
    const { apiClient, onUnauthorized } = setup(401);
    await getMe({ client: apiClient });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("getToken failure notifies and sends nothing", async () => {
    const { apiClient, fetch, onUnauthorized } = setup(200, () => Promise.reject(new Error("refresh failed")));
    await expect(getMe({ client: apiClient, throwOnError: true })).rejects.toThrow();
    expect(onUnauthorized).toHaveBeenCalledOnce();
    expect(fetch).not.toHaveBeenCalled();
  });
});
```

(Adjust import paths and the `fetch` mock signature to what Task 5 generated, e.g. if the client calls `fetch(request)` vs `fetch(url, init)`; the assertions stay the same.)

- [ ] **Step 3: Run to verify they fail**

Run: `cd web && npx vitest run src/auth src/api`
Expected: FAIL (modules missing).

- [ ] **Step 4: Implement**

`web/src/auth/authClient.ts`:

```ts
// The sign-in boundary the app depends on; keycloakClient.ts implements it, tests fake it.
export type AuthClient = {
  /** Resolves once the learner is signed in (redirects to Keycloak first if needed). */
  init(): Promise<void>;
  /** A token valid for at least 60 more seconds; rejects when the session can't be refreshed. */
  getToken(): Promise<string>;
  signIn(): Promise<void>;
  signOut(): Promise<void>;
};

export class SessionExpiredError extends Error {
  constructor() {
    super("Session expired");
    this.name = "SessionExpiredError";
  }
}

const listeners = new Set<() => void>();

/** The API client reports an ended session here; SessionProvider listens. */
export const sessionExpiry = {
  notify() {
    for (const listener of listeners) listener();
  },
  subscribe(listener: () => void) {
    listeners.add(listener);
    return () => {
      listeners.delete(listener);
    };
  },
};
```

`web/src/auth/keycloakClient.ts`:

```ts
import Keycloak from "keycloak-js";

import type { AuthClient } from "./authClient";

export type AuthConfig = { url: string; realm: string; clientId: string };

export function authConfig(): AuthConfig {
  return {
    url: import.meta.env.VITE_KEYCLOAK_URL ?? "http://localhost:8080",
    realm: import.meta.env.VITE_KEYCLOAK_REALM ?? "smart-tutor",
    clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "smart-tutor-web",
  };
}

// Authorization Code + PKCE on the public smart-tutor-web client (PRD §9.3).
export function createKeycloakClient(config: AuthConfig = authConfig()): AuthClient {
  const keycloak = new Keycloak(config);
  let initialized: Promise<void> | undefined; // keycloak-js throws if init runs twice (StrictMode)

  return {
    init() {
      initialized ??= keycloak
        .init({ onLoad: "login-required", pkceMethod: "S256", checkLoginIframe: false })
        .then(() => undefined);
      return initialized;
    },
    async getToken() {
      await keycloak.updateToken(60);
      if (!keycloak.token) throw new Error("Not signed in");
      return keycloak.token;
    },
    signIn: () => keycloak.login(),
    signOut: () => keycloak.logout({ redirectUri: `${window.location.origin}/` }),
  };
}
```

`web/src/api/client.ts`:

```ts
import { client, type Client } from "./generated/client";

export function apiBaseUrl(): string {
  return import.meta.env.VITE_API_URL ?? "http://localhost:8001";
}

type Options = {
  baseUrl: string;
  /** Refreshes first (updateToken(60)); rejects when the session is over. */
  getToken: () => Promise<string>;
  /** Called on a 401 or a failed refresh: the app shows "Please sign in again". */
  onUnauthorized: () => void;
  apiClient?: Client;
};

export function configureApiClient({ baseUrl, getToken, onUnauthorized, apiClient = client }: Options): void {
  apiClient.setConfig({ baseUrl });
  apiClient.interceptors.request.use(async (request) => {
    let token: string;
    try {
      token = await getToken();
    } catch (e) {
      onUnauthorized();
      throw e;
    }
    request.headers.set("Authorization", `Bearer ${token}`);
    return request;
  });
  apiClient.interceptors.response.use((response) => {
    if (response.status === 401) onUnauthorized();
    return response;
  });
}
```

(If the generated `client` and `Client` are exported from `./generated/client.gen` rather than `./generated/client`, import them from there.)

- [ ] **Step 5: Run to verify they pass**

Run: `cd web && npx vitest run src/auth src/api && npm run build`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add web/package.json web/package-lock.json web/src/vite-env.d.ts web/src/auth web/src/api/client.ts web/src/api/client.test.ts
git commit -m "Sign in with keycloak-js and attach a fresh token to every API call" -m "ADR 0007 open item, decided in #31: refresh with updateToken(60) before each call so a token can't expire mid-request; a 401 or failed refresh ends the session."
```

---

### Task 7: Session in the app shell: name, Sign out, "Please sign in again"

**Files:**
- Create: `web/src/api/me.ts`
- Create: `web/src/auth/SessionProvider.tsx`, `web/src/auth/SessionProvider.module.css`, `web/src/auth/SessionProvider.test.tsx`
- Modify: `web/src/components/SideNav/SideNav.tsx`
- Modify: `web/src/app/routes.test.tsx` (wrap in a session; new test for the name and Sign out)
- Modify: `web/src/main.tsx`, `web/src/App.tsx` (comment only if needed)

**Interfaces:**
- Consumes: `AuthClient`, `SessionExpiredError`, `sessionExpiry`, `createKeycloakClient` (Task 6); `configureApiClient`, `apiBaseUrl` (Task 6); generated `getMe`, `MeResponse` (Task 5); `Button` (`variant`, `size`), `EmptyState`/tokens from the shell.
- Produces:
  - `loadMe(): Promise<MeResponse>` — throws `SessionExpiredError` on 401, `Error` otherwise.
  - `SessionProvider({ auth, loadMe, children })`; `SessionContext`; `useSession(): { name: string; signOut: () => void }`.

- [ ] **Step 1: Write the failing tests**

`web/src/auth/SessionProvider.test.tsx`:

```tsx
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { type AuthClient, SessionExpiredError, sessionExpiry } from "./authClient";
import { SessionProvider, useSession } from "./SessionProvider";

function fakeAuth(): AuthClient {
  return {
    init: vi.fn(async () => {}),
    getToken: vi.fn(async () => "t"),
    signIn: vi.fn(async () => {}),
    signOut: vi.fn(async () => {}),
  };
}

function Who() {
  const { name, signOut } = useSession();
  return (
    <button type="button" onClick={signOut}>
      {name}
    </button>
  );
}

function renderSession(auth: AuthClient, loadMe: () => Promise<{ name: string }>) {
  render(
    <SessionProvider auth={auth} loadMe={loadMe}>
      <Who />
    </SessionProvider>,
  );
}

describe("SessionProvider", () => {
  it("signs in, loads the learner, and shows the app", async () => {
    const auth = fakeAuth();
    renderSession(auth, async () => ({ name: "Ada Lovelace" }));
    expect(screen.getByRole("status")).toHaveTextContent("Signing you in");
    expect(await screen.findByRole("button", { name: "Ada Lovelace" })).toBeInTheDocument();
    expect(auth.init).toHaveBeenCalled();
  });

  it("signs out through the auth client", async () => {
    const auth = fakeAuth();
    renderSession(auth, async () => ({ name: "Ada Lovelace" }));
    await userEvent.click(await screen.findByRole("button", { name: "Ada Lovelace" }));
    expect(auth.signOut).toHaveBeenCalledOnce();
  });

  it("asks to sign in again when the API says 401", async () => {
    const auth = fakeAuth();
    renderSession(auth, () => Promise.reject(new SessionExpiredError()));
    expect(await screen.findByRole("heading", { name: "Please sign in again" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(auth.signIn).toHaveBeenCalledOnce();
  });

  it("asks to sign in again when a later call ends the session", async () => {
    renderSession(fakeAuth(), async () => ({ name: "Ada Lovelace" }));
    await screen.findByRole("button", { name: "Ada Lovelace" });
    act(() => sessionExpiry.notify());
    expect(screen.getByRole("heading", { name: "Please sign in again" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Ada Lovelace" })).not.toBeInTheDocument();
  });

  it("offers a retry when the API can't be reached", async () => {
    const loadMe = vi.fn().mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValue({ name: "Ada Lovelace" });
    renderSession(fakeAuth(), loadMe);
    expect(await screen.findByRole("heading", { name: "Can't reach Smart Tutor" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByRole("button", { name: "Ada Lovelace" })).toBeInTheDocument();
  });
});
```

In `web/src/app/routes.test.tsx`, wrap the router in a session and add a test. Change imports and `renderAt`:

```tsx
import { vi } from "vitest"; // merge into the existing vitest import
import { SessionContext } from "../auth/SessionProvider";

const signOut = vi.fn();

function renderAt(path: string, { strict = false } = {}) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const app = (
    <SessionContext.Provider value={{ name: "Ada Lovelace", signOut }}>
      <RouterProvider router={router} />
    </SessionContext.Provider>
  );
  render(strict ? <StrictMode>{app}</StrictMode> : app);
  return router;
}
```

and add inside the `describe`:

```tsx
  it("shows the learner's name and signs out from the user menu", async () => {
    renderAt("/library");
    await userEvent.click(nav().getByRole("button", { name: /Ada Lovelace/ }));
    await userEvent.click(nav().getByRole("button", { name: "Sign out" }));
    expect(signOut).toHaveBeenCalledOnce();
  });
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd web && npx vitest run src/auth/SessionProvider.test.tsx src/app/routes.test.tsx`
Expected: FAIL (module `./SessionProvider` missing).

- [ ] **Step 3: Implement**

`web/src/api/me.ts`:

```ts
import { SessionExpiredError } from "../auth/authClient";
import { getMe } from "./generated/sdk.gen";
import type { MeResponse } from "./generated/types.gen";

export async function loadMe(): Promise<MeResponse> {
  const { data, response } = await getMe();
  if (response?.status === 401) throw new SessionExpiredError();
  if (!data) throw new Error(`GET /me failed (${response?.status ?? "no response"})`);
  return data;
}
```

`web/src/auth/SessionProvider.tsx`:

```tsx
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { Button } from "../components/Button/Button";
import { type AuthClient, SessionExpiredError, sessionExpiry } from "./authClient";
import styles from "./SessionProvider.module.css";

export type Session = { name: string; signOut: () => void };

export const SessionContext = createContext<Session | null>(null);

export function useSession(): Session {
  const session = useContext(SessionContext);
  if (!session) throw new Error("useSession needs a SessionProvider");
  return session;
}

type Status = { kind: "loading" } | { kind: "ready"; name: string } | { kind: "expired" } | { kind: "error" };

type Props = { auth: AuthClient; loadMe: () => Promise<{ name: string }>; children: ReactNode };

// Signs the learner in (Keycloak), loads /me, and renders the app only for a live session (US-1).
export function SessionProvider({ auth, loadMe, children }: Props) {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  const load = useCallback(async () => {
    setStatus({ kind: "loading" });
    try {
      await auth.init();
      const me = await loadMe();
      setStatus({ kind: "ready", name: me.name });
    } catch (e) {
      setStatus(e instanceof SessionExpiredError ? { kind: "expired" } : { kind: "error" });
    }
  }, [auth, loadMe]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => sessionExpiry.subscribe(() => setStatus({ kind: "expired" })), []);

  if (status.kind === "ready") {
    const session = { name: status.name, signOut: () => void auth.signOut() };
    return <SessionContext.Provider value={session}>{children}</SessionContext.Provider>;
  }

  return (
    <main className={styles.screen}>
      {status.kind === "loading" && (
        <p role="status" className={styles.note}>
          Signing you in…
        </p>
      )}
      {status.kind === "expired" && (
        <div className={styles.card}>
          <h1 className={styles.title}>Please sign in again</h1>
          <p className={styles.note}>Your session has ended.</p>
          <Button variant="primary" onClick={() => void auth.signIn()}>
            Sign in
          </Button>
        </div>
      )}
      {status.kind === "error" && (
        <div className={styles.card}>
          <h1 className={styles.title}>Can't reach Smart Tutor</h1>
          <p className={styles.note}>Check your connection and try again.</p>
          <Button variant="secondary" onClick={() => void load()}>
            Try again
          </Button>
        </div>
      )}
    </main>
  );
}
```

`web/src/auth/SessionProvider.module.css` (tokens only — read `web/src/styles/tokens.css` and `DESIGN.md` and pick the matching token names; the names below are the roles to use):

```css
.screen {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: var(--space-6);
  background: var(--bg);
}

.card {
  display: grid;
  gap: var(--space-3);
  justify-items: start;
  max-width: 28rem;
  padding: var(--space-6);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

.title {
  margin: 0;
  font-family: var(--font-display);
  font-size: var(--text-xl);
}

.note {
  margin: 0;
  color: var(--text-muted);
}
```

(Replace each `var(--…)` with the real token of that role from `tokens.css`; don't introduce raw colors or sizes.)

`web/src/components/SideNav/SideNav.tsx` — import `useSession` and replace the placeholder:

```tsx
import { useSession } from "../../auth/SessionProvider";
```

```tsx
export function SideNav() {
  const { name, signOut } = useSession();
  return (
    <nav className={styles.sidenav} aria-label="Main">
      {/* …brand and list unchanged… */}
      <UserMenu name={name} onSignOut={signOut} />
    </nav>
  );
}
```

(Remove the `{/* US-1 replaces the placeholder name and wires Sign out. */}` comment.)

`web/src/main.tsx`:

```tsx
import "./styles/tokens.css";
import "./styles/base.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { apiBaseUrl, configureApiClient } from "./api/client";
import { loadMe } from "./api/me";
import { sessionExpiry } from "./auth/authClient";
import { createKeycloakClient } from "./auth/keycloakClient";
import { SessionProvider } from "./auth/SessionProvider";
import { followColorScheme } from "./styles/theme";

followColorScheme(document.documentElement, window.matchMedia("(prefers-color-scheme: dark)"));

const auth = createKeycloakClient();
configureApiClient({ baseUrl: apiBaseUrl(), getToken: () => auth.getToken(), onUnauthorized: sessionExpiry.notify });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <SessionProvider auth={auth} loadMe={loadMe}>
      <App />
    </SessionProvider>
  </StrictMode>,
);
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd web && npm test && npm run build`
Expected: all PASS (existing shell tests included).

- [ ] **Step 5: Commit**

```bash
git add web/src/api/me.ts web/src/auth/SessionProvider.tsx web/src/auth/SessionProvider.module.css web/src/auth/SessionProvider.test.tsx web/src/components/SideNav/SideNav.tsx web/src/app/routes.test.tsx web/src/main.tsx
git commit -m "Show the signed-in learner in the shell and handle ended sessions" -m "US-1: the app opens only for a signed-in learner, shows their name from GET /me, signs out through Keycloak, and asks to sign in again on a 401."
```

---

### Task 8: Docs and the Compose check

**Files:**
- Modify: `backend/README.md` (section "Check sign-in against Compose")
- Modify: `AGENTS.md` (Local development: realm re-import, `make migrate`, `make api-client`)
- Modify: `web/README.md` (env vars `VITE_API_URL`, `VITE_KEYCLOAK_*`)
- Modify: `sdd/specs/2026-10-02-project-structure-design.md` (`apps/jobs/migrate.py`; `shared/adapters/postgres/migrations/`)

- [ ] **Step 1: Write the docs**

Append to `backend/README.md`:

```markdown
## Check sign-in against Compose

The unit tests fake Keycloak; this is the end-to-end check for US-1 (#45).

1. `docker compose down -v && docker compose --profile app up -d --build` (re-imports the realm, runs `migrate`).
2. Open http://localhost:5173, sign in as `learner@example.com` / `learner`: the Library shows "Upload your first document" and the user menu shows "Local Learner".
3. In the browser's dev tools, copy the `Authorization` header of the `GET /me` request, then:
   `curl -i http://localhost:8001/me -H "Authorization: Bearer <token>"` → `200`.
4. Sign out from the user menu, then repeat the `curl` → `401` (the token is revoked although not expired).
5. `curl -i http://localhost:8001/me` → `401` with `WWW-Authenticate: Bearer`.
```

In `AGENTS.md` → Local development, add one bullet:

```markdown
- `make migrate` applies Alembic migrations to the Compose database (the app profile runs it before the API). After changing an API route, run `make api-client` to regenerate `web/src/api/`; CI fails when it is stale.
```

In `web/README.md`, add:

```markdown
## Configuration

Build-time variables, defaulting to Docker Compose: `VITE_API_URL` (`http://localhost:8001`), `VITE_KEYCLOAK_URL` (`http://localhost:8080`), `VITE_KEYCLOAK_REALM` (`smart-tutor`), `VITE_KEYCLOAK_CLIENT_ID` (`smart-tutor-web`).
```

In the structure spec §4 tree, change the `jobs/` line to `# migrate.py, record_sweeper.py, glacier_tagger.py, retention.py, (R3) learner_reports.py` and the postgres line to `# engine, session, unit of work; migrations/ (Alembic)`.

- [ ] **Step 2: Run every check**

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest
cd web && npm ci && npm test && npm run build
```

Expected: all PASS.

- [ ] **Step 3: Run the Compose check**

Follow the backend README steps 1–5. Expected results as written there. If Docker or a browser isn't available, report which steps weren't run.

- [ ] **Step 4: Commit**

```bash
git add backend/README.md AGENTS.md web/README.md sdd/specs/2026-10-02-project-structure-design.md
git commit -m "Document the sign-in check, migrations, and client generation" -m "So the next slice can verify US-1 end to end and keep the generated client current."
```

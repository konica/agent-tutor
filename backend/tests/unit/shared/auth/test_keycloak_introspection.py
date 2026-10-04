import base64
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from smart_tutor.shared.adapters.auth.keycloak_introspection import KeycloakIntrospectionVerifier
from smart_tutor.shared.domain.errors import IntrospectionUnavailableError, UnauthenticatedError

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
    with pytest.raises(UnauthenticatedError) as excinfo:
        await verifier(returning(claims)).verify(TOKEN)
    assert type(excinfo.value) is UnauthenticatedError  # a bad token, not an outage


async def test_rejects_when_keycloak_returns_500() -> None:
    with pytest.raises(IntrospectionUnavailableError):
        await verifier(lambda _req: httpx.Response(500)).verify(TOKEN)


async def test_rejects_when_keycloak_returns_non_json() -> None:
    with pytest.raises(IntrospectionUnavailableError):
        await verifier(lambda _req: httpx.Response(200, text="<html>")).verify(TOKEN)


async def test_rejects_when_keycloak_unreachable() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=req)

    with pytest.raises(IntrospectionUnavailableError):
        await verifier(handler).verify(TOKEN)


async def test_rejects_when_the_client_credentials_are_refused() -> None:
    with pytest.raises(IntrospectionUnavailableError):
        await verifier(lambda _req: httpx.Response(401, json={"error": "unauthorized_client"})).verify(TOKEN)


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
        (
            {**{k: v for k, v in active().items() if k != "name"}, "given_name": "Ada", "family_name": "L"},
            "Ada L",
        ),
        (
            {**{k: v for k, v in active().items() if k != "name"}, "preferred_username": "ada@example.com"},
            "ada@example.com",
        ),
        ({k: v for k, v in active().items() if k != "name"}, "Learner"),
    ],
    ids=["name", "given-family", "username", "fallback"],
)
async def test_display_name(claims: dict[str, Any], name: str) -> None:
    assert (await verifier(returning(claims)).verify(TOKEN)).name == name


async def test_missing_roles_mean_no_roles() -> None:
    claims = {k: v for k, v in active().items() if k != "realm_access"}
    assert (await verifier(returning(claims)).verify(TOKEN)).roles == frozenset()


async def test_malformed_aud_as_int_is_rejected() -> None:
    with pytest.raises(UnauthenticatedError, match="another audience"):
        await verifier(returning(active(aud=123))).verify(TOKEN)


async def test_malformed_aud_as_none_is_rejected() -> None:
    with pytest.raises(UnauthenticatedError, match="another audience"):
        await verifier(returning(active(aud=None))).verify(TOKEN)


async def test_aud_list_with_non_string_entry_plus_valid_entry_is_accepted() -> None:
    principal = await verifier(returning(active(aud=[123, "smart-tutor-api", None]))).verify(TOKEN)
    assert principal.user_id == "user-1"


async def test_realm_access_as_list_means_no_roles() -> None:
    claims = active(realm_access=[])
    assert (await verifier(returning(claims)).verify(TOKEN)).roles == frozenset()


async def test_realm_access_as_none_means_no_roles() -> None:
    claims = active(realm_access=None)
    assert (await verifier(returning(claims)).verify(TOKEN)).roles == frozenset()


async def test_roles_as_string_means_no_roles() -> None:
    claims = active(realm_access={"roles": "learner"})
    assert (await verifier(returning(claims)).verify(TOKEN)).roles == frozenset()


async def test_roles_list_with_non_string_entry_keeps_only_strings() -> None:
    principal = await verifier(returning(active(realm_access={"roles": [123, "learner", None, "admin"]}))).verify(TOKEN)
    assert principal.roles == frozenset({"learner", "admin"})


async def test_given_name_as_int_falls_back_cleanly() -> None:
    claims = {k: v for k, v in active().items() if k != "name"}
    claims["given_name"] = 123
    claims["family_name"] = "Smith"
    assert (await verifier(returning(claims)).verify(TOKEN)).name == "Smith"


async def test_display_name_all_fields_non_string() -> None:
    claims = {k: v for k, v in active().items() if k not in ("name", "given_name", "family_name", "preferred_username")}
    claims["name"] = 123
    claims["given_name"] = []
    claims["family_name"] = {}
    claims["preferred_username"] = True
    assert (await verifier(returning(claims)).verify(TOKEN)).name == "Learner"

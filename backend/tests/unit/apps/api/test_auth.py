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
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
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

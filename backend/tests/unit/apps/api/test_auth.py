import logging

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier
from smart_tutor.apps.api.main import PUBLIC_PATHS, create_app
from smart_tutor.apps.api.routes import accounts
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import IntrospectionUnavailableError
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.shared.ports.token_verifier import TokenVerifier

ORIGIN = "http://localhost:10453"
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
    # Collect all protected routes by walking the route tree
    # (include_router wraps routes in _IncludedRouter with effective_candidates)
    protected = []
    app = client.app  # type: ignore[attr-defined]
    for route in app.routes:
        if isinstance(route, APIRoute) and route.path not in PUBLIC_PATHS:
            for method in route.methods:
                protected.append((route.path, method))
        elif hasattr(route, "effective_candidates"):
            # _IncludedRouter: walk its effective routes
            for candidate in route.effective_candidates():
                path = candidate.path
                if path not in PUBLIC_PATHS:
                    for method in candidate.methods:
                        protected.append((path, method))

    assert protected, "expected at least GET /me"
    assert ("/me", "GET") in protected, "GET /me should be in protected routes"
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


class BrokenVerifier(TokenVerifier):
    async def verify(self, token: str) -> Principal:
        raise IntrospectionUnavailableError("introspection failed: ConnectError")


def test_an_unavailable_token_check_is_a_401_and_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    r = TestClient(create_app(Settings(), verifier=BrokenVerifier())).get("/me", headers=bearer(TOKEN))
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"] == "Bearer"
    warnings = [rec for rec in caplog.records if rec.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "introspection failed" in warnings[0].getMessage()
    assert TOKEN not in caplog.text


def test_startup_fails_without_a_client_secret() -> None:
    with (
        pytest.raises(RuntimeError, match="SMART_TUTOR_KEYCLOAK_CLIENT_SECRET"),
        TestClient(create_app(Settings(keycloak_client_secret=""))),
    ):
        pass


def test_openapi_declares_bearer_auth(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert schema["components"]["securitySchemes"]["HTTPBearer"]["scheme"] == "bearer"
    assert schema["paths"]["/me"]["get"]["operationId"] == "get_me"


def test_route_without_principal_parameter_is_still_protected() -> None:
    """Regression: routes included via include_protected must be protected even if their
    handler doesn't take a principal parameter (protection comes from include_router
    dependencies, not from parameter presence)."""
    from fastapi import APIRouter

    from smart_tutor.apps.api.main import create_app, include_protected

    verifier = FakeTokenVerifier()
    verifier.add(TOKEN, ADA)

    # Create a router with a route that takes no principal
    test_router = APIRouter()

    @test_router.get("/test-no-principal")
    async def test_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    app = create_app(Settings(cors_origins=[ORIGIN]), verifier=verifier)
    include_protected(app, test_router)
    client = TestClient(app)

    # Without token, should be 401
    r = client.get("/test-no-principal")
    assert r.status_code == 401, "Route without principal param should still be protected"

    # With valid token, should be 200
    r = client.get("/test-no-principal", headers=bearer(TOKEN))
    assert r.status_code == 200, "Route without principal param should work with valid token"


def test_router_mutation_does_not_occur_on_multiple_app_creations() -> None:
    """Regression: create_app() should not mutate the original router's dependencies."""
    original_deps_count = len(accounts.router.routes[0].dependencies)

    # Create two apps
    create_app(Settings(cors_origins=[ORIGIN]), verifier=FakeTokenVerifier())
    create_app(Settings(cors_origins=[ORIGIN]), verifier=FakeTokenVerifier())

    # Router's dependencies should not have grown
    assert len(accounts.router.routes[0].dependencies) == original_deps_count, (
        "Router should not be mutated by create_app()"
    )

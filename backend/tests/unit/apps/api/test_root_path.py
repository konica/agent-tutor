"""Behind CloudFront the API is at /api (ADR 0009); the ALB forwards the path unchanged."""

import pytest
from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

TOKEN = "secret-token-value"
ADA = Principal(user_id=UserId("user-ada"), name="Ada Lovelace", roles=frozenset({"learner"}))


@pytest.fixture
def client() -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add(TOKEN, ADA)
    return TestClient(create_app(Settings(root_path="/api", cors_origins=[]), verifier=verifier))


@pytest.mark.parametrize("path", ["/api/me", "/me"])
def test_routes_answer_under_the_root_path(client: TestClient, path: str) -> None:
    r = client.get(path, headers={"Authorization": f"Bearer {TOKEN}"})
    assert r.status_code == 200
    assert r.json()["name"] == "Ada Lovelace"


def test_prefixed_call_without_a_token_is_401_with_bearer_challenge(client: TestClient) -> None:
    r = client.get("/api/me")
    assert r.status_code == 401
    assert r.headers["WWW-Authenticate"].startswith("Bearer")


@pytest.mark.parametrize("path", ["/healthz", "/api/healthz"])
def test_health_answers_with_and_without_the_prefix(client: TestClient, path: str) -> None:
    assert client.get(path).status_code == 200


def test_openapi_names_the_prefix_as_server(client: TestClient) -> None:
    assert client.get("/api/openapi.json").json()["servers"] == [{"url": "/api"}]


def test_root_path_defaults_to_empty() -> None:
    assert Settings().root_path == ""

import pytest
from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier, InMemorySubjects, api_services
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.shared.domain.principal import Principal

AUTH = {"Authorization": "Bearer ada-token"}
IR = "00000000-0000-4000-8000-0000000000a1"


@pytest.fixture
def client() -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add("ada-token", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    services = api_services(catalog=InMemorySubjects({SubjectId(IR): "Information Retrieval"}))
    return TestClient(create_app(Settings(), verifier=verifier, services=services))


def test_search_returns_matches_with_only_id_name_origin(client: TestClient) -> None:
    response = client.get("/subjects/search", params={"q": "retriev"}, headers=AUTH)
    assert response.status_code == 200
    assert response.json() == [{"subject_id": IR, "name": "Information Retrieval", "origin": "shared"}]


@pytest.mark.parametrize("q", ["", "x" * 101])
def test_search_refuses_an_empty_or_huge_query(client: TestClient, q: str) -> None:
    assert client.get("/subjects/search", params={"q": q}, headers=AUTH).status_code == 422


def test_search_needs_a_token(client: TestClient) -> None:
    assert client.get("/subjects/search", params={"q": "x"}).status_code == 401

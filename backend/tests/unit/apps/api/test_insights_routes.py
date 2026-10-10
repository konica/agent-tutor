"""POST /viewer/highlight-misses: a content-free count of highlights the viewer couldn't draw."""

from datetime import date

from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier, FixedClock, InMemoryHighlightMisses, api_services
from smart_tutor.apps.api.main import create_app
from smart_tutor.insights.application import HighlightMissService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

AUTH = {"Authorization": "Bearer t-ada"}


def make_client() -> tuple[TestClient, InMemoryHighlightMisses]:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    counter = InMemoryHighlightMisses()
    services = api_services(highlight_misses=HighlightMissService(counter, FixedClock()))
    return TestClient(create_app(Settings(), verifier=verifier, services=services)), counter


def test_a_miss_adds_one_to_todays_count() -> None:
    client, counter = make_client()

    response = client.post("/viewer/highlight-misses", headers=AUTH)

    assert response.status_code == 204
    assert counter.counts == {date(2026, 10, 4): 1}


def test_needs_a_signed_in_learner() -> None:
    client, counter = make_client()

    assert client.post("/viewer/highlight-misses").status_code == 401
    assert counter.counts == {}


def test_a_body_is_ignored() -> None:
    client, counter = make_client()

    response = client.post("/viewer/highlight-misses", headers=AUTH, json={"chunk_id": "c1", "text": "secret passage"})

    assert response.status_code == 204
    assert counter.counts == {date(2026, 10, 4): 1}

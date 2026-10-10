"""US-12 / #66: one learner's uploads never count toward another's limits, and the status reports only the caller's."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from fakes import APP_TZ, TEST_LIMITS, FakeObjectStore, FakeTokenVerifier, FixedClock, InMemoryLibrary, api_services
from smart_tutor.accounts.application import UploadLimits
from smart_tutor.apps.api.main import create_app
from smart_tutor.knowledge.application import UploadService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}


def setup() -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    library, objects = InMemoryLibrary(), FakeObjectStore()
    clock = FixedClock(datetime(2026, 10, 10, 4, 0, tzinfo=UTC))
    uploads = UploadService(
        library.unit_of_work, objects, clock, TEST_LIMITS, rate=UploadLimits(per_hour=2, per_day=3), time_zone=APP_TZ
    )
    services = api_services(library, objects, uploads=uploads)
    return TestClient(create_app(Settings(), verifier=verifier, services=services))


def test_a_learners_uploads_never_count_toward_anothers_limits() -> None:
    client = setup()
    for name in ("a1.pdf", "a2.pdf"):
        assert client.post("/uploads", json={"file_name": name}, headers=A).status_code == 201
    assert client.post("/uploads", json={"file_name": "a3.pdf"}, headers=A).status_code == 429

    assert client.get("/uploads/rate-limit", headers=B).json()["limit"] is None
    assert client.post("/uploads", json={"file_name": "b1.pdf"}, headers=B).status_code == 201
    assert client.post("/uploads", json={"file_name": "b2.pdf"}, headers=B).status_code == 201


def test_the_status_reports_only_the_callers_limit_and_takes_no_user() -> None:
    client = setup()
    for name in ("a1.pdf", "a2.pdf"):
        client.post("/uploads", json={"file_name": name}, headers=A)
    assert client.get("/uploads/rate-limit", headers=A).json()["limit"] == "hour"
    assert client.get("/uploads/rate-limit", headers=B, params={"user_id": "learner-a"}).json()["limit"] is None

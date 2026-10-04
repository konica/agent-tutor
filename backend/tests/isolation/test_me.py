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

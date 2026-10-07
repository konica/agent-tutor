"""US-12: GET /me/subjects lists only subjects of the caller's own documents."""

from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier, InMemoryLibrary, InMemorySubjects, api_services, ingest_ready
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}
C = {"Authorization": "Bearer token-c"}
SA = SubjectId("00000000-0000-4000-8000-0000000000a1")
SB = SubjectId("00000000-0000-4000-8000-0000000000b1")


def test_each_learner_sees_only_subjects_of_their_own_documents() -> None:
    verifier = FakeTokenVerifier()
    for name in "abc":
        verifier.add(f"token-{name}", Principal(UserId(f"learner-{name}"), name.upper(), frozenset({"learner"})))
    catalog = InMemorySubjects({GENERAL_SUBJECT_ID: "General", SA: "Alpha", SB: "Beta"})
    library = InMemoryLibrary()
    ingest_ready(library, "learner-a", "Alpha text.", subject_ids=[SA])
    ingest_ready(library, "learner-a", "Shared general A.")
    ingest_ready(library, "learner-b", "Beta text.", subject_ids=[SB])
    ingest_ready(library, "learner-b", "Shared general B.")
    client = TestClient(create_app(Settings(), verifier=verifier, services=api_services(library, catalog=catalog)))

    def listed(headers: dict[str, str]) -> list[str]:
        return [s["subject_id"] for s in client.get("/me/subjects", headers=headers).json()]

    assert sorted(listed(A)) == sorted([SA, GENERAL_SUBJECT_ID])
    assert sorted(listed(B)) == sorted([SB, GENERAL_SUBJECT_ID])
    assert listed(C) == []  # others' subjects never leak to a learner with no documents

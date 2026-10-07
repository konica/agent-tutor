"""US-12: GET /me/subjects lists only subjects of the caller's own documents; catalog search never shows who has a
subject or another learner's personal names (US-2b, D21)."""

from collections.abc import Collection

from fastapi.testclient import TestClient

from fakes import (
    TEST_LIMITS,
    FakeObjectStore,
    FakeQueue,
    FakeTokenVerifier,
    InMemoryLibrary,
    InMemorySubjects,
    api_services,
    fake_tools,
    ingest_ready,
)
from smart_tutor.apps.api.main import create_app
from smart_tutor.knowledge.application import IngestionService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID, SubjectNames

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}
C = {"Authorization": "Bearer token-c"}
SA = SubjectId("00000000-0000-4000-8000-0000000000a1")
SB = SubjectId("00000000-0000-4000-8000-0000000000b1")
IR = SubjectId("00000000-0000-4000-8000-0000000000a1")


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


class PersonalNames(SubjectNames):
    """Learner A calls "Information Retrieval" "My secret IR notes"."""

    def names_for(self, user_id: UserId, subject_ids: Collection[SubjectId]) -> dict[SubjectId, str]:
        names = super().names_for(user_id, subject_ids)
        if user_id == "learner-a" and IR in names:
            names[IR] = "My secret IR notes"
        return names


def setup_with_a_holding_ir() -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    library, objects = InMemoryLibrary(), FakeObjectStore()
    catalog = InMemorySubjects({IR: "Information Retrieval"})
    services = api_services(library, objects, catalog=catalog, names=PersonalNames(catalog), queue=FakeQueue())
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    key = stored["fields"]["key"]
    objects.objects[key] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS).ingest_upload(key)
    chosen = client.put(f"/documents/{stored['document_id']}/subjects", json={"subject_ids": [IR]}, headers=A)
    assert chosen.status_code == 200
    return client


def test_b_sees_a_subject_as_shared_by_its_canonical_name() -> None:
    client = setup_with_a_holding_ir()
    a = client.get("/subjects/search", params={"q": "secret"}, headers=A).json()
    assert a == [{"subject_id": IR, "name": "My secret IR notes", "origin": "yours"}]
    assert client.get("/subjects/search", params={"q": "secret"}, headers=B).json() == []
    b = client.get("/subjects/search", params={"q": "retrieval"}, headers=B).json()
    assert b == [{"subject_id": IR, "name": "Information Retrieval", "origin": "shared"}]
    assert client.get("/subjects/search", params={"q": "retrieval", "user_id": "learner-a"}, headers=B).json() == b

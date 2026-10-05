"""US-12: a learner never sees another learner's documents, and can't get a presigned POST for their key."""

from fastapi.testclient import TestClient

from fakes import (
    TEST_LIMITS,
    FakeObjectStore,
    FakeTokenVerifier,
    FixedClock,
    InMemoryLibrary,
    InMemorySubjects,
    fake_tools,
)
from smart_tutor.apps.api.main import create_app
from smart_tutor.apps.api.services import ApiServices
from smart_tutor.knowledge.application import DocumentService, IngestionService, UploadService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.subjects.application import SubjectNames

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}


def setup() -> tuple[TestClient, FakeObjectStore, IngestionService]:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    library, objects = InMemoryLibrary(), FakeObjectStore()
    services = ApiServices(
        uploads=UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS),
        documents=DocumentService(library.unit_of_work),
        subjects=SubjectNames(InMemorySubjects()),
    )
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))
    return client, objects, IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS)


def test_b_never_sees_documents_in_any_state() -> None:
    client, objects, ingestion = setup()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    client.post("/uploads", json={"file_name": "a2.pdf"}, headers=A)  # stays processing
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])

    assert client.get("/documents", headers=B).json() == []
    assert client.get("/documents", headers=B, params={"user_id": "learner-a"}).json() == []
    assert {d["title"] for d in client.get("/documents", headers=A).json()} == {"a1.pdf", "a2.pdf"}


def test_b_never_sees_the_subjects_of_a_document() -> None:
    client, objects, ingestion = setup()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])

    assert [d["subjects"] for d in client.get("/documents", headers=A).json()] == [
        [{"subject_id": "00000000-0000-4000-8000-000000000001", "name": "General"}]
    ]
    assert client.get("/documents", headers=B).json() == []
    assert "General" not in client.get("/documents", headers=B).text


def test_b_cannot_get_a_presigned_post_for_a_key() -> None:
    client, objects, _ = setup()
    forged = client.post(
        "/uploads", json={"file_name": "x.pdf", "user_id": "learner-a", "key": "uploads/learner-a/x.pdf"}, headers=B
    )
    assert forged.status_code == 422  # unknown fields are refused, not ignored
    own = client.post("/uploads", json={"file_name": "x.pdf"}, headers=B, params={"user_id": "learner-a"}).json()
    assert own["fields"]["key"].startswith("uploads/learner-b/")
    assert all(key.startswith("uploads/learner-b/") for key, *_ in objects.presigned)

"""US-12, US-4b: a learner reads a chunk only through a document they can read (archived included)."""

from fastapi.testclient import TestClient

from fakes import (
    TEST_LIMITS,
    FakeObjectStore,
    FakeQueue,
    FakeTokenVerifier,
    InMemoryLibrary,
    api_services,
    fake_tools,
)
from fakes.knowledge import fake_chunk_id
from smart_tutor.apps.api.main import create_app
from smart_tutor.knowledge.application import IngestionService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}


def _setup() -> tuple[TestClient, FakeObjectStore, IngestionService, InMemoryLibrary]:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    library, objects = InMemoryLibrary(), FakeObjectStore()
    services = api_services(library, objects, queue=FakeQueue())
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))
    return client, objects, IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS), library


def _first_chunk_of_a_new_document(
    client: TestClient, objects: FakeObjectStore, ingestion: IngestionService, library: InMemoryLibrary
) -> tuple[str, str]:
    """A's document id and the id of its first chunk."""
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])
    doc = stored["document_id"]
    content_id = library.state.documents[doc].content_id
    assert content_id is not None
    return doc, fake_chunk_id(content_id, 0)


def test_b_cannot_read_a_chunk_of_as_document() -> None:
    client, objects, ingestion, library = _setup()
    doc, chunk = _first_chunk_of_a_new_document(client, objects, ingestion, library)

    assert client.get(f"/chunks/{chunk}", headers=B).status_code == 404
    mine = client.get(f"/chunks/{chunk}", headers=A)
    assert mine.status_code == 200
    body = mine.json()
    assert body["chunk_id"] == chunk and body["document_id"] == doc and body["page"] == 1
    assert body["start_index"] == 0
    assert body["text"].startswith("A sentence about attention")


def test_a_chunk_of_an_archived_document_is_still_readable_by_its_owner() -> None:
    client, objects, ingestion, library = _setup()
    doc, chunk = _first_chunk_of_a_new_document(client, objects, ingestion, library)
    assert client.post(f"/documents/{doc}/archive", headers=A).status_code == 200

    assert client.get(f"/chunks/{chunk}", headers=A).status_code == 200
    assert client.get(f"/chunks/{chunk}", headers=B).status_code == 404


def test_an_unknown_chunk_is_404() -> None:
    client, *_ = _setup()
    assert client.get("/chunks/00000000-0000-4000-8000-000000000000", headers=A).status_code == 404

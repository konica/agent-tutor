import pytest
from fastapi.testclient import TestClient

from fakes import (
    TEST_LIMITS,
    FakeObjectStore,
    FakeQueue,
    FakeTokenVerifier,
    FixedClock,
    InMemoryLibrary,
    InMemorySubjects,
    fake_tools,
)
from smart_tutor.apps.api.main import create_app
from smart_tutor.apps.api.services import ApiServices
from smart_tutor.knowledge.application import (
    DocumentService,
    IngestionService,
    RetryService,
    UploadService,
    retried_content,
)
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID, SubjectNames

AUTH = {"Authorization": "Bearer ada-token"}


@pytest.fixture
def client() -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add("ada-token", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library, objects, queue = InMemoryLibrary(), FakeObjectStore(), FakeQueue()
    services = ApiServices(
        uploads=UploadService(library.unit_of_work, objects, FixedClock(), TEST_LIMITS),
        documents=DocumentService(library.unit_of_work, max_attempts=3),
        subjects=SubjectNames(InMemorySubjects()),
        retries=RetryService(library.unit_of_work, queue, max_attempts=3),
    )
    app = create_app(Settings(), verifier=verifier, services=services)
    app.state.queue = queue
    app.state.objects, app.state.ingestion = (
        objects,
        IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS),
    )
    return TestClient(app)


def test_start_upload_returns_the_presigned_post(client: TestClient) -> None:
    r = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH)
    assert r.status_code == 201
    body = r.json()
    assert body["url"] == "http://s3.test/bucket"
    assert body["fields"]["key"] == f"uploads/ada/{body['upload_id']}.pdf"
    assert set(body) == {"document_id", "upload_id", "url", "fields"}


def test_the_new_document_is_listed_as_processing(client: TestClient) -> None:
    started = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH).json()
    [doc] = client.get("/documents", headers=AUTH).json()
    assert doc["document_id"] == started["document_id"]
    assert (doc["title"], doc["state"], doc["failure_reason"]) == ("paper.pdf", "processing", None)
    assert doc["created_at"].startswith("2026-10-04T09:00:00")


def test_a_ready_document_lists_its_subject_with_the_resolved_name(client: TestClient) -> None:
    started = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH).json()
    key = started["fields"]["key"]
    client.app.state.objects.objects[key] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()  # type: ignore[attr-defined]
    client.app.state.ingestion.ingest_upload(key)  # type: ignore[attr-defined]
    [doc] = client.get("/documents", headers=AUTH).json()
    assert doc["state"] == "ready"
    assert doc["subjects"] == [{"subject_id": str(GENERAL_SUBJECT_ID), "name": "General"}]


def test_a_processing_document_has_no_subjects(client: TestClient) -> None:
    client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH)
    [doc] = client.get("/documents", headers=AUTH).json()
    assert doc["subjects"] == []


def test_blank_file_name_is_422(client: TestClient) -> None:
    assert client.post("/uploads", json={"file_name": "   "}, headers=AUTH).status_code == 422
    assert client.post("/uploads", json={}, headers=AUTH).status_code == 422


def test_openapi_names_the_operations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/uploads"]["post"]["operationId"] == "start_upload"
    assert paths["/documents"]["get"]["operationId"] == "list_documents"
    assert paths["/documents/{document_id}/retry"]["post"]["operationId"] == "retry_document"


def test_upload_limits_come_from_the_upload_service(client: TestClient) -> None:
    response = client.get("/uploads/limits", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"max_bytes": 50 * 1024 * 1024, "max_pages": 500}


def test_upload_limits_need_a_token(client: TestClient) -> None:
    assert client.get("/uploads/limits").status_code == 401


SCAN = b"%PDF-1.7 tiny"  # fake extractor: no text layer → failed


def failed_document(client: TestClient) -> str:
    started = client.post("/uploads", json={"file_name": "scan.pdf"}, headers=AUTH).json()
    client.app.state.objects.objects[started["fields"]["key"]] = SCAN  # type: ignore[attr-defined]
    client.app.state.ingestion.ingest_upload(started["fields"]["key"])  # type: ignore[attr-defined]
    return str(started["document_id"])


def test_retry_returns_a_failed_document_to_processing_with_its_attempt(client: TestClient) -> None:
    doc_id = failed_document(client)
    [before] = client.get("/documents", headers=AUTH).json()
    assert (before["state"], before["attempt"], before["max_attempts"], before["can_retry"]) == ("failed", 1, 3, True)

    assert client.post(f"/documents/{doc_id}/retry", headers=AUTH).status_code == 204
    [after] = client.get("/documents", headers=AUTH).json()
    assert (after["state"], after["attempt"], after["can_retry"], after["failure_reason"]) == (
        "processing",
        2,
        False,
        None,
    )


def test_a_fourth_attempt_is_refused(client: TestClient) -> None:
    doc_id = failed_document(client)
    for _ in range(2):
        assert client.post(f"/documents/{doc_id}/retry", headers=AUTH).status_code == 204
        content_id = retried_content(client.app.state.queue.sent[-1].body)  # type: ignore[attr-defined]
        client.app.state.ingestion.process_content(content_id)  # type: ignore[attr-defined]
    [doc] = client.get("/documents", headers=AUTH).json()
    assert (doc["failure_reason"], doc["can_retry"]) == ("This file could not be processed", False)
    refused = client.post(f"/documents/{doc_id}/retry", headers=AUTH)
    assert (refused.status_code, refused.json()["detail"]) == (409, "This file could not be processed")


def test_retrying_a_document_that_is_not_failed_changes_nothing(client: TestClient) -> None:
    started = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH).json()
    assert client.post(f"/documents/{started['document_id']}/retry", headers=AUTH).status_code == 204
    [doc] = client.get("/documents", headers=AUTH).json()
    assert (doc["state"], doc["attempt"]) == ("processing", None)
    assert client.app.state.queue.sent == []  # type: ignore[attr-defined]


def test_retry_of_an_unknown_or_malformed_id(client: TestClient) -> None:
    assert client.post("/documents/00000000-0000-4000-8000-00000000dead/retry", headers=AUTH).status_code == 404
    assert client.post("/documents/not-a-uuid/retry", headers=AUTH).status_code == 422
    assert client.post("/documents/00000000-0000-4000-8000-00000000dead/retry").status_code == 401

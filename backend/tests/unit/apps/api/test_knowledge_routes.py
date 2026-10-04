import pytest
from fastapi.testclient import TestClient

from fakes import FakeObjectStore, FakeTokenVerifier, FixedClock, InMemoryLibrary
from smart_tutor.apps.api.main import create_app
from smart_tutor.apps.api.services import ApiServices
from smart_tutor.knowledge.application import DocumentService, UploadService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

AUTH = {"Authorization": "Bearer ada-token"}


@pytest.fixture
def client() -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add("ada-token", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library = InMemoryLibrary()
    services = ApiServices(
        uploads=UploadService(library.unit_of_work, FakeObjectStore(), FixedClock()),
        documents=DocumentService(library.unit_of_work),
    )
    return TestClient(create_app(Settings(), verifier=verifier, services=services))


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


def test_blank_file_name_is_422(client: TestClient) -> None:
    assert client.post("/uploads", json={"file_name": "   "}, headers=AUTH).status_code == 422
    assert client.post("/uploads", json={}, headers=AUTH).status_code == 422


def test_openapi_names_the_operations(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert paths["/uploads"]["post"]["operationId"] == "start_upload"
    assert paths["/documents"]["get"]["operationId"] == "list_documents"

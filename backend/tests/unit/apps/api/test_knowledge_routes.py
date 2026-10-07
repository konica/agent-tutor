import hashlib

import pytest
from fastapi.testclient import TestClient

from fakes import (
    TEST_LIMITS,
    FakeObjectStore,
    FakeTokenVerifier,
    InMemoryLibrary,
    api_services,
    fake_tools,
)
from smart_tutor.apps.api.main import create_app
from smart_tutor.knowledge.application import IngestionService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

AUTH = {"Authorization": "Bearer ada-token"}


@pytest.fixture
def client() -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add("ada-token", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library, objects = InMemoryLibrary(), FakeObjectStore()
    services = api_services(library, objects)
    app = create_app(Settings(), verifier=verifier, services=services)
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


def test_a_processed_document_waits_for_subjects(client: TestClient) -> None:
    started = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH).json()
    key = started["fields"]["key"]
    client.app.state.objects.objects[key] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()  # type: ignore[attr-defined]
    client.app.state.ingestion.ingest_upload(key)  # type: ignore[attr-defined]
    [doc] = client.get("/documents", headers=AUTH).json()
    assert doc["state"] == "awaiting_subjects"
    assert doc["subjects"] == []


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
    assert paths["/documents/duplicate-check"]["post"]["operationId"] == "check_duplicate"


def test_upload_limits_come_from_the_upload_service(client: TestClient) -> None:
    response = client.get("/uploads/limits", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"max_bytes": 50 * 1024 * 1024, "max_pages": 500}


def test_upload_limits_need_a_token(client: TestClient) -> None:
    assert client.get("/uploads/limits").status_code == 401


def test_duplicate_check_finds_the_callers_document(client: TestClient) -> None:
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    started = client.post("/uploads", json={"file_name": "a.pdf"}, headers=AUTH).json()
    client.app.state.objects.objects[started["fields"]["key"]] = pdf  # type: ignore[attr-defined]
    client.app.state.ingestion.ingest_upload(started["fields"]["key"])  # type: ignore[attr-defined]

    sha = hashlib.sha256(pdf).hexdigest()
    found = client.post("/documents/duplicate-check", json={"sha256": sha}, headers=AUTH)
    assert found.status_code == 200
    assert found.json() == {"document_id": started["document_id"]}
    missing = client.post("/documents/duplicate-check", json={"sha256": "0" * 64}, headers=AUTH)
    assert missing.json() == {"document_id": None}


@pytest.mark.parametrize("body", [{"sha256": "A" * 64}, {"sha256": "0" * 63}, {"sha256": "0" * 64, "user_id": "x"}, {}])
def test_duplicate_check_refuses_a_malformed_request(client: TestClient, body: dict[str, str]) -> None:
    assert client.post("/documents/duplicate-check", json=body, headers=AUTH).status_code == 422


def test_duplicate_check_needs_a_token(client: TestClient) -> None:
    assert client.post("/documents/duplicate-check", json={"sha256": "0" * 64}).status_code == 401


def awaiting_document(client: TestClient) -> str:
    started = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH).json()
    key = started["fields"]["key"]
    client.app.state.objects.objects[key] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()  # type: ignore[attr-defined]
    client.app.state.ingestion.ingest_upload(key)  # type: ignore[attr-defined]
    return str(started["document_id"])


def test_suggestions_for_an_awaiting_document(client: TestClient) -> None:
    doc = awaiting_document(client)

    r = client.get(f"/documents/{doc}/subject-suggestions", headers=AUTH)

    assert r.status_code == 200
    body = r.json()
    assert body["document_id"] == doc
    assert body["summary"]
    assert len(body["suggestions"]) == 3
    assert {s["origin"] for s in body["suggestions"]} <= {"shared", "yours", "new"}
    assert all(s["name"] for s in body["suggestions"])


def test_choosing_a_suggestion_makes_the_document_ready(client: TestClient) -> None:
    doc = awaiting_document(client)
    [first, *_] = client.get(f"/documents/{doc}/subject-suggestions", headers=AUTH).json()["suggestions"]

    r = client.put(f"/documents/{doc}/subjects", json={"new_names": [first["name"]]}, headers=AUTH)

    assert r.status_code == 200
    assert r.json()["state"] == "ready"
    assert [s["name"] for s in r.json()["subjects"]] == [first["name"]]
    [listed] = client.get("/documents", headers=AUTH).json()
    assert (listed["state"], [s["name"] for s in listed["subjects"]]) == ("ready", [first["name"]])


def test_choosing_an_existing_subject_by_id(client: TestClient) -> None:
    doc = awaiting_document(client)
    general = "00000000-0000-4000-8000-000000000001"

    r = client.put(f"/documents/{doc}/subjects", json={"subject_ids": [general]}, headers=AUTH)

    assert r.status_code == 200
    assert r.json()["subjects"] == [{"subject_id": general, "name": "General"}]


@pytest.mark.parametrize(
    "body",
    [
        {"subject_ids": [], "new_names": []},
        {"subject_ids": [f"00000000-0000-4000-8000-00000000000{n}" for n in range(1, 5)]},
        {"subject_ids": ["00000000-0000-4000-8000-000000000001"] * 2},
        {"subject_ids": ["00000000-0000-4000-8000-0000000000ff"]},
        {"subject_ids": ["abc"]},
        {"new_names": [""]},
        {"new_names": ["x" * 61]},
        {"subject_ids": ["00000000-0000-4000-8000-000000000001"], "user_id": "x"},
    ],
)
def test_choosing_refuses_an_invalid_request(client: TestClient, body: dict[str, object]) -> None:
    doc = awaiting_document(client)

    assert client.put(f"/documents/{doc}/subjects", json=body, headers=AUTH).status_code == 422
    [listed] = client.get("/documents", headers=AUTH).json()
    assert listed["state"] == "awaiting_subjects"


def test_a_malformed_document_id_is_422(client: TestClient) -> None:
    assert client.put("/documents/abc/subjects", json={"new_names": ["X"]}, headers=AUTH).status_code == 422
    assert client.get("/documents/abc/subject-suggestions", headers=AUTH).status_code == 422


def test_a_processing_document_is_409(client: TestClient) -> None:
    doc = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH).json()["document_id"]

    assert client.get(f"/documents/{doc}/subject-suggestions", headers=AUTH).status_code == 409
    put = client.put(f"/documents/{doc}/subjects", json={"new_names": ["X"]}, headers=AUTH)
    assert put.status_code == 409


def test_an_unknown_document_is_404(client: TestClient) -> None:
    doc = "00000000-0000-4000-8000-0000000000aa"

    assert client.get(f"/documents/{doc}/subject-suggestions", headers=AUTH).status_code == 404
    assert client.put(f"/documents/{doc}/subjects", json={"new_names": ["X"]}, headers=AUTH).status_code == 404


def test_the_subject_routes_need_a_token(client: TestClient) -> None:
    doc = "00000000-0000-4000-8000-0000000000aa"

    assert client.get(f"/documents/{doc}/subject-suggestions").status_code == 401
    assert client.put(f"/documents/{doc}/subjects", json={"new_names": ["X"]}).status_code == 401

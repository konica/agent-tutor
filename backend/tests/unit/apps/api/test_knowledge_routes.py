import hashlib
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from fakes import (
    TEST_LIMITS,
    FakeObjectStore,
    FakeQueue,
    FakeTokenVerifier,
    FixedClock,
    InMemoryLibrary,
    api_services,
    fake_tools,
)
from smart_tutor.apps.api.main import create_app
from smart_tutor.knowledge.application import IngestionService, retried_content
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

AUTH = {"Authorization": "Bearer ada-token"}


@pytest.fixture
def client() -> TestClient:
    verifier = FakeTokenVerifier()
    verifier.add("ada-token", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library, objects, queue = InMemoryLibrary(), FakeObjectStore(), FakeQueue()
    services = api_services(library, objects, queue=queue)
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
    assert paths["/subjects/search"]["get"]["operationId"] == "search_subjects"
    assert paths["/documents/duplicate-check"]["post"]["operationId"] == "check_duplicate"
    assert paths["/documents/{document_id}/retry"]["post"]["operationId"] == "retry_document"


def test_upload_limits_come_from_the_upload_service(client: TestClient) -> None:
    response = client.get("/uploads/limits", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {"max_bytes": 50 * 1024 * 1024, "max_pages": 500}


def test_upload_limits_need_a_token(client: TestClient) -> None:
    assert client.get("/uploads/limits").status_code == 401


def test_an_own_duplicate_upload_reports_the_existing_document(client: TestClient) -> None:
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    first = client.post("/uploads", json={"file_name": "a.pdf"}, headers=AUTH).json()
    again = client.post("/uploads", json={"file_name": "copy.pdf"}, headers=AUTH).json()
    pending = client.get(f"/uploads/{again['upload_id']}", headers=AUTH).json()
    assert pending["outcome"] is None
    for started in (first, again):
        client.app.state.objects.objects[started["fields"]["key"]] = pdf  # type: ignore[attr-defined]
        client.app.state.ingestion.ingest_upload(started["fields"]["key"])  # type: ignore[attr-defined]

    response = client.get(f"/uploads/{again['upload_id']}", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {
        "upload_id": again["upload_id"],
        "outcome": "duplicate",
        "document_id": first["document_id"],
        "archived": False,
    }


def test_an_unknown_upload_is_404(client: TestClient) -> None:
    assert client.get("/uploads/00000000-0000-4000-8000-0000000000aa", headers=AUTH).status_code == 404


def test_a_malformed_upload_id_is_422(client: TestClient) -> None:
    assert client.get("/uploads/not-a-uuid", headers=AUTH).status_code == 422


def test_upload_status_needs_a_token(client: TestClient) -> None:
    assert client.get("/uploads/00000000-0000-4000-8000-0000000000aa").status_code == 401


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
    # Distinct bytes per call: the learner's own identical file would be a duplicate (US-11).
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode() + started["upload_id"].encode()
    client.app.state.objects.objects[key] = pdf  # type: ignore[attr-defined]
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


def test_a_typed_name_is_trimmed_and_may_be_60_characters_with_padding(client: TestClient) -> None:
    doc = awaiting_document(client)
    name = "y" * 60

    r = client.put(f"/documents/{doc}/subjects", json={"new_names": [f"  {name}  "]}, headers=AUTH)

    assert r.status_code == 200
    assert [s["name"] for s in r.json()["subjects"]] == [name]


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
        {"new_names": ["   "]},
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


GENERAL = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-0000000000ff"


def library_of_three(client: TestClient) -> dict[str, str]:
    """A ready document (General), one awaiting subjects, and one still processing; ids by state."""
    ready = awaiting_document(client)
    client.put(f"/documents/{ready}/subjects", json={"subject_ids": [GENERAL]}, headers=AUTH)
    awaiting = awaiting_document(client)
    processing = client.post("/uploads", json={"file_name": "new.pdf"}, headers=AUTH).json()["document_id"]
    return {"ready": ready, "awaiting_subjects": awaiting, "processing": processing}


def listed_ids(client: TestClient, params: dict[str, str] | list[tuple[str, str]]) -> set[str]:
    r = client.get("/documents", headers=AUTH, params=params)
    assert r.status_code == 200
    return {d["document_id"] for d in r.json()}


def test_documents_carry_authors_and_year(client: TestClient) -> None:
    awaiting_document(client)
    client.post("/uploads", json={"file_name": "new.pdf"}, headers=AUTH)

    by_title = {d["title"]: d for d in client.get("/documents", headers=AUTH).json()}

    processed = next(d for d in by_title.values() if d["state"] == "awaiting_subjects")
    assert (processed["authors"], processed["year"]) == (["Ashish Vaswani", "Noam Shazeer"], 2017)
    assert (by_title["new.pdf"]["authors"], by_title["new.pdf"]["year"]) == ([], None)


def test_no_filter_lists_everything(client: TestClient) -> None:
    ids = library_of_three(client)
    assert listed_ids(client, {}) == set(ids.values())


def test_filter_by_state(client: TestClient) -> None:
    ids = library_of_three(client)
    assert listed_ids(client, {"state": "ready"}) == {ids["ready"]}
    both = [("state", "ready"), ("state", "processing")]
    assert listed_ids(client, both) == {ids["ready"], ids["processing"]}


def test_filter_by_subject(client: TestClient) -> None:
    ids = library_of_three(client)
    assert listed_ids(client, {"subject_id": GENERAL}) == {ids["ready"]}
    assert listed_ids(client, {"subject_id": OTHER}) == set()


def test_repeated_subject_id_matches_any_of_them(client: TestClient) -> None:
    ids = library_of_three(client)
    assert listed_ids(client, [("subject_id", OTHER), ("subject_id", GENERAL)]) == {ids["ready"]}


def test_filter_by_upload_dates_in_gmt_plus_7(client: TestClient) -> None:
    ids = library_of_three(client)  # all uploaded at 2026-10-04T09:00Z, which is 16:00 on Oct 4 in GMT+7
    everything = set(ids.values())
    assert listed_ids(client, {"uploaded_from": "2026-10-04", "uploaded_to": "2026-10-04"}) == everything
    assert listed_ids(client, {"uploaded_from": "2026-10-05"}) == set()
    assert listed_ids(client, {"uploaded_to": "2026-10-03"}) == set()
    assert listed_ids(client, {"uploaded_from": "2026-10-01", "uploaded_to": "2026-10-04"}) == everything


def test_filters_combine(client: TestClient) -> None:
    ids = library_of_three(client)
    params = {"subject_id": GENERAL, "state": "ready", "uploaded_from": "2026-10-04", "uploaded_to": "2026-10-04"}
    assert listed_ids(client, params) == {ids["ready"]}
    assert listed_ids(client, {**params, "state": "failed"}) == set()


@pytest.mark.parametrize(
    "params",
    [
        {"subject_id": "not-a-uuid"},
        {"state": "archived"},
        {"uploaded_from": "yesterday"},
        {"uploaded_to": "2026-13-45"},
    ],
)
def test_a_malformed_filter_is_422(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/documents", headers=AUTH, params=params).status_code == 422


def test_more_than_100_subject_ids_is_422(client: TestClient) -> None:
    params = [("subject_id", f"00000000-0000-4000-8000-{n:012d}") for n in range(101)]
    assert client.get("/documents", headers=AUTH, params=params).status_code == 422


def test_upload_date_filter_uses_the_gmt_plus_7_day_at_the_boundary() -> None:
    verifier = FakeTokenVerifier()
    verifier.add("ada-token", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    clock = FixedClock(datetime(2026, 10, 1, 17, 30, tzinfo=UTC))  # 00:30 on Oct 2 in GMT+7
    services = api_services(InMemoryLibrary(), FakeObjectStore(), queue=FakeQueue(), clock=clock)
    boundary = TestClient(create_app(Settings(), verifier=verifier, services=services))
    document_id = boundary.post("/uploads", json={"file_name": "late.pdf"}, headers=AUTH).json()["document_id"]

    assert listed_ids(boundary, {"uploaded_to": "2026-10-01"}) == set()
    assert listed_ids(boundary, {"uploaded_from": "2026-10-02", "uploaded_to": "2026-10-02"}) == {document_id}


def test_a_range_with_from_after_to_is_empty_not_an_error(client: TestClient) -> None:
    library_of_three(client)
    assert listed_ids(client, {"uploaded_from": "2026-10-05", "uploaded_to": "2026-10-01"}) == set()


def ready_document(client: TestClient) -> str:
    doc = awaiting_document(client)
    assert client.put(f"/documents/{doc}/subjects", json={"subject_ids": [GENERAL]}, headers=AUTH).status_code == 200
    return doc


def test_archive_moves_a_document_to_the_archived_list(client: TestClient) -> None:
    doc = ready_document(client)

    r = client.post(f"/documents/{doc}/archive", headers=AUTH)

    assert r.status_code == 200
    assert (r.json()["document_id"], r.json()["archived"]) == (doc, True)
    assert listed_ids(client, {}) == set()
    assert listed_ids(client, {"archived": "true"}) == {doc}
    assert listed_ids(client, {"archived": "false"}) == set()


def test_the_file_link_of_a_processing_document_is_409(client: TestClient) -> None:
    started = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH).json()
    r = client.get(f"/documents/{started['document_id']}/file", headers=AUTH)
    assert r.status_code == 409
    assert r.json()["detail"] == "This document can't be opened until it has been processed"


def test_the_file_link_of_an_archived_document_opens(client: TestClient) -> None:
    doc = ready_document(client)
    client.post(f"/documents/{doc}/archive", headers=AUTH)
    r = client.get(f"/documents/{doc}/file", headers=AUTH)
    assert r.status_code == 200
    assert (r.json()["document"]["document_id"], r.json()["document"]["archived"]) == (doc, True)
    assert r.json()["url"].startswith("https://s3.test/contents/ada/")


def test_the_file_link_of_an_unknown_document_is_404(client: TestClient) -> None:
    r = client.get("/documents/00000000-0000-4000-8000-0000000000aa/file", headers=AUTH)
    assert (r.status_code, r.json()["detail"]) == (404, "Document not found")


def test_archive_twice_is_harmless(client: TestClient) -> None:
    doc = ready_document(client)
    assert client.post(f"/documents/{doc}/archive", headers=AUTH).status_code == 200
    again = client.post(f"/documents/{doc}/archive", headers=AUTH)
    assert (again.status_code, again.json()["archived"]) == (200, True)


def test_restore_brings_the_document_back(client: TestClient) -> None:
    doc = ready_document(client)
    client.post(f"/documents/{doc}/archive", headers=AUTH)

    r = client.post(f"/documents/{doc}/restore", headers=AUTH)

    assert (r.status_code, r.json()["archived"]) == (200, False)
    assert listed_ids(client, {}) == {doc}
    assert listed_ids(client, {"archived": "true"}) == set()
    assert client.post(f"/documents/{doc}/restore", headers=AUTH).status_code == 200


def test_archive_and_restore_of_an_unknown_document_are_404(client: TestClient) -> None:
    unknown = "00000000-0000-4000-8000-0000000000aa"
    for action in ("archive", "restore"):
        r = client.post(f"/documents/{unknown}/{action}", headers=AUTH)
        assert (r.status_code, r.json()["detail"]) == (404, "Document not found")


def test_my_subjects_loses_the_subject_while_archived(client: TestClient) -> None:
    doc = ready_document(client)
    assert [s["subject_id"] for s in client.get("/me/subjects", headers=AUTH).json()] == [GENERAL]

    client.post(f"/documents/{doc}/archive", headers=AUTH)
    assert client.get("/me/subjects", headers=AUTH).json() == []

    client.post(f"/documents/{doc}/restore", headers=AUTH)
    assert [s["subject_id"] for s in client.get("/me/subjects", headers=AUTH).json()] == [GENERAL]


def test_choosing_subjects_of_an_archived_document_is_409(client: TestClient) -> None:
    doc = awaiting_document(client)
    client.post(f"/documents/{doc}/archive", headers=AUTH)

    r = client.put(f"/documents/{doc}/subjects", json={"subject_ids": [GENERAL]}, headers=AUTH)
    assert r.status_code == 409
    assert client.get(f"/documents/{doc}/subject-suggestions", headers=AUTH).status_code == 409


def test_archive_routes_need_a_token(client: TestClient) -> None:
    unknown = "00000000-0000-4000-8000-0000000000aa"
    assert client.post(f"/documents/{unknown}/archive").status_code == 401
    assert client.post(f"/documents/{unknown}/restore").status_code == 401


def test_get_document_returns_its_details(client: TestClient) -> None:
    doc = ready_document(client)
    r = client.get(f"/documents/{doc}", headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["document_id"] == doc
    assert body["file_name"] == "paper.pdf"
    assert body["title_overridden"] is False
    assert len(body["subjects"]) == 1 and body["subjects"][0]["name"]
    assert "summary" in body and "pages" in body and "doi" in body and "extracted_title" in body
    assert body["pages"] is not None


def test_get_unknown_document_is_404(client: TestClient) -> None:
    assert client.get("/documents/00000000-0000-4000-8000-0000000000aa", headers=AUTH).status_code == 404


def test_set_title_trims_and_lists_the_new_title(client: TestClient) -> None:
    doc = ready_document(client)
    r = client.put(f"/documents/{doc}/title", json={"title": "  Mine  "}, headers=AUTH)
    assert r.status_code == 200
    assert (r.json()["title"], r.json()["title_overridden"]) == ("Mine", True)
    assert [d["title"] for d in client.get("/documents", headers=AUTH).json()] == ["Mine"]


def test_null_title_goes_back_to_the_extracted_title(client: TestClient) -> None:
    doc = ready_document(client)
    before = client.get(f"/documents/{doc}", headers=AUTH).json()["title"]
    client.put(f"/documents/{doc}/title", json={"title": "Mine"}, headers=AUTH)
    r = client.put(f"/documents/{doc}/title", json={"title": None}, headers=AUTH)
    assert r.status_code == 200
    assert (r.json()["title"], r.json()["title_overridden"]) == (before, False)


def test_set_title_refuses_a_blank_or_long_title(client: TestClient) -> None:
    doc = ready_document(client)
    blank = client.put(f"/documents/{doc}/title", json={"title": "   "}, headers=AUTH)
    assert (blank.status_code, blank.json()["detail"]) == (422, "Enter a title")
    long = client.put(f"/documents/{doc}/title", json={"title": "x" * 301}, headers=AUTH)
    assert long.status_code == 422 and "300 characters" in long.json()["detail"]
    assert client.get(f"/documents/{doc}", headers=AUTH).json()["title_overridden"] is False


@pytest.mark.parametrize("body", [{"title": "x", "owner_id": "b"}, {}])
def test_set_title_refuses_a_bad_body(client: TestClient, body: dict[str, object]) -> None:
    doc = ready_document(client)
    assert client.put(f"/documents/{doc}/title", json=body, headers=AUTH).status_code == 422


def test_set_title_of_an_unknown_document_is_404(client: TestClient) -> None:
    unknown = "00000000-0000-4000-8000-0000000000aa"
    assert client.put(f"/documents/{unknown}/title", json={"title": "x"}, headers=AUTH).status_code == 404


def test_delete_answers_204_and_the_document_leaves_both_lists(client: TestClient) -> None:
    active, archived = ready_document(client), ready_document(client)
    client.post(f"/documents/{archived}/archive", headers=AUTH)

    for doc in (active, archived):
        r = client.delete(f"/documents/{doc}", headers=AUTH)
        assert (r.status_code, r.content) == (204, b"")

    assert listed_ids(client, {}) == set()
    assert listed_ids(client, {"archived": "true"}) == set()


def test_delete_of_a_processing_document_is_409(client: TestClient) -> None:
    doc = client.post("/uploads", json={"file_name": "paper.pdf"}, headers=AUTH).json()["document_id"]

    r = client.delete(f"/documents/{doc}", headers=AUTH)

    assert (r.status_code, r.json()["detail"]) == (409, "This document is still processing")
    assert listed_ids(client, {}) == {doc}


def test_delete_of_an_unknown_document_is_404(client: TestClient) -> None:
    r = client.delete("/documents/00000000-0000-4000-8000-0000000000aa", headers=AUTH)

    assert (r.status_code, r.json()["detail"]) == (404, "Document not found")


def test_delete_needs_a_token(client: TestClient) -> None:
    assert client.delete("/documents/00000000-0000-4000-8000-0000000000aa").status_code == 401


def test_a_deleted_documents_subject_leaves_my_subjects_unless_another_document_has_it(client: TestClient) -> None:
    shared, other = ready_document(client), awaiting_document(client)
    client.put(f"/documents/{other}/subjects", json={"new_names": ["Topology"]}, headers=AUTH)
    names = {s["name"] for s in client.get("/me/subjects", headers=AUTH).json()}
    assert names == {"General", "Topology"}

    assert client.delete(f"/documents/{other}", headers=AUTH).status_code == 204

    assert [s["subject_id"] for s in client.get("/me/subjects", headers=AUTH).json()] == [GENERAL]
    assert listed_ids(client, {}) == {shared}

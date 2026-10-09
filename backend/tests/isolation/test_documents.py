"""US-12: a learner never sees another learner's documents, and can't get a presigned POST for their key.

US-11: each learner's upload is their own content; a learner's own duplicate points to their existing document, and
another learner's upload status is a 404. The browser hash check (D19) answers only from the caller's own library
and links nothing.
"""

import hashlib

import httpx
from fastapi.testclient import TestClient

from fakes import (
    DESCRIPTION_ARGS,
    TEST_LIMITS,
    FakeObjectStore,
    FakeQueue,
    FakeTokenVerifier,
    InMemoryLibrary,
    InMemoryThreads,
    api_services,
    fake_agent,
    fake_tools,
    ingest_ready,
)
from smart_tutor.apps.api.main import create_app
from smart_tutor.knowledge.application import IngestionService, UploadOutcome
from smart_tutor.knowledge.domain.content import content_key, pages_key
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}


def setup_with_library() -> tuple[TestClient, FakeObjectStore, IngestionService, InMemoryLibrary]:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    library, objects = InMemoryLibrary(), FakeObjectStore()
    services = api_services(library, objects, queue=FakeQueue())
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))
    return client, objects, IngestionService(library.unit_of_work, objects, fake_tools(), TEST_LIMITS), library


def setup() -> tuple[TestClient, FakeObjectStore, IngestionService]:
    client, objects, ingestion, _ = setup_with_library()
    return client, objects, ingestion


def test_b_never_sees_documents_in_any_state() -> None:
    client, objects, ingestion = setup()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    client.post("/uploads", json={"file_name": "a2.pdf"}, headers=A)  # stays processing
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])

    assert client.get("/documents", headers=B).json() == []
    assert client.get("/documents", headers=B, params={"user_id": "learner-a"}).json() == []
    assert {d["title"] for d in client.get("/documents", headers=A).json()} == {DESCRIPTION_ARGS["title"], "a2.pdf"}


def test_b_never_sees_the_subjects_of_a_document() -> None:
    client, objects, ingestion = setup()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])

    general = "00000000-0000-4000-8000-000000000001"
    chosen = client.put(f"/documents/{stored['document_id']}/subjects", json={"subject_ids": [general]}, headers=A)

    assert chosen.status_code == 200
    assert [(d["state"], [s["name"] for s in d["subjects"]]) for d in client.get("/documents", headers=A).json()] == [
        ("ready", ["General"])
    ]
    assert client.get("/documents", headers=B).json() == []


def test_b_cannot_read_a_suggestions_or_set_a_subjects() -> None:
    client, objects, ingestion = setup()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])
    doc = stored["document_id"]

    assert client.get(f"/documents/{doc}/subject-suggestions", headers=B).status_code == 404
    put = client.put(f"/documents/{doc}/subjects", json={"new_names": ["Deep Learning"]}, headers=B)
    assert put.status_code == 404
    [mine] = client.get("/documents", headers=A).json()
    assert (mine["state"], mine["subjects"]) == ("awaiting_subjects", [])
    assert client.get(f"/documents/{doc}/subject-suggestions", headers=A).status_code == 200


def test_b_cannot_get_a_presigned_post_for_a_key() -> None:
    client, objects, _ = setup()
    forged = client.post(
        "/uploads", json={"file_name": "x.pdf", "user_id": "learner-a", "key": "uploads/learner-a/x.pdf"}, headers=B
    )
    assert forged.status_code == 422  # unknown fields are refused, not ignored
    own = client.post("/uploads", json={"file_name": "x.pdf"}, headers=B, params={"user_id": "learner-a"}).json()
    assert own["fields"]["key"].startswith("uploads/learner-b/")
    assert all(key.startswith("uploads/learner-b/") for key, *_ in objects.presigned)


def test_b_cannot_retry_a_documents_processing() -> None:
    client, objects, ingestion = setup()
    started = client.post("/uploads", json={"file_name": "scan.pdf"}, headers=A).json()
    objects.objects[started["fields"]["key"]] = b"%PDF-1.7 tiny"
    ingestion.ingest_upload(started["fields"]["key"])

    response = client.post(f"/documents/{started['document_id']}/retry", headers=B)

    assert response.status_code == 404  # the same answer as for a document that doesn't exist
    [doc] = client.get("/documents", headers=A).json()
    assert (doc["state"], doc["attempt"]) == ("failed", 1)


def test_b_checking_as_file_hash_finds_nothing() -> None:
    client, objects, ingestion = setup()
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = pdf
    ingestion.ingest_upload(stored["fields"]["key"])
    sha = hashlib.sha256(pdf).hexdigest()

    assert client.post("/documents/duplicate-check", json={"sha256": sha}, headers=A).json() == {
        "document_id": stored["document_id"]
    }
    assert client.post("/documents/duplicate-check", json={"sha256": sha}, headers=B).json() == {"document_id": None}
    assert client.get("/documents", headers=B).json() == []  # the check linked nothing


def test_b_filters_find_nothing_of_a_and_a_filtered_list_holds_only_as() -> None:
    client, objects, ingestion = setup()
    general = "00000000-0000-4000-8000-000000000001"
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])
    client.put(f"/documents/{stored['document_id']}/subjects", json={"subject_ids": [general]}, headers=A)
    client.post("/uploads", json={"file_name": "b1.pdf"}, headers=B)  # B's own document, still processing
    day = {"uploaded_from": "2026-10-04", "uploaded_to": "2026-10-04"}

    by_subject = client.get("/documents", headers=B, params={"subject_id": general}).json()
    by_state = client.get("/documents", headers=B, params={"state": "ready"}).json()
    by_dates = client.get("/documents", headers=B, params=day).json()
    mine = client.get("/documents", headers=A, params={"subject_id": general, "state": "ready", **day}).json()

    assert by_subject == []
    assert by_state == []
    assert [d["title"] for d in by_dates] == ["b1.pdf"]  # the range covers A's upload too, but B sees only B's
    assert [d["document_id"] for d in mine] == [stored["document_id"]]


def test_two_learners_with_the_same_file_each_get_their_own_document_and_never_see_the_other() -> None:
    client, objects, ingestion = setup()
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    a = client.post("/uploads", json={"file_name": "a.pdf"}, headers=A).json()
    b = client.post("/uploads", json={"file_name": "b.pdf"}, headers=B).json()
    for started in (a, b):
        objects.objects[started["fields"]["key"]] = pdf
        assert ingestion.ingest_upload(started["fields"]["key"]) is UploadOutcome.STORED

    [doc_a] = client.get("/documents", headers=A).json()
    [doc_b] = client.get("/documents", headers=B).json()
    assert (doc_a["document_id"], doc_b["document_id"]) == (a["document_id"], b["document_id"])
    assert doc_a["state"] == doc_b["state"] == "awaiting_subjects"
    assert client.get(f"/uploads/{a['upload_id']}", headers=A).json()["document_id"] == a["document_id"]
    assert client.get(f"/uploads/{a['upload_id']}", headers=B).status_code == 404
    assert client.get(f"/uploads/{b['upload_id']}", headers=A).status_code == 404


def test_a_learners_own_duplicate_points_to_their_document() -> None:
    client, objects, ingestion = setup()
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    first = client.post("/uploads", json={"file_name": "a.pdf"}, headers=A).json()
    again = client.post("/uploads", json={"file_name": "copy.pdf"}, headers=A).json()
    for started in (first, again):
        objects.objects[started["fields"]["key"]] = pdf
        ingestion.ingest_upload(started["fields"]["key"])
    assert [d["document_id"] for d in client.get("/documents", headers=A).json()] == [first["document_id"]]
    assert client.get(f"/uploads/{again['upload_id']}", headers=A).json() == {
        "upload_id": again["upload_id"],
        "outcome": "duplicate",
        "document_id": first["document_id"],
        "archived": False,
    }


def test_b_cannot_archive_restore_or_see_as_archived_document() -> None:
    client, objects, ingestion = setup()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])
    doc = stored["document_id"]

    assert client.post(f"/documents/{doc}/archive", headers=B).status_code == 404
    assert [d["archived"] for d in client.get("/documents", headers=A).json()] == [False]
    assert client.post(f"/documents/{doc}/archive", headers=A).status_code == 200
    assert client.get("/documents", headers=B, params={"archived": "true"}).json() == []
    assert client.post(f"/documents/{doc}/restore", headers=B).status_code == 404
    assert [d["document_id"] for d in client.get("/documents", headers=A, params={"archived": "true"}).json()] == [doc]


def test_b_cant_delete_as_document_and_as_copy_of_the_same_file_is_untouched() -> None:
    client, objects, ingestion, library = setup_with_library()
    pdf = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    a = client.post("/uploads", json={"file_name": "a.pdf"}, headers=A).json()
    b = client.post("/uploads", json={"file_name": "b.pdf"}, headers=B).json()
    for started in (a, b):
        objects.objects[started["fields"]["key"]] = pdf
        ingestion.ingest_upload(started["fields"]["key"])
    state = library.state
    content_of = {d.document_id: d.content_id for d in state.documents.values()}
    a_content, b_content = content_of[a["document_id"]], content_of[b["document_id"]]
    assert a_content != b_content  # two contents (ADR 0011)
    assert state.chunks[a_content] and state.chunks[b_content]

    assert client.delete(f"/documents/{a['document_id']}", headers=B).status_code == 404
    assert [d["document_id"] for d in client.get("/documents", headers=A).json()] == [a["document_id"]]
    assert objects.versions_deleted == []

    assert client.delete(f"/documents/{a['document_id']}", headers=A).status_code == 204

    state = library.state  # committed work replaces the state object
    assert client.get("/documents", headers=A).json() == []
    assert a["document_id"] not in state.documents and a_content not in state.contents
    assert not state.chunks.get(a_content)
    assert sorted(objects.versions_deleted) == sorted(
        [content_key(UserId("learner-a"), a_content), pages_key(UserId("learner-a"), a_content)]
    )
    assert [d["document_id"] for d in client.get("/documents", headers=B).json()] == [b["document_id"]]
    assert b["document_id"] in state.documents and b_content in state.contents and state.chunks[b_content]
    assert content_key(UserId("learner-b"), b_content) in objects.objects


def test_after_a_delete_as_conversation_lists_it_as_deleted() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    doc = ingest_ready(library, "learner-a", "Attention weighs tokens.")
    title = library.state.documents[doc].file_name
    body = (
        b'event: delta\ndata: {"text": "Hi"}\n\n'
        + f'event: sources\ndata: {{"document_ids": ["{doc}"]}}\n\n'.encode()
        + b"event: done\ndata: {}\n\n"
    )
    agent = fake_agent(lambda request: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    services = api_services(library, threads=threads, agent=agent)
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [thread] = threads.threads.values()

    assert client.delete(f"/documents/{doc}", headers=A).status_code == 204

    listed = client.get(f"/threads/{thread.thread_id}/documents", headers=A).json()
    assert [(d["title"], d["deleted"]) for d in listed] == [(title, True)]
    assert client.get(f"/threads/{thread.thread_id}/documents", headers=B).status_code == 404

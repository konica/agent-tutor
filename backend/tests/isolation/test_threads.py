"""US-12: each learner's POST /threads starts a thread owned by that learner; no one else can get it, its
documents used (GET /threads/{id}/documents), its turns (GET /threads/{id}/turns), or rename it (PATCH
/threads/{id}), or rate one of its turns (PUT /threads/{id}/turns/{run_id}/rating); GET /threads lists only the
caller's own threads. A thread starts from a document only if it is the learner's own ready, active one."""

import json

import httpx
from fastapi.testclient import TestClient

from fakes import (
    FakeAnswerFeedback,
    FakeObjectStore,
    FakeTokenVerifier,
    FixedClock,
    InMemoryLibrary,
    InMemorySubjects,
    InMemoryThreads,
    api_services,
    fake_agent,
    ingest_ready,
)
from fakes.parameters import APP_TZ, TEST_LIMITS, TEST_UPLOAD_LIMITS
from smart_tutor.apps.api.main import create_app
from smart_tutor.knowledge.application import UploadService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import DocumentId, SubjectId, ThreadId, UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.tutoring.application import Rating

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}
SHARED = SubjectId("00000000-0000-4000-8000-0000000000aa")
ANSWER = b'event: delta\ndata: {"text": "Hi"}\n\nevent: done\ndata: {}\n\n'


def answers(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=ANSWER, headers={"content-type": "text/event-stream"})


def learners() -> FakeTokenVerifier:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    return verifier


def test_each_learner_starts_their_own_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    services = api_services(library, threads=threads, agent=fake_agent(answers))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))

    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [a_thread] = threads.threads.values()
    assert a_thread.user_id == "learner-a"

    assert client.post("/threads", json={"question": "What is attention?"}, headers=B).status_code == 200
    [b_thread] = [t for t in threads.threads.values() if t.thread_id != a_thread.thread_id]
    assert b_thread.user_id == "learner-b"

    assert threads.get_owned(ThreadId(a_thread.thread_id), UserId("learner-b")) is None
    assert threads.get_owned(ThreadId(b_thread.thread_id), UserId("learner-a")) is None


def test_only_the_owner_lists_a_threads_documents_used() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    a_document = ingest_ready(library, "learner-a", "Attention weighs tokens.")
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    a_title = library.state.documents[a_document].file_name
    body = (
        b'event: delta\ndata: {"text": "Hi"}\n\n'
        + f'event: sources\ndata: {{"document_ids": ["{a_document}"]}}\n\n'.encode()
        + b"event: done\ndata: {}\n\n"
    )
    agent = fake_agent(lambda request: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    services = api_services(library, threads=threads, agent=agent)
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))

    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [thread] = threads.threads.values()

    mine = client.get(f"/threads/{thread.thread_id}/documents", headers=A)
    assert [d["document_id"] for d in mine.json()] == [a_document]
    theirs = client.get(f"/threads/{thread.thread_id}/documents", headers=B)
    assert theirs.status_code == 404
    assert a_title not in theirs.text and a_document not in theirs.text


def test_only_the_owner_renames_a_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    services = api_services(library, threads=threads, agent=fake_agent(answers))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [thread] = threads.threads.values()

    theirs = client.patch(f"/threads/{thread.thread_id}", json={"title": "Taken over"}, headers=B)

    assert theirs.status_code == 404
    assert "What is attention?" not in theirs.text
    assert threads.threads[thread.thread_id].title == "What is attention?"
    mine = client.patch(f"/threads/{thread.thread_id}", json={"title": "Attention basics"}, headers=A)
    assert mine.status_code == 200 and threads.threads[thread.thread_id].title == "Attention basics"


def test_a_learner_without_documents_asks_with_their_own_token_even_when_another_has_documents() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.", subject_ids=(SHARED,))
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers(request)

    services = api_services(library, threads=threads, agent=fake_agent(record))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))

    response = client.post("/threads", json={"question": "What is attention?"}, headers=B)

    # The agent searches as B (MCP's can_read gives B an empty readable set); the thread is B's, never A's.
    assert response.status_code == 200
    assert [r.headers["authorization"] for r in seen] == ["Bearer token-b"]
    [thread] = threads.threads.values()
    assert thread.user_id == "learner-b"


def test_a_citation_to_another_learners_document_never_resolves() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    b_document = ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    citation = {"n": 1, "chunk_id": "c1", "document_id": str(b_document), "document_title": "B's paper", "page": 1}
    body = (
        b'event: delta\ndata: {"text": "Hi [1]"}\n\n'
        + f"event: citations\ndata: {json.dumps({'citations': [citation]})}\n\n".encode()
        + b"event: done\ndata: {}\n\n"
    )
    agent = fake_agent(lambda request: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    services = api_services(library, threads=threads, agent=agent)
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [thread] = threads.threads.values()

    [turn] = client.get(f"/threads/{thread.thread_id}/turns", headers=A).json()

    # Resolved through A's library only: B's document reads as gone, with none of its title or state.
    assert turn["citations"][0]["document_title"] == "Deleted document"
    assert turn["citations"][0]["deleted"] is True and turn["citations"][0]["archived"] is False
    assert library.state.documents[b_document].file_name not in json.dumps(turn)


def _client_with_thread() -> tuple[TestClient, InMemoryLibrary, DocumentId, str]:
    """Learner A has one ready document and a thread whose answer used it."""
    library, threads = InMemoryLibrary(), InMemoryThreads()
    a_document = ingest_ready(library, "learner-a", "Attention weighs tokens.")
    body = (
        b'event: delta\ndata: {"text": "Hi"}\n\n'
        + f'event: sources\ndata: {{"document_ids": ["{a_document}"]}}\n\n'.encode()
        + b"event: done\ndata: {}\n\n"
    )
    agent = fake_agent(lambda request: httpx.Response(200, content=body, headers={"content-type": "text/event-stream"}))
    services = api_services(library, threads=threads, agent=agent)
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [thread] = threads.threads.values()
    return client, library, a_document, thread.thread_id


def test_a_learner_can_add_only_their_own_ready_active_documents() -> None:
    client, library, listed, thread_id = _client_with_thread()
    url = f"/threads/{thread_id}/documents"
    b_document = ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    b_title = library.state.documents[b_document].file_name
    a_ready = ingest_ready(library, "learner-a", "Backpropagation applies the chain rule.")
    a_archived = ingest_ready(library, "learner-a", "Dropout regularises networks.")
    library.state.documents[a_archived].archived = True
    upload = UploadService(
        library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ
    )
    a_processing = upload.start_upload(UserId("learner-a"), "processing.pdf").document_id  # never made ready

    def listed_ids() -> list[str]:
        return [d["document_id"] for d in client.get(url, headers=A).json()]

    foreign = client.post(url, json={"document_ids": [b_document]}, headers=A)
    assert foreign.status_code == 404
    assert b_title not in foreign.text and b_document not in foreign.text
    assert client.post(url, json={"document_ids": [a_ready, b_document]}, headers=A).status_code == 404
    assert listed_ids() == [listed]  # all-or-nothing: A's own ready one was not added
    assert client.post(url, json={"document_ids": [a_archived]}, headers=A).status_code == 404
    assert client.post(url, json={"document_ids": [a_processing]}, headers=A).status_code == 404
    assert listed_ids() == [listed]

    assert client.post(url, json={"document_ids": [a_ready]}, headers=A).status_code == 200
    assert listed_ids() == [listed, a_ready]


def test_only_the_owner_adds_or_removes_a_threads_documents() -> None:
    client, library, a_document, thread_id = _client_with_thread()
    url = f"/threads/{thread_id}/documents"
    b_document = ingest_ready(library, "learner-b", "Gradient descent follows the slope.")

    added = client.post(url, json={"document_ids": [b_document]}, headers=B)
    removed = client.delete(f"{url}/{a_document}", headers=B)

    assert added.status_code == 404 and removed.status_code == 404
    assert [d["document_id"] for d in client.get(url, headers=A).json()] == [a_document]


def test_only_the_owner_reads_limits_or_asks_in_a_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    seen: list[httpx.Request] = []

    def agent_called(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers(request)

    services = api_services(library, threads=threads, agent=fake_agent(agent_called))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [thread] = threads.threads.values()
    url = f"/threads/{thread.thread_id}"
    seen.clear()

    # B has no documents either: ownership is checked first, so B gets 404, not 409.
    assert client.get(url, headers=B).status_code == 404
    assert client.patch(url, json={"search_scope": "listed"}, headers=B).status_code == 404
    assert client.post(f"{url}/questions", json={"question": "Hi"}, headers=B).status_code == 404

    assert seen == []
    assert threads.threads[thread.thread_id].search_scope == "library"
    assert client.get(url, headers=A).status_code == 200


def test_a_learner_starts_a_thread_only_from_their_own_ready_document() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    a_ready = ingest_ready(library, "learner-a", "Attention weighs tokens.")
    b_document = ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    b_title = library.state.documents[b_document].file_name
    a_archived = ingest_ready(library, "learner-a", "Dropout regularises networks.")
    library.state.documents[a_archived].archived = True
    upload = UploadService(
        library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS, rate=TEST_UPLOAD_LIMITS, time_zone=APP_TZ
    )
    a_processing = upload.start_upload(UserId("learner-a"), "processing.pdf").document_id  # never made ready
    seen: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return answers(request)

    services = api_services(library, threads=threads, agent=fake_agent(recording))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    question = {"question": "What is attention?"}

    foreign = client.post("/threads", json={**question, "document_id": b_document}, headers=A)
    assert foreign.status_code == 404
    assert b_title not in foreign.text and b_document not in foreign.text
    assert client.post("/threads", json={**question, "document_id": a_archived}, headers=A).status_code == 404
    assert client.post("/threads", json={**question, "document_id": a_processing}, headers=A).status_code == 404
    assert seen == [] and threads.threads == {}  # the agent was never called and no thread started

    assert client.post("/threads", json={**question, "document_id": a_ready}, headers=A).status_code == 200
    [thread] = threads.threads.values()
    listed = client.get(f"/threads/{thread.thread_id}/documents", headers=A).json()
    assert [d["document_id"] for d in listed] == [a_ready]


def test_only_the_owner_reads_a_threads_turns() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    services = api_services(library, threads=threads, agent=fake_agent(answers))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [thread] = threads.threads.values()

    mine = client.get(f"/threads/{thread.thread_id}/turns", headers=A)
    theirs = client.get(f"/threads/{thread.thread_id}/turns", headers=B)

    assert [t["question"] for t in mine.json()] == ["What is attention?"]
    assert theirs.status_code == 404 and theirs.json() == {"detail": "Conversation not found"}
    assert threads.turns(ThreadId(thread.thread_id), UserId("learner-b")) == []


def test_each_learner_lists_only_their_own_threads() -> None:
    """Two learners sharing a subject and the same uploaded file each list only their own threads."""
    library, threads = InMemoryLibrary(), InMemoryThreads()
    same_text = "Attention weighs tokens."
    documents = {
        "token-a": ingest_ready(library, "learner-a", same_text, subject_ids=[SHARED]),
        "token-b": ingest_ready(library, "learner-b", same_text, subject_ids=[SHARED]),
    }

    def own_document_answer(request: httpx.Request) -> httpx.Response:
        # The agent receives the caller's own token; its `sources` names that learner's document.
        document = documents[request.headers["authorization"].removeprefix("Bearer ")]
        body = (
            b'event: delta\ndata: {"text": "Hi"}\n\n'
            + f'event: sources\ndata: {{"document_ids": ["{document}"]}}\n\n'.encode()
            + b"event: done\ndata: {}\n\n"
        )
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    catalog = InMemorySubjects({SHARED: "Shared"})
    services = api_services(library, threads=threads, catalog=catalog, agent=fake_agent(own_document_answer))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    assert client.post("/threads", json={"question": "What is attention?"}, headers=B).status_code == 200
    owned = {t.user_id: t.thread_id for t in threads.threads.values()}

    a_list, b_list = client.get("/threads", headers=A).json(), client.get("/threads", headers=B).json()

    for listed, owner in ((a_list, "learner-a"), (b_list, "learner-b")):
        [row] = listed
        assert row["thread_id"] == owned[owner]
        assert row["subjects"] == [{"subject_id": SHARED, "name": "Shared"}] and row["documents"] == 1
    assert a_list[0]["thread_id"] != b_list[0]["thread_id"]


def test_only_the_owner_rates_a_turn() -> None:
    library, threads, feedback = InMemoryLibrary(), InMemoryThreads(), FakeAnswerFeedback()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    services = api_services(library, threads=threads, agent=fake_agent(answers), feedback=feedback)
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    assert client.post("/threads", json={"question": "What is descent?"}, headers=B).status_code == 200
    [a_turn] = [t for t in threads.turn_rows if t.user_id == "learner-a"]
    [b_turn] = [t for t in threads.turn_rows if t.user_id == "learner-b"]

    # B on A's thread and run, and B's own thread with A's run: both 404, nothing changes or is sent.
    theirs = client.put(f"/threads/{a_turn.thread_id}/turns/{a_turn.run_id}/rating", json={"rating": "down"}, headers=B)
    mixed = client.put(f"/threads/{b_turn.thread_id}/turns/{a_turn.run_id}/rating", json={"rating": "down"}, headers=B)

    assert theirs.status_code == 404 and mixed.status_code == 404
    assert "What is attention?" not in theirs.text + mixed.text
    assert all(t.rating is None for t in threads.turn_rows)
    assert feedback.sent == []
    mine = client.put(f"/threads/{a_turn.thread_id}/turns/{a_turn.run_id}/rating", json={"rating": "up"}, headers=A)
    assert mine.status_code == 200 and feedback.sent == [(a_turn.run_id, Rating.UP)]

"""US-12: each learner's POST /threads starts a thread owned by that learner; no one else can get it."""

import httpx
from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier, InMemoryLibrary, InMemoryThreads, api_services, fake_agent, ingest_ready
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.shared.domain.principal import Principal

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


def test_a_learner_without_documents_starts_no_thread_even_when_another_has_documents_in_their_subject() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.", subject_ids=(SHARED,))
    services = api_services(library, threads=threads, agent=fake_agent(answers))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))

    response = client.post("/threads", json={"question": "What is attention?"}, headers=B)

    assert response.status_code == 409
    assert threads.threads == {}

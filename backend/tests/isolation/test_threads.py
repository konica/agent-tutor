"""US-12: each learner's POST /threads starts a thread owned by that learner; no one else can get it."""

from collections.abc import Callable

import httpx
from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier, InMemoryLibrary, InMemoryThreads, api_services, fake_agent, ingest_ready
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.shared.domain.principal import Principal

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}
GENERAL = "00000000-0000-4000-8000-000000000001"
A_ONLY = "00000000-0000-4000-8000-0000000000aa"


def detects(subject_id: str) -> Callable[[httpx.Request], httpx.Response]:
    """An agent that detects `subject_id`, then answers."""
    sse = f'event: subjects\ndata: {{"subject_ids": ["{subject_id}"]}}\n\nevent: done\ndata: {{}}\n\n'.encode()
    return lambda request: httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})


def learners() -> FakeTokenVerifier:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    return verifier


def test_each_learner_starts_their_own_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    services = api_services(library, threads=threads, agent=fake_agent(detects(GENERAL)))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))

    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [a_thread] = threads.threads.values()
    assert a_thread.user_id == "learner-a"

    assert client.post("/threads", json={"question": "What is attention?"}, headers=B).status_code == 200
    [b_thread] = [t for t in threads.threads.values() if t.thread_id != a_thread.thread_id]
    assert b_thread.user_id == "learner-b"

    assert threads.get_owned(ThreadId(a_thread.thread_id), UserId("learner-b")) is None
    assert threads.get_owned(ThreadId(b_thread.thread_id), UserId("learner-a")) is None


def test_a_subject_only_another_learner_has_starts_no_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.", subject_ids=(SubjectId(A_ONLY),))
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    services = api_services(library, threads=threads, agent=fake_agent(detects(A_ONLY)))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))

    response = client.post("/threads", json={"question": "What is attention?"}, headers=B)

    assert response.status_code == 200 and "event: thread" not in response.text
    assert response.text.startswith("event: error\n")
    assert threads.threads == {}


def test_another_learner_cannot_read_or_resume_a_pending_thread() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    seen: list[httpx.Request] = []

    def agent(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        sse = f'event: choose_subjects\ndata: {{"subject_ids": ["{GENERAL}"]}}\n\nevent: done\ndata: {{}}\n\n'
        return httpx.Response(200, content=sse.encode(), headers={"content-type": "text/event-stream"})

    services = api_services(library, threads=threads, agent=fake_agent(agent))
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    client.post("/threads", json={"question": "Secret question of A"}, headers=A)
    [thread] = threads.threads.values()
    calls = len(seen)

    read = client.get(f"/threads/{thread.thread_id}", headers=B)
    resume = client.post(f"/threads/{thread.thread_id}/subjects", json={"subject_ids": [GENERAL]}, headers=B)

    assert read.status_code == 404 and "Secret question" not in read.text
    assert resume.status_code == 404 and "Secret question" not in resume.text
    assert len(seen) == calls  # the agent was never called
    assert threads.threads[thread.thread_id].awaiting_subjects

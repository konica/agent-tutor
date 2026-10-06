"""US-12: each learner's POST /threads starts a thread owned by that learner; no one else can get it."""

import httpx
from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier, InMemoryLibrary, InMemoryThreads, api_services, fake_agent, ingest_ready
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import ThreadId, UserId
from smart_tutor.shared.domain.principal import Principal

A = {"Authorization": "Bearer token-a"}
B = {"Authorization": "Bearer token-b"}


def done(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=b"event: done\ndata: {}\n\n", headers={"content-type": "text/event-stream"})


def test_each_learner_starts_their_own_thread() -> None:
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "A", frozenset({"learner"})))
    verifier.add("token-b", Principal(UserId("learner-b"), "B", frozenset({"learner"})))
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    services = api_services(library, threads=threads, agent=fake_agent(done))
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))

    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    [a_thread] = threads.threads.values()
    assert a_thread.user_id == "learner-a"

    assert client.post("/threads", json={"question": "What is attention?"}, headers=B).status_code == 200
    [b_thread] = [t for t in threads.threads.values() if t.thread_id != a_thread.thread_id]
    assert b_thread.user_id == "learner-b"

    assert threads.get_owned(ThreadId(a_thread.thread_id), UserId("learner-b")) is None
    assert threads.get_owned(ThreadId(b_thread.thread_id), UserId("learner-a")) is None

"""POST /threads: start a thread, forward the same token to the agent, relay its SSE stream."""

import json
from collections.abc import AsyncIterator, Callable

import httpx
from fastapi.testclient import TestClient

from fakes import FakeTokenVerifier, InMemoryLibrary, InMemoryThreads, api_services, fake_agent, ingest_ready
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal

AUTH = {"Authorization": "Bearer t-ada"}
QUESTION = {"question": "What is attention?"}
UNAVAILABLE = "The tutor is unavailable. Try again in a moment."

AGENT_SSE = (
    b'event: delta\ndata: {"text": "It weighs "}\n\n'
    b'event: delta\ndata: {"text": "tokens [1]."}\n\n'
    b'event: citations\ndata: {"citations": [{"chunk_id": "c1", "document_title": "a.pdf", "page": 3}]}\n\n'
    b"event: done\ndata: {}\n\n"
)

Handler = Callable[[httpx.Request], httpx.Response]


def sse_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=AGENT_SSE, headers={"content-type": "text/event-stream"})


def setup(
    handler: Handler = sse_ok, ready_document: bool = True
) -> tuple[TestClient, InMemoryThreads, FakeTokenVerifier]:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library, threads = InMemoryLibrary(), InMemoryThreads()
    if ready_document:
        ingest_ready(library, "ada", "Attention weighs tokens.")
    services = api_services(library, threads=threads, agent=fake_agent(handler))
    return TestClient(create_app(Settings(), verifier=verifier, services=services)), threads, verifier


def recording(seen: list[httpx.Request], handler: Handler = sse_ok) -> Handler:
    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    return record


def test_starts_a_thread_and_relays_the_agents_stream_after_a_thread_event() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    [thread] = threads.threads.values()
    assert thread.user_id == "ada"
    first, rest = response.text.split("\n\n", 1)
    assert first.startswith("event: thread\n") and thread.thread_id in first and '"name": "General"' in first
    assert json.loads(first.split("data: ", 1)[1]) == {
        "thread_id": thread.thread_id,
        "subjects": [{"subject_id": "00000000-0000-4000-8000-000000000001", "name": "General"}],
    }
    assert rest == AGENT_SSE.decode()
    [request] = seen
    assert request.url == "http://agent.test/ask"
    assert request.headers["authorization"] == "Bearer t-ada"  # the same token, forwarded (ADR 0007)
    assert json.loads(request.content) == {
        "question": "What is attention?",
        "subjects": [{"subject_id": "00000000-0000-4000-8000-000000000001", "name": "General"}],
    }
    assert "t-ada" not in request.content.decode()  # never in the body


def test_no_token_is_401_and_the_agent_is_never_called() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen))

    response = client.post("/threads", json=QUESTION)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert seen == [] and threads.threads == {}


def test_a_revoked_token_is_401() -> None:
    seen: list[httpx.Request] = []
    client, threads, verifier = setup(recording(seen))
    verifier.revoke("t-ada")

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 401
    assert seen == [] and threads.threads == {}


def test_a_token_the_agent_refuses_is_401() -> None:
    client, _, _ = setup(lambda request: httpx.Response(401, json={"detail": "Not authenticated"}))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_an_unreachable_agent_is_503() -> None:
    def unreachable(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    client, _, _ = setup(unreachable)

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE}


def test_an_agent_error_status_is_503() -> None:
    client, _, _ = setup(lambda request: httpx.Response(500, text="boom"))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 503
    assert response.json() == {"detail": UNAVAILABLE}


def test_no_ready_documents_is_409_before_any_thread_or_agent_call() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen), ready_document=False)

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 409
    assert response.json() == {"detail": "Upload a document first"}
    assert threads.threads == {} and seen == []


def test_an_unknown_body_field_is_422() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen))

    response = client.post("/threads", json={**QUESTION, "user_id": "bob"}, headers=AUTH)

    assert response.status_code == 422
    assert threads.threads == {} and seen == []


def test_an_empty_question_is_422() -> None:
    client, _, _ = setup()
    assert client.post("/threads", json={"question": ""}, headers=AUTH).status_code == 422


class _BreaksMidAnswer(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'event: delta\ndata: {"text": "It weighs "}\n\n'
        raise httpx.ReadError("connection reset")


def test_a_dropped_agent_stream_ends_with_an_unavailable_error_event() -> None:
    client, _, _ = setup(
        lambda request: httpx.Response(200, stream=_BreaksMidAnswer(), headers={"content-type": "text/event-stream"})
    )

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200
    assert 'event: delta\ndata: {"text": "It weighs "}\n\n' in response.text
    *_, last = response.text.rstrip("\n").split("\n\n")
    assert last.startswith("event: error\n")
    assert json.loads(last.split("data: ", 1)[1]) == {"code": "unavailable", "message": UNAVAILABLE}


def test_openapi_names_the_operation_and_declares_the_event_stream() -> None:
    client, _, _ = setup()
    operation = client.get("/openapi.json").json()["paths"]["/threads"]["post"]
    assert operation["operationId"] == "ask_in_new_thread"
    assert "text/event-stream" in operation["responses"]["200"]["content"]

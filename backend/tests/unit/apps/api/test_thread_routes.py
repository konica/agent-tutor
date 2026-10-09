"""POST /threads: start a thread, forward the same token to the agent, relay its SSE stream."""

import json
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import (
    FakeTokenVerifier,
    InMemoryLibrary,
    InMemoryThreads,
    api_services,
    fake_agent,
    ingest_ready,
)
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.tutoring.application import Thread

AUTH = {"Authorization": "Bearer t-ada"}
QUESTION = {"question": "What is attention?"}
UNAVAILABLE = "The tutor is unavailable. Try again in a moment."

AGENT_ANSWER = (
    b'event: delta\ndata: {"text": "It weighs "}\n\n'
    b'event: delta\ndata: {"text": "tokens [1]."}\n\n'
    b'event: citations\ndata: {"citations": [{"n": 1, "chunk_id": "c1", "document_title": "a.pdf", "page": 3}]}\n\n'
    b"event: done\ndata: {}\n\n"
)
Handler = Callable[[httpx.Request], httpx.Response]


def sse_ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, content=AGENT_ANSWER, headers={"content-type": "text/event-stream"})


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


def test_starts_a_thread_and_relays_the_agents_answer_after_a_thread_event() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache" and response.headers["x-accel-buffering"] == "no"
    [thread] = threads.threads.values()
    assert thread.user_id == "ada"
    first, rest = response.text.split("\n\n", 1)
    assert first.startswith("event: thread\n")
    assert json.loads(first.split("data: ", 1)[1]) == {"thread_id": thread.thread_id}
    assert rest == AGENT_ANSWER.decode()  # the agent's events follow, byte-identical
    [request] = seen
    assert request.url == "http://agent.test/ask"
    assert request.headers["authorization"] == "Bearer t-ada"  # the same token, forwarded (ADR 0007)
    assert json.loads(request.content) == {"question": "What is attention?"}
    assert "t-ada" not in request.content.decode()  # never in the body


def event_stream(content: bytes) -> Handler:
    return lambda request: httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})


def test_an_agent_error_first_is_relayed_and_starts_no_thread() -> None:
    error = b'event: error\ndata: {"code": "unavailable", "message": "x"}\n\n'
    client, threads, _ = setup(event_stream(error))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200 and response.text == error.decode()
    assert threads.threads == {}


@pytest.mark.parametrize("first", [b"", b'event: delta\ndata: {"text": "hi"', b'event: delta\ndata: {"text": "hi"}\n'])
def test_a_stream_that_ends_before_a_complete_event_is_unavailable_and_starts_no_thread(first: bytes) -> None:
    client, threads, _ = setup(event_stream(first))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.text == UNAVAILABLE_EVENT
    assert threads.threads == {}


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


def test_a_whitespace_only_question_is_422_before_any_thread_or_agent_call() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen))

    response = client.post("/threads", json={"question": "   \n\t "}, headers=AUTH)

    assert response.status_code == 422
    assert threads.threads == {} and seen == []


def test_the_question_is_forwarded_stripped() -> None:
    seen: list[httpx.Request] = []
    client, _, _ = setup(recording(seen))

    client.post("/threads", json={"question": "  What is attention?\n"}, headers=AUTH)

    [request] = seen
    assert json.loads(request.content)["question"] == "What is attention?"


class _Chunks(httpx.AsyncByteStream):
    """Yields the given network reads, then raises `error` if one is given."""

    def __init__(self, *reads: bytes, error: Exception | None = None) -> None:
        self._reads = reads
        self._error = error

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for read in self._reads:
            yield read
        if self._error is not None:
            raise self._error


def streaming(stream: httpx.AsyncByteStream) -> Handler:
    return lambda request: httpx.Response(200, stream=stream, headers={"content-type": "text/event-stream"})


def test_events_split_across_reads_are_relayed_byte_identical() -> None:
    reads = [AGENT_ANSWER[i : i + 7] for i in range(0, len(AGENT_ANSWER), 7)]  # reads cut events anywhere
    client, _, _ = setup(streaming(_Chunks(*reads)))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.text.split("\n\n", 1)[1] == AGENT_ANSWER.decode()


def test_a_first_event_split_across_reads_starts_the_thread() -> None:
    cut = 10
    client, threads, _ = setup(streaming(_Chunks(AGENT_ANSWER[:cut], AGENT_ANSWER[cut:])))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    [thread] = threads.threads.values()
    first, rest = response.text.split("\n\n", 1)
    assert first.startswith("event: thread\n") and thread.thread_id in first
    assert rest == AGENT_ANSWER.decode()


def test_a_stream_dropped_inside_an_event_ends_with_a_well_formed_error_event() -> None:
    client, _, _ = setup(
        streaming(
            _Chunks(
                b'event: delta\ndata: {"text": "It weighs "}\n\n',
                b'event: delta\ndata: {"text": "half',  # half an event, then the connection drops
                error=httpx.ReadError("connection reset"),
            )
        )
    )

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200
    events = response.text.split("\n\n")
    assert events[-1] == ""  # the body ends on an event boundary
    thread, delta, error = events[:-1]
    assert thread.startswith("event: thread\n")
    assert delta == 'event: delta\ndata: {"text": "It weighs "}'  # the partial event is dropped
    event, data = error.split("\n")
    assert event == "event: error"
    assert json.loads(data.removeprefix("data: ")) == {"code": "unavailable", "message": UNAVAILABLE}
    assert "half" not in response.text


def test_a_stream_that_ends_inside_an_event_ends_with_an_error_event_instead() -> None:
    complete_then_half = b'event: delta\ndata: {"text": "It weighs "}\n\nevent: delta\ndata: {"text": "half'
    client, _, _ = setup(streaming(_Chunks(complete_then_half)))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    *_, delta, error, end = response.text.split("\n\n")
    assert end == "" and delta == 'event: delta\ndata: {"text": "It weighs "}'
    assert error.startswith("event: error\n") and '"code": "unavailable"' in error
    assert "half" not in response.text


class _BreaksMidAnswer(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b'event: delta\ndata: {"text": "It weighs "}\n\n'
        raise httpx.ReadError("connection reset")


UNAVAILABLE_EVENT = f"event: error\ndata: {json.dumps({'code': 'unavailable', 'message': UNAVAILABLE})}\n\n"


class _FailingThreads(InMemoryThreads):
    def add(self, thread: Thread) -> None:
        raise RuntimeError("database down")


def test_a_failure_starting_the_thread_ends_the_stream_with_an_unavailable_error_event() -> None:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention weighs tokens.")
    services = api_services(library, threads=_FailingThreads(), agent=fake_agent(sse_ok))
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200 and response.text == UNAVAILABLE_EVENT


def test_a_stream_dropped_inside_the_first_event_is_unavailable_and_starts_no_thread() -> None:
    dropped = _Chunks(b'event: delta\ndata: {"te', error=httpx.ReadError("connection reset"))
    client, threads, _ = setup(streaming(dropped))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.text == UNAVAILABLE_EVENT and threads.threads == {}


def test_an_archived_only_learner_is_409_before_any_agent_call() -> None:
    seen: list[httpx.Request] = []
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library, threads = InMemoryLibrary(), InMemoryThreads()
    document_id = ingest_ready(library, "ada", "Attention weighs tokens.")
    library.state.documents[document_id].archived = True
    services = api_services(library, threads=threads, agent=fake_agent(recording(seen)))
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 409 and response.json() == {"detail": "Upload a document first"}
    assert threads.threads == {} and seen == []


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

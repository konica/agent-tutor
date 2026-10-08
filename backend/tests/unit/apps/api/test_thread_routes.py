"""POST /threads: start a thread, forward the same token to the agent, relay its SSE stream."""

import json
import logging
from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from fakes import (
    FakeTokenVerifier,
    FixedClock,
    InMemoryLibrary,
    InMemorySubjects,
    InMemoryThreads,
    api_services,
    fake_agent,
    ingest_ready,
)
from smart_tutor.apps.api.main import create_app
from smart_tutor.apps.api.services import ApiServices
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.subjects.application import SubjectNames
from smart_tutor.tutoring.application import Thread

AUTH = {"Authorization": "Bearer t-ada"}
QUESTION = {"question": "What is attention?"}
UNAVAILABLE = "The tutor is unavailable. Try again in a moment."

GENERAL = "00000000-0000-4000-8000-000000000001"
S2 = "00000000-0000-4000-8000-000000000002"

SUBJECTS_EVENT = b'event: subjects\ndata: {"subject_ids": ["00000000-0000-4000-8000-000000000001"]}\n\n'
AGENT_ANSWER = (
    b'event: delta\ndata: {"text": "It weighs "}\n\n'
    b'event: delta\ndata: {"text": "tokens [1]."}\n\n'
    b'event: citations\ndata: {"citations": [{"n": 1, "chunk_id": "c1", "document_title": "a.pdf", "page": 3}]}\n\n'
    b"event: done\ndata: {}\n\n"
)
AGENT_SSE = SUBJECTS_EVENT + AGENT_ANSWER

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


def test_starts_a_thread_and_relays_the_agents_answer_after_a_thread_event() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = setup(recording(seen))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache" and response.headers["x-accel-buffering"] == "no"
    [thread] = threads.threads.values()
    assert thread.user_id == "ada"
    first, rest = response.text.split("\n\n", 1)
    assert first.startswith("event: thread\n") and thread.thread_id in first and '"name": "General"' in first
    assert json.loads(first.split("data: ", 1)[1]) == {
        "thread_id": thread.thread_id,
        "subjects": [{"subject_id": "00000000-0000-4000-8000-000000000001", "name": "General"}],
    }
    assert rest == AGENT_ANSWER.decode()  # the agent's subjects event is replaced by the thread event
    [request] = seen
    assert request.url == "http://agent.test/ask"
    assert request.headers["authorization"] == "Bearer t-ada"  # the same token, forwarded (ADR 0007)
    sent = json.loads(request.content)
    assert sent.pop("thread_id") == thread.thread_id and thread.title == "What is attention?"
    assert sent == {
        "question": "What is attention?",
        "learner_subjects": [{"subject_id": "00000000-0000-4000-8000-000000000001", "name": "General"}],
    }
    assert "t-ada" not in request.content.decode()  # never in the body


def test_a_subject_without_a_name_is_sent_with_a_placeholder_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    seen: list[httpx.Request] = []
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention weighs tokens.")
    services = api_services(library, subjects=SubjectNames(InMemorySubjects({})), agent=fake_agent(recording(seen)))
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))
    caplog.set_level(logging.DEBUG)

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200
    unnamed = [{"subject_id": "00000000-0000-4000-8000-000000000001", "name": "Unnamed subject"}]
    assert json.loads(seen[0].content)["learner_subjects"] == unnamed
    [record] = [r for r in caplog.records if "placeholder" in r.getMessage()]
    assert record.levelno == logging.WARNING and "00000000-0000-4000-8000-000000000001" in record.getMessage()
    assert "t-ada" not in caplog.text


def event_stream(content: bytes) -> Handler:
    return lambda request: httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})


def test_the_thread_starts_with_the_subjects_the_agent_detected() -> None:
    # ada has General and S2; the agent gets both and detects both
    seen: list[httpx.Request] = []
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "ada", "Attention weighs tokens.")
    ingest_ready(library, "ada", "Language models predict tokens.", subject_ids=(SubjectId(S2),))
    catalog = InMemorySubjects({SubjectId(GENERAL): "General", SubjectId(S2): "LLMs"})
    detected = f'event: subjects\ndata: {{"subject_ids": ["{S2}", "{GENERAL}"]}}\n\n'.encode()
    agent = fake_agent(recording(seen, event_stream(detected + AGENT_ANSWER)))
    services = api_services(library, threads=threads, catalog=catalog, agent=agent)
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    [thread] = threads.threads.values()
    assert thread.subject_ids == (S2, GENERAL)  # the order the agent sent
    first, rest = response.text.split("\n\n", 1)
    assert json.loads(first.split("data: ", 1)[1])["subjects"] == [
        {"subject_id": S2, "name": "LLMs"},
        {"subject_id": GENERAL, "name": "General"},
    ]
    assert rest == AGENT_ANSWER.decode()
    assert json.loads(seen[0].content)["learner_subjects"] == [
        {"subject_id": GENERAL, "name": "General"},
        {"subject_id": S2, "name": "LLMs"},
    ]


def test_an_agent_error_before_subjects_is_relayed_and_starts_no_thread() -> None:
    error = b'event: error\ndata: {"code": "unavailable", "message": "x"}\n\n'
    client, threads, _ = setup(event_stream(error))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.status_code == 200 and response.text == error.decode()
    assert threads.threads == {}


def test_a_subject_the_learner_does_not_have_starts_no_thread(caplog: pytest.LogCaptureFixture) -> None:
    bad = b'event: subjects\ndata: {"subject_ids": ["00000000-0000-4000-8000-000000000099"]}\n\n' + AGENT_ANSWER
    client, threads, _ = setup(event_stream(bad))
    caplog.set_level(logging.DEBUG)

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.text == f"event: error\ndata: {json.dumps({'code': 'unavailable', 'message': UNAVAILABLE})}\n\n"
    assert threads.threads == {}
    assert "What is attention?" not in caplog.text and "t-ada" not in caplog.text


@pytest.mark.parametrize(
    "first",
    [
        b'event: delta\ndata: {"text": "hi"}\n\n',
        b"event: subjects\ndata: nope\n\n",
        b'event: subjects\ndata: {"subject_ids": "00000000-0000-4000-8000-000000000001"}\n\n',
        b'event: subjects\ndata: {"subject_ids": [1]}\n\n',
        b'event: subjects\ndata: {"subject_ids": []}\n\n',
        b"",
    ],
)
def test_a_stream_that_does_not_start_with_subjects_is_unavailable(first: bytes) -> None:
    client, threads, _ = setup(event_stream(first))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.text.endswith(f"data: {json.dumps({'code': 'unavailable', 'message': UNAVAILABLE})}\n\n")
    assert "event: thread" not in response.text and threads.threads == {}


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
    reads = [AGENT_SSE[i : i + 7] for i in range(0, len(AGENT_SSE), 7)]  # reads cut events anywhere
    client, _, _ = setup(streaming(_Chunks(*reads)))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.text.split("\n\n", 1)[1] == AGENT_ANSWER.decode()


def test_a_subjects_event_split_across_reads_starts_the_thread() -> None:
    cut = len(SUBJECTS_EVENT) // 2
    client, threads, _ = setup(streaming(_Chunks(AGENT_SSE[:cut], AGENT_SSE[cut:])))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    [thread] = threads.threads.values()
    first, rest = response.text.split("\n\n", 1)
    assert first.startswith("event: thread\n") and thread.thread_id in first
    assert rest == AGENT_ANSWER.decode()


def test_a_stream_dropped_inside_an_event_ends_with_a_well_formed_error_event() -> None:
    client, _, _ = setup(
        streaming(
            _Chunks(
                SUBJECTS_EVENT + b'event: delta\ndata: {"text": "It weighs "}\n\n',
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
    complete_then_half = (
        SUBJECTS_EVENT + b'event: delta\ndata: {"text": "It weighs "}\n\nevent: delta\ndata: {"text": "half'
    )
    client, _, _ = setup(streaming(_Chunks(complete_then_half)))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    *_, delta, error, end = response.text.split("\n\n")
    assert end == "" and delta == 'event: delta\ndata: {"text": "It weighs "}'
    assert error.startswith("event: error\n") and '"code": "unavailable"' in error
    assert "half" not in response.text


class _BreaksMidAnswer(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield SUBJECTS_EVENT + b'event: delta\ndata: {"text": "It weighs "}\n\n'
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


def test_a_stream_that_ends_inside_the_subjects_event_is_unavailable() -> None:
    client, threads, _ = setup(streaming(_Chunks(b'event: subjects\ndata: {"subj')))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.text == UNAVAILABLE_EVENT and threads.threads == {}


def test_a_stream_dropped_before_the_subjects_event_is_complete_is_unavailable() -> None:
    dropped = _Chunks(b'event: subjects\ndata: {"subj', error=httpx.ReadError("connection reset"))
    client, threads, _ = setup(streaming(dropped))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    assert response.text == UNAVAILABLE_EVENT and threads.threads == {}


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


S3 = "00000000-0000-4000-8000-000000000003"
DONE = "event: done\ndata: {}\n\n"
CHOOSE = f'event: choose_subjects\ndata: {{"subject_ids": ["{GENERAL}", "{S2}"]}}\n\n{DONE}'.encode()
CATALOG = {SubjectId(GENERAL): "General", SubjectId(S2): "LLMs"}


def two_subject_setup(
    handler: Handler, catalog: dict[SubjectId, str] = CATALOG
) -> tuple[TestClient, InMemoryThreads, ApiServices]:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "ada", "Attention weighs tokens.")
    ingest_ready(library, "ada", "Language models predict tokens.", subject_ids=(SubjectId(S2),))
    services = api_services(library, threads=threads, catalog=InMemorySubjects(catalog), agent=fake_agent(handler))
    return TestClient(create_app(Settings(), verifier=verifier, services=services)), threads, services


def open_pending(client: TestClient, threads: InMemoryThreads) -> str:
    response = client.post("/threads", json=QUESTION, headers=AUTH)
    assert response.text.startswith("event: choose_subjects\n")
    [thread] = threads.threads.values()
    return thread.thread_id


def resume_sse(*ids: str) -> bytes:
    return f'event: subjects\ndata: {{"subject_ids": {json.dumps(list(ids))}}}\n\n'.encode() + AGENT_ANSWER


def pick_handler(seen: list[httpx.Request], resume: Handler) -> Handler:
    """/ask is unsure; /resume is answered by `resume`."""

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/ask":
            return event_stream(CHOOSE)(request)
        return resume(request)

    return handle


def test_an_unsure_detection_stores_a_pending_thread_and_asks_the_learner_to_choose() -> None:
    client, threads, _ = two_subject_setup(event_stream(CHOOSE))

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    [thread] = threads.threads.values()
    assert thread.subject_ids == () and thread.awaiting_subjects and thread.title == "What is attention?"
    first, rest = response.text.split("\n\n", 1)
    assert first.startswith("event: choose_subjects\n")
    assert json.loads(first.split("data: ", 1)[1]) == {
        "thread_id": thread.thread_id,
        "question": "What is attention?",
        "subjects": [{"subject_id": GENERAL, "name": "General"}, {"subject_id": S2, "name": "LLMs"}],
    }
    assert rest == DONE


def test_a_choice_the_learner_does_not_have_is_left_out_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    odd = f'event: choose_subjects\ndata: {{"subject_ids": ["{GENERAL}", "{S3}"]}}\n\n{DONE}'
    client, _, _ = two_subject_setup(event_stream(odd.encode()))
    caplog.set_level(logging.DEBUG)

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    first = json.loads(response.text.split("\n\n", 1)[0].split("data: ", 1)[1])
    assert first["subjects"] == [{"subject_id": GENERAL, "name": "General"}]
    assert S3 in caplog.text and "What is attention?" not in caplog.text


def test_the_choices_are_listed_by_name_like_my_subjects() -> None:
    # By id, GENERAL comes first; by name (case-insensitive), "algebra" does.
    client, _, _ = two_subject_setup(event_stream(CHOOSE), {SubjectId(GENERAL): "Zoology", SubjectId(S2): "algebra"})

    response = client.post("/threads", json=QUESTION, headers=AUTH)

    first = json.loads(response.text.split("\n\n", 1)[0].split("data: ", 1)[1])
    assert first["subjects"] == [{"subject_id": S2, "name": "algebra"}, {"subject_id": GENERAL, "name": "Zoology"}]
    assert [s["subject_id"] for s in client.get("/me/subjects", headers=AUTH).json()] == [S2, GENERAL]


def test_resume_sends_the_pick_to_the_agent_binds_it_and_relays_the_answer() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = two_subject_setup(pick_handler(seen, event_stream(resume_sse(S2))))
    thread_id = open_pending(client, threads)

    response = client.post(f"/threads/{thread_id}/subjects", json={"subject_ids": [S2]}, headers=AUTH)

    assert response.status_code == 200 and response.headers["content-type"].startswith("text/event-stream")
    resume = seen[-1]
    assert resume.url == "http://agent.test/resume" and resume.headers["authorization"] == "Bearer t-ada"
    assert json.loads(resume.content) == {"thread_id": thread_id, "subject_ids": [S2]}
    first, rest = response.text.split("\n\n", 1)
    assert first.startswith("event: thread\n")
    assert json.loads(first.split("data: ", 1)[1]) == {
        "thread_id": thread_id,
        "subjects": [{"subject_id": S2, "name": "LLMs"}],
    }
    assert rest == AGENT_ANSWER.decode()
    assert threads.threads[thread_id].subject_ids == (S2,)


def agent_paths(seen: list[httpx.Request]) -> list[str]:
    return [r.url.path for r in seen]


@pytest.mark.parametrize(
    "ids",
    [[], [GENERAL, S2, S3, "x"], [S3], [S2, S2]],
    ids=["none", "four", "not-the-learners", "duplicates"],
)
def test_an_invalid_pick_is_422_and_the_agent_is_not_called(ids: list[str]) -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = two_subject_setup(pick_handler(seen, event_stream(resume_sse(S2))))
    thread_id = open_pending(client, threads)

    response = client.post(f"/threads/{thread_id}/subjects", json={"subject_ids": ids}, headers=AUTH)

    assert response.status_code == 422
    assert agent_paths(seen) == ["/ask"] and threads.threads[thread_id].awaiting_subjects


def test_resume_of_an_unknown_thread_is_404_and_the_agent_is_not_called() -> None:
    seen: list[httpx.Request] = []
    client, _, _ = two_subject_setup(pick_handler(seen, event_stream(resume_sse(S2))))

    response = client.post(f"/threads/{S3}/subjects", json={"subject_ids": [S2]}, headers=AUTH)

    assert response.status_code == 404 and seen == []


def test_resume_of_a_thread_id_that_is_not_a_uuid_is_422_and_the_agent_is_not_called() -> None:
    seen: list[httpx.Request] = []
    client, _, _ = two_subject_setup(pick_handler(seen, event_stream(resume_sse(S2))))

    response = client.post("/threads/nope/subjects", json={"subject_ids": [S2]}, headers=AUTH)

    assert response.status_code == 422 and seen == []


def test_resume_of_a_bound_thread_is_409_and_the_agent_is_not_called() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = two_subject_setup(pick_handler(seen, event_stream(resume_sse(S2))))
    thread_id = open_pending(client, threads)
    threads.threads[thread_id].subject_ids = (GENERAL,)

    response = client.post(f"/threads/{thread_id}/subjects", json={"subject_ids": [S2]}, headers=AUTH)

    assert response.status_code == 409
    assert agent_paths(seen) == ["/ask"] and threads.threads[thread_id].subject_ids == (GENERAL,)


def test_an_agent_with_nothing_waiting_is_409_for_the_learner_and_the_thread_stays_pending() -> None:
    seen: list[httpx.Request] = []
    client, threads, _ = two_subject_setup(
        pick_handler(seen, lambda request: httpx.Response(409, json={"detail": "nothing waits"}))
    )
    thread_id = open_pending(client, threads)

    response = client.post(f"/threads/{thread_id}/subjects", json={"subject_ids": [S2]}, headers=AUTH)

    assert response.status_code == 409 and threads.threads[thread_id].awaiting_subjects
    assert response.json() == {"detail": "This question can no longer be answered. Ask it again."}
    assert agent_paths(seen) == ["/ask", "/resume"]  # the agent was asked, and refused


def test_resume_without_ready_documents_is_409_and_the_agent_is_not_called() -> None:
    seen: list[httpx.Request] = []
    client, threads = setup(recording(seen), ready_document=False)[:2]
    threads.add(Thread.pending(ThreadId(S3), UserId("ada"), "What is attention?", FixedClock().now()))

    response = client.post(f"/threads/{S3}/subjects", json={"subject_ids": [GENERAL]}, headers=AUTH)

    assert response.status_code == 409 and response.json() == {"detail": "Upload a document first"}
    assert seen == [] and threads.threads[S3].awaiting_subjects


def test_an_agent_that_resumes_with_other_subjects_is_unavailable_and_binds_nothing() -> None:
    client, threads, _ = two_subject_setup(pick_handler([], event_stream(resume_sse(GENERAL))))
    thread_id = open_pending(client, threads)

    response = client.post(f"/threads/{thread_id}/subjects", json={"subject_ids": [S2]}, headers=AUTH)

    assert response.text == UNAVAILABLE_EVENT and threads.threads[thread_id].awaiting_subjects


def test_a_concurrent_resume_that_bound_first_is_unavailable_and_changes_nothing() -> None:
    holder: list[InMemoryThreads] = []
    thread_ids: list[str] = []

    def bound_meanwhile(request: httpx.Request) -> httpx.Response:
        holder[0].threads[thread_ids[0]].subject_ids = (GENERAL,)  # another resume got there first
        return event_stream(resume_sse(S2))(request)

    client, threads, _ = two_subject_setup(pick_handler([], bound_meanwhile))
    holder.append(threads)
    thread_ids.append(open_pending(client, threads))

    response = client.post(f"/threads/{thread_ids[0]}/subjects", json={"subject_ids": [S2]}, headers=AUTH)

    assert response.text == UNAVAILABLE_EVENT and threads.threads[thread_ids[0]].subject_ids == (GENERAL,)


def test_get_thread_reads_a_pending_thread() -> None:
    client, threads, _ = two_subject_setup(event_stream(CHOOSE))
    thread_id = open_pending(client, threads)

    response = client.get(f"/threads/{thread_id}", headers=AUTH)

    assert response.status_code == 200
    assert response.json() == {
        "thread_id": thread_id,
        "question": "What is attention?",
        "subjects": [],
        "awaiting_subjects": True,
    }


def test_get_thread_reads_a_bound_thread_with_named_subjects() -> None:
    client, threads, _ = two_subject_setup(event_stream(resume_sse(S2)))
    client.post("/threads", json=QUESTION, headers=AUTH)
    [thread_id] = threads.threads

    response = client.get(f"/threads/{thread_id}", headers=AUTH)

    assert response.json()["awaiting_subjects"] is False
    assert response.json()["subjects"] == [{"subject_id": S2, "name": "LLMs"}]


def test_get_unknown_thread_is_404() -> None:
    client, _, _ = two_subject_setup(event_stream(CHOOSE))
    assert client.get(f"/threads/{S3}", headers=AUTH).status_code == 404


def test_get_thread_with_an_id_that_is_not_a_uuid_is_422() -> None:
    client, _, _ = two_subject_setup(event_stream(CHOOSE))
    assert client.get("/threads/nope", headers=AUTH).status_code == 422

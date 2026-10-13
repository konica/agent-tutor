import dataclasses
import json
import logging
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from openinference.instrumentation.langchain import LangChainInstrumentor

from fakes import (
    FakeRetriever,
    FakeTokenVerifier,
    FakeTopicClassifier,
    PassingGuard,
    TrippingGuard,
    fake_chat_model,
)
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.server import create_app
from smart_tutor.shared.adapters.ask_tracing import PhoenixAskTracing
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.shared.ports.ask_tracing import AskRun, AskTrace, AskTracing, NoAskTrace, NoAskTracing
from smart_tutor.tutoring.application import GUARD_MESSAGE, OFF_TOPIC_DECLINE, Guard, GuardTrip, TopicClassifier
from smart_tutor.tutoring.domain.errors import RetrievalError
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

BODY = {"question": "What is attention?"}
AUTH = {"Authorization": "Bearer t-ada"}
CHUNK = RetrievedChunk("c1", "d1", "a.pdf", 3, "Attention weighs tokens.", 0.9)
NO_DOCUMENTS = "None of your documents can be used right now: they are all archived or deleted."


def client(
    retriever: FakeRetriever,
    reply: str = "It weighs tokens [1].",
    answer_floor: float = 0.3,
    guard: Guard | None = None,
    topic_classifier: TopicClassifier | None = None,
) -> tuple[TestClient, FakeTokenVerifier]:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    graph = build_graph(
        lambda token: retriever,
        fake_chat_model(AIMessage(reply)),
        answer_floor,
        guard=guard or PassingGuard(),
        topic_classifier=topic_classifier,
    )
    return TestClient(create_app(Settings(), verifier=verifier, graph=graph)), verifier


def events(body: str) -> list[tuple[str, dict[str, Any]]]:
    out = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


def test_streams_deltas_then_citations_then_done() -> None:
    c, _ = client(FakeRetriever([CHUNK]))
    response = c.post("/ask", json=BODY, headers=AUTH)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache" and response.headers["x-accel-buffering"] == "no"
    got = events(response.text)
    assert "".join(d["text"] for e, d in got if e == "delta") == "It weighs tokens [1]."
    assert len([e for e, _ in got if e == "delta"]) > 1  # streamed, not one block
    assert got[-3] == ("sources", {"document_ids": ["d1"]})
    assert got[-2] == (
        "citations",
        {"citations": [{"n": 1, "chunk_id": "c1", "document_id": "d1", "document_title": "a.pdf", "page": 3}]},
    )
    assert got[-1] == ("done", {})


def test_sources_names_the_distinct_documents_given_to_the_model_in_rank_order() -> None:
    chunks = [
        CHUNK,
        RetrievedChunk("c2", "d2", "b.pdf", 1, "Other text.", 0.8),
        RetrievedChunk("c3", "d1", "a.pdf", 4, "More attention.", 0.7),
    ]
    c, _ = client(FakeRetriever(chunks), reply="Both [1] and [2].")
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    names = [e for e, _ in got]
    assert set(names[:-3]) == {"delta"}
    assert names[-3:] == ["sources", "citations", "done"]
    assert got[-3][1] == {"document_ids": ["d1", "d2"]}
    assert [c["document_id"] for c in got[-2][1]["citations"]] == ["d1", "d2"]


def test_the_stream_starts_with_a_delta_and_has_no_subjects_event() -> None:
    c, _ = client(FakeRetriever([CHUNK]))
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    assert got[0][0] == "delta"
    assert "subjects" not in [e for e, _ in got]


def test_a_retrieval_failure_is_the_only_event() -> None:
    c, _ = client(FakeRetriever(error=RetrievalError("down")))
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    assert got == [
        ("error", {"code": "unavailable", "message": "The tutor couldn't answer right now. Try again in a moment."})
    ]


def test_citations_carry_the_marker_number_the_answer_uses() -> None:
    other = RetrievedChunk("c2", "d2", "b.pdf", None, "Other text.", 0.8)
    c, _ = client(FakeRetriever([CHUNK, other]), reply="Only the second [2].")
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    assert got[-2] == (
        "citations",
        {"citations": [{"n": 2, "chunk_id": "c2", "document_id": "d2", "document_title": "b.pdf", "page": None}]},
    )


def test_an_empty_readable_set_streams_the_upload_request_without_calling_the_model() -> None:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    graph = build_graph(
        lambda token: FakeRetriever([]), fake_chat_model(), 0.3, guard=PassingGuard()
    )  # no replies: any model call fails
    c = TestClient(create_app(Settings(), verifier=verifier, graph=graph))
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    assert got == [("decline", {"code": "no_documents", "message": NO_DOCUMENTS}), ("done", {})]


def test_a_token_refused_mid_turn_ends_with_an_unauthenticated_error() -> None:
    c, _ = client(FakeRetriever(error=UnauthenticatedError("refused")))
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    assert got[-1][0] == "error" and got[-1][1]["code"] == "unauthenticated"
    assert "done" not in [e for e, _ in got]


def test_a_retrieval_failure_ends_with_an_unavailable_error(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    c, _ = client(FakeRetriever(error=RetrievalError("down")))
    text = c.post("/ask", json=BODY, headers=AUTH).text
    got = events(text)
    assert got[-1][0] == "error" and got[-1][1]["code"] == "unavailable"
    assert "done" not in [e for e, _ in got]
    assert "t-ada" not in text
    assert "t-ada" not in caplog.text


def test_no_token_or_revoked_token_is_401() -> None:
    c, verifier = client(FakeRetriever([CHUNK]))
    missing = c.post("/ask", json=BODY)
    assert missing.status_code == 401 and missing.headers["WWW-Authenticate"] == "Bearer"
    assert c.post("/ask", json=BODY, headers={"Authorization": "Basic dXNlcjpwdw=="}).status_code == 401
    verifier.revoke("t-ada")
    assert c.post("/ask", json=BODY, headers=AUTH).status_code == 401


def test_rejects_bad_bodies() -> None:
    c, _ = client(FakeRetriever([CHUNK]))
    assert c.post("/ask", json={**BODY, "question": ""}, headers=AUTH).status_code == 422
    assert c.post("/ask", json={**BODY, "question": "x" * 4001}, headers=AUTH).status_code == 422
    old = {**BODY, "learner_subjects": [{"subject_id": "s1", "name": "General"}]}
    assert c.post("/ask", json=old, headers=AUTH).status_code == 422


def test_healthz_is_public() -> None:
    c, _ = client(FakeRetriever([]))
    assert c.get("/healthz").json() == {"status": "ok"}


def test_startup_fails_without_a_client_secret() -> None:
    with (
        pytest.raises(RuntimeError, match="SMART_TUTOR_KEYCLOAK_CLIENT_SECRET"),
        TestClient(create_app(Settings(keycloak_client_secret=""))),
    ):
        pass


def test_document_ids_go_to_the_search_and_a_covered_question_is_answered() -> None:
    retriever = FakeRetriever([CHUNK])
    c, _ = client(retriever)
    body = c.post("/ask", json={"question": "q", "document_ids": ["d1"]}, headers=AUTH).text
    names = [name for name, _ in events(body)]
    assert retriever.calls == [("q", 5, ["d1"])]
    assert names[-1] == "done" and "delta" in names and "decline" not in names


def test_a_limited_search_with_nothing_readable_anywhere_streams_the_upload_request() -> None:
    c, _ = client(FakeRetriever([]))
    body = c.post("/ask", json={"question": "q", "document_ids": ["d1"]}, headers=AUTH).text
    assert events(body) == [("decline", {"code": "no_documents", "message": NO_DOCUMENTS}), ("done", {})]


class _ListedUnreadable(FakeRetriever):
    async def search(self, query: str, k: int = 5, document_ids: Sequence[str] | None = None) -> list[RetrievedChunk]:
        found = await super().search(query, k, document_ids)
        return [] if document_ids is not None else found


def test_a_limited_search_whose_listed_documents_cant_be_read_declines_as_limited() -> None:
    c, _ = client(_ListedUnreadable([CHUNK]))
    body = c.post("/ask", json={"question": "q", "document_ids": ["d1"]}, headers=AUTH).text
    assert events(body) == [
        ("decline", {"code": "limited", "message": "These documents don't cover this."}),
        ("done", {}),
    ]


def test_a_limited_search_below_the_floor_declines_without_calling_the_model() -> None:
    weak = dataclasses.replace(CHUNK, score=0.1)
    retriever = FakeRetriever([weak])
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    graph = build_graph(
        lambda token: retriever, fake_chat_model(), 0.3, guard=PassingGuard()
    )  # no replies: any model call fails
    c = TestClient(create_app(Settings(), verifier=verifier, graph=graph))
    body = c.post("/ask", json={"question": "q", "document_ids": ["d1"]}, headers=AUTH).text
    assert [name for name, _ in events(body)] == ["decline", "done"]


def test_without_document_ids_the_whole_library_is_searched_and_never_declined() -> None:
    retriever = FakeRetriever([dataclasses.replace(CHUNK, score=0.1)])
    c, _ = client(retriever, answer_floor=0.3)
    names = [name for name, _ in events(c.post("/ask", json={"question": "q"}, headers=AUTH).text)]
    assert retriever.calls == [("q", 5, None)] and "decline" not in names


def test_more_than_200_document_ids_are_refused() -> None:
    c, _ = client(FakeRetriever([CHUNK]))
    ids = [f"d{i}" for i in range(201)]
    assert c.post("/ask", json={"question": "q", "document_ids": ids}, headers=AUTH).status_code == 422


def test_startup_refuses_tracing_without_a_learner_hash_key() -> None:
    settings = Settings(keycloak_client_secret="s", learner_hash_key="", phoenix_url="http://127.0.0.1:9")
    with pytest.raises(RuntimeError, match="SMART_TUTOR_LEARNER_HASH_KEY"), TestClient(create_app(settings)):
        pass


def test_without_a_phoenix_url_the_agent_starts_untraced(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("smart_tutor.apps.agent.server.keycloak_verifier", lambda settings, http: FakeTokenVerifier())
    graph = build_graph(lambda token: FakeRetriever([CHUNK]), fake_chat_model(AIMessage("x")), guard=PassingGuard())
    app = create_app(Settings(keycloak_client_secret="s"), graph=graph)
    with TestClient(app):
        assert isinstance(app.state.tracing, NoAskTracing)


def test_with_a_phoenix_url_the_agent_starts_traced_and_stops_instrumenting_on_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("smart_tutor.apps.agent.server.keycloak_verifier", lambda settings, http: FakeTokenVerifier())
    graph = build_graph(lambda token: FakeRetriever([CHUNK]), fake_chat_model(AIMessage("x")), guard=PassingGuard())
    settings = Settings(
        keycloak_client_secret="s", learner_hash_key="k", phoenix_url="http://127.0.0.1:9"
    )  # nothing listens on :9, and no ask is made
    app = create_app(settings, graph=graph)
    with TestClient(app):
        assert isinstance(app.state.tracing, PhoenixAskTracing)
        assert LangChainInstrumentor().is_instrumented_by_opentelemetry
    assert not LangChainInstrumentor().is_instrumented_by_opentelemetry


def test_a_refused_startup_for_a_missing_client_secret_leaves_langchain_uninstrumented() -> None:
    settings = Settings(keycloak_client_secret="", learner_hash_key="k", phoenix_url="http://127.0.0.1:9")
    with pytest.raises(RuntimeError, match="KEYCLOAK_CLIENT_SECRET"), TestClient(create_app(settings)):
        pass
    assert not LangChainInstrumentor().is_instrumented_by_opentelemetry


class _RecordingTracing(AskTracing):
    def __init__(self) -> None:
        self.runs: list[AskRun] = []

    @contextmanager
    def trace(self, run: AskRun) -> Iterator[AskTrace]:
        self.runs.append(run)
        yield NoAskTrace()


def traced_client() -> tuple[TestClient, _RecordingTracing]:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    graph = build_graph(
        lambda token: FakeRetriever([CHUNK]), fake_chat_model(AIMessage("It weighs tokens [1].")), guard=PassingGuard()
    )
    tracing = _RecordingTracing()
    return TestClient(create_app(Settings(), verifier=verifier, graph=graph, tracing=tracing)), tracing


def test_the_run_and_thread_ids_reach_the_trace_with_the_principal() -> None:
    c, tracing = traced_client()
    run_id, thread_id = uuid.uuid4(), uuid.uuid4()
    body = {**BODY, "run_id": str(run_id), "thread_id": str(thread_id)}
    assert c.post("/ask", json=body, headers=AUTH).status_code == 200
    assert tracing.runs == [AskRun(run_id, str(thread_id), UserId("ada"), BODY["question"], None)]


def test_without_ids_the_run_gets_a_fresh_id_and_no_thread() -> None:
    c, tracing = traced_client()
    c.post("/ask", json=BODY, headers=AUTH)
    c.post("/ask", json=BODY, headers=AUTH)
    first, second = tracing.runs
    assert first.thread_id is None and first.run_id != second.run_id


def test_an_unknown_body_field_is_still_refused() -> None:
    c, _ = traced_client()
    assert c.post("/ask", json={**BODY, "turn_id": "x"}, headers=AUTH).status_code == 422


def test_history_in_the_request_reaches_the_search() -> None:
    retriever = FakeRetriever([CHUNK])
    c, _ = client(retriever)
    body = {
        "question": "What are its limitations?",
        "history": [{"question": "Explain the transformer architecture", "answer": "It uses attention."}],
    }
    response = c.post("/ask", json=body, headers=AUTH)
    assert response.status_code == 200
    assert retriever.calls[0][0] == "Explain the transformer architecture\nWhat are its limitations?"


@pytest.mark.parametrize(
    "history",
    [
        [{"question": "q", "answer": "a"}] * 21,
        [{"question": "", "answer": "a"}],
        [{"question": "q", "answer": "a" * 8001}],
        [{"question": "q", "answer": "a", "user_id": "ada"}],
    ],
)
def test_oversized_or_malformed_history_is_refused(history: list[dict[str, str]]) -> None:
    c, _ = client(FakeRetriever([CHUNK]))
    response = c.post("/ask", json={"question": "Q", "history": history}, headers=AUTH)
    assert response.status_code == 422


def test_a_tripped_answer_ends_with_replace_then_done_and_no_sources_or_citations() -> None:
    c, _ = client(
        FakeRetriever([CHUNK]), reply="Fine start then SECRET-CANARY tail", guard=TrippingGuard("SECRET-CANARY")
    )
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    names = [e for e, _ in got]
    assert names[-2:] == ["replace", "done"]
    assert got[-2][1] == {
        "code": "guard",
        "text": "I can only answer questions about your documents. Rephrase it to ask about their content.",
    }
    assert got[-2][1]["text"] == GUARD_MESSAGE
    assert "sources" not in names and "citations" not in names and "decline" not in names
    assert "SECRET-CANARY" not in "".join(d.get("text", "") for e, d in got if e == "delta")  # cut before it left


def test_a_trip_on_the_first_piece_sends_no_delta() -> None:
    c, _ = client(FakeRetriever([CHUNK]), reply="SECRET-CANARY first", guard=TrippingGuard("SECRET-CANARY"))
    assert [e for e, _ in events(c.post("/ask", json=BODY, headers=AUTH).text)] == ["replace", "done"]


class _BrokenGuard(PassingGuard):
    async def check_answer(self, text: str) -> GuardTrip | None:
        raise RuntimeError("guard down")


def test_a_guard_that_fails_fails_closed_with_an_unavailable_error() -> None:
    c, _ = client(FakeRetriever([CHUNK]), guard=_BrokenGuard())
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    names = [e for e, _ in got]
    assert got[-1][0] == "error" and got[-1][1]["code"] == "unavailable"
    assert "replace" not in names and "done" not in names and "delta" not in names


def test_an_off_topic_question_streams_only_the_decline_then_done() -> None:
    retriever = FakeRetriever([CHUNK])
    c, _ = client(retriever, topic_classifier=FakeTopicClassifier({"Tell me a joke.": 0.99}))
    got = events(c.post("/ask", json={"question": "Tell me a joke."}, headers=AUTH).text)
    assert got == [("decline", {"code": "off_topic", "message": OFF_TOPIC_DECLINE}), ("done", {})]
    assert retriever.calls == []


def test_an_on_topic_question_with_a_classifier_streams_the_answer_as_before() -> None:
    c, _ = client(FakeRetriever([CHUNK]), topic_classifier=FakeTopicClassifier({"What is attention?": 0.05}))
    names = [e for e, _ in events(c.post("/ask", json=BODY, headers=AUTH).text)]
    assert "decline" not in names and names[-3:] == ["sources", "citations", "done"]

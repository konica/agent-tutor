import json
import logging
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from fakes import FakeRetriever, FakeTokenVerifier, fake_chat_model
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.server import create_app
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.tutoring.application import DetectionPolicy
from smart_tutor.tutoring.domain.errors import RetrievalError
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

BODY = {"question": "What is attention?", "learner_subjects": [{"subject_id": "s1", "name": "General"}]}
POLICY = DetectionPolicy(0.5, 0.125, 0.0625)
AUTH = {"Authorization": "Bearer t-ada"}
CHUNK = RetrievedChunk("c1", "a.pdf", 3, "Attention weighs tokens.", 0.9)


def client(retriever: FakeRetriever, reply: str = "It weighs tokens [1].") -> tuple[TestClient, FakeTokenVerifier]:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    graph = build_graph(lambda token: retriever, fake_chat_model(AIMessage(reply)), POLICY)
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
    assert got[-2] == ("citations", {"citations": [{"n": 1, "chunk_id": "c1", "document_title": "a.pdf", "page": 3}]})
    assert got[-1] == ("done", {})


def test_the_subjects_event_comes_first() -> None:
    c, _ = client(FakeRetriever([CHUNK]))
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    assert got[0] == ("subjects", {"subject_ids": ["s1"]})
    assert [e for e, _ in got].count("subjects") == 1


def test_a_detection_failure_is_an_error_before_any_subjects() -> None:
    body = {**BODY, "learner_subjects": [{"subject_id": "s1", "name": "A"}, {"subject_id": "s2", "name": "B"}]}
    c, _ = client(FakeRetriever(error=RetrievalError("down")))
    got = events(c.post("/ask", json=body, headers=AUTH).text)
    assert got == [
        ("error", {"code": "unavailable", "message": "The tutor couldn't answer right now. Try again in a moment."})
    ]


def test_more_than_100_subjects_is_422() -> None:
    c, _ = client(FakeRetriever([CHUNK]))
    many = [{"subject_id": f"s{i}", "name": "x"} for i in range(101)]
    assert c.post("/ask", json={**BODY, "learner_subjects": many}, headers=AUTH).status_code == 422


def test_citations_carry_the_marker_number_the_answer_uses() -> None:
    other = RetrievedChunk("c2", "b.pdf", None, "Other text.", 0.8)
    c, _ = client(FakeRetriever([CHUNK, other]), reply="Only the second [2].")
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    assert got[-2] == (
        "citations",
        {"citations": [{"n": 2, "chunk_id": "c2", "document_title": "b.pdf", "page": None}]},
    )


def test_no_chunks_streams_the_fixed_answer() -> None:
    c, _ = client(FakeRetriever([]))
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    assert got == [
        ("subjects", {"subject_ids": ["s1"]}),
        ("delta", {"text": "I couldn't find anything about that in your documents."}),
        ("citations", {"citations": []}),
        ("done", {}),
    ]


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
    assert c.post("/ask", json={**BODY, "learner_subjects": []}, headers=AUTH).status_code == 422
    old = {"question": "What is attention?", "subjects": BODY["learner_subjects"]}
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

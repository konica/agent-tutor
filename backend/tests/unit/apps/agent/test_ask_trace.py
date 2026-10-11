"""PRD §10.4: each ask is one `ask` trace with run metadata; the learner only as a keyed hash."""

import json
import uuid
from typing import Any

import langsmith
from langchain_core.messages import AIMessage

from fakes import FakeRetriever, RecordingClient, fake_chat_model
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.server import AskRequest, answer_events
from smart_tutor.apps.agent.tracing import AskRun, AskTracing
from smart_tutor.shared.adapters.tracing import LearnerHasher
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.tutoring.domain.errors import RetrievalError
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

RUN_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
THREAD_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
USER = UserId("user-under-test-123")
META = {"deployment": "local", "chat_model": "chat-x", "embedding_model": "embed-y"}
CHUNKS = [
    RetrievedChunk("c1", "d1", "a.pdf", 3, "Attention weighs tokens.", 0.9),
    RetrievedChunk("c2", "d2", "b.pdf", 1, "Other text.", 0.8),
]


async def traced(
    body: AskRequest,
    chunks: list[RetrievedChunk] = CHUNKS,
    close_after: int | None = None,
    error: Exception | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    recorder = RecordingClient()
    tracing = AskTracing(META, LearnerHasher("k"), client=recorder)
    graph = build_graph(
        lambda token: FakeRetriever(chunks, error=error), fake_chat_model(AIMessage("It weighs tokens [1]."))
    )
    run = AskRun(RUN_ID, body.thread_id and str(body.thread_id), USER, body.question, body.document_ids)
    got: list[str] = []
    with langsmith.tracing_context(enabled=True):
        events = answer_events(graph, body, "tok", run, tracing)
        async for event in events:
            got.append(event)
            if close_after is not None and len(got) >= close_after:
                await events.aclose()
                break
    return recorder.payloads, got


def root(payloads: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """The ask run's create payload and its final metadata (create merged with the last update)."""
    [create] = [p for p in payloads if p["op"] == "create" and p["name"] == "ask"]
    meta = dict(create["extra"]["metadata"])
    for p in payloads:
        if p["op"] == "update" and str(p.get("run_id")) == str(RUN_ID) and p.get("extra"):
            meta.update(p["extra"].get("metadata", {}))
    return create, meta


async def test_an_answer_traces_as_one_ask_run_with_its_metadata() -> None:
    payloads, _ = await traced(AskRequest(question="What is attention?", thread_id=uuid.UUID(THREAD_ID)))
    create, meta = root(payloads)
    assert str(create["id"]) == str(RUN_ID) and create.get("parent_run_id") is None
    assert create["inputs"]["question"] == "What is attention?"
    assert meta["thread_id"] == THREAD_ID
    assert meta["learner_hash"] == LearnerHasher("k")(USER)
    assert {k: meta[k] for k in META} == META
    assert meta["limited"] is False and meta["decline"] == "none" and meta["chunks"] == 2
    others = [p for p in payloads if p["op"] == "create" and p["name"] != "ask"]
    assert others and all(p.get("parent_run_id") is not None for p in others)  # LangGraph nests under ask


async def test_a_decline_traces_with_its_code_and_no_chunks_given_to_the_model() -> None:
    low = [RetrievedChunk("c1", "d1", "a.pdf", 3, "Unrelated.", 0.01)]
    payloads, _ = await traced(AskRequest(question="Q?", document_ids=["d1"]), chunks=low)
    _, meta = root(payloads)
    assert meta["limited"] is True and meta["decline"] == "limited" and meta["chunks"] == 0


async def test_a_no_documents_decline_traces_its_code() -> None:
    payloads, _ = await traced(AskRequest(question="Q?"), chunks=[])
    assert root(payloads)[1]["decline"] == "no_documents"


async def test_without_a_thread_id_the_run_still_traces() -> None:
    payloads, _ = await traced(AskRequest(question="Q?"))
    assert "thread_id" not in root(payloads)[1]


async def test_a_closed_stream_still_ends_the_ask_run() -> None:
    payloads, got = await traced(AskRequest(question="What is attention?"), close_after=1)
    assert len(got) == 1
    assert any(p["op"] == "update" and str(p.get("run_id")) == str(RUN_ID) for p in payloads)


async def test_the_user_id_never_reaches_the_trace() -> None:
    payloads, _ = await traced(AskRequest(question="What is attention?"))
    assert USER not in json.dumps(payloads, default=str)


async def test_a_failed_ask_ends_the_run_with_the_error_code() -> None:
    payloads, got = await traced(AskRequest(question="Q?"), error=RetrievalError("down"))
    assert got[-1].startswith("event: error") and "unavailable" in got[-1]
    updates = [p for p in payloads if p["op"] == "update" and str(p.get("run_id")) == str(RUN_ID)]
    assert updates[-1]["error"] == "unavailable"

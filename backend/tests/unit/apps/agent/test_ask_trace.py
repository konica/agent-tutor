"""PRD §10.4: each ask is one `ask` trace whose id is the turn's run id, with run metadata; the learner only as a
keyed hash."""

import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import StatusCode

from fakes import TRACE_META, FailingExporter, FakeRetriever, fake_chat_model, recorded_traces
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.server import AskRequest, answer_events
from smart_tutor.shared.adapters.ask_tracing import PhoenixAskTracing
from smart_tutor.shared.adapters.tracing import LearnerHasher, otlp_exporter, phoenix_traces, root_span_id
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.ports.ask_tracing import AskRun
from smart_tutor.tutoring.domain.errors import RetrievalError
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

RUN_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
THREAD_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
USER = UserId("user-under-test-123")
CHUNKS = [
    RetrievedChunk("c1", "d1", "a.pdf", 3, "Attention weighs tokens.", 0.9),
    RetrievedChunk("c2", "d2", "b.pdf", 1, "Other text.", 0.8),
]


async def traced(
    body: AskRequest,
    chunks: list[RetrievedChunk] = CHUNKS,
    close_after: int | None = None,
    error: Exception | None = None,
    sampling_rate: float = 1.0,
) -> tuple[list[ReadableSpan], list[str]]:
    graph = build_graph(
        lambda token: FakeRetriever(chunks, error=error), fake_chat_model(AIMessage("It weighs tokens [1]."))
    )
    run = AskRun(RUN_ID, body.thread_id and str(body.thread_id), USER, body.question, body.document_ids)
    got: list[str] = []
    with recorded_traces(sampling_rate=sampling_rate) as (traces, spans):
        events = answer_events(graph, body, "tok", run, PhoenixAskTracing(traces))
        async for event in events:
            got.append(event)
            if close_after is not None and len(got) >= close_after:
                await events.aclose()
                break
    return list(spans.get_finished_spans()), got


def ask_span(spans: list[ReadableSpan]) -> tuple[ReadableSpan, dict[str, Any]]:
    [span] = [s for s in spans if s.name == "ask"]
    return span, json.loads(span.attributes["metadata"])


async def test_an_answer_traces_as_one_root_ask_span_whose_trace_id_is_the_run_id() -> None:
    spans, _ = await traced(AskRequest(question="What is attention?", thread_id=uuid.UUID(THREAD_ID)))
    span, meta = ask_span(spans)
    assert span.parent is None
    assert span.context.trace_id == RUN_ID.int and span.context.span_id == root_span_id(RUN_ID)
    assert json.loads(span.attributes["input.value"])["question"] == "What is attention?"
    assert span.attributes["session.id"] == THREAD_ID
    assert meta["thread_id"] == THREAD_ID and meta["learner_hash"] == LearnerHasher("k")(USER)
    assert {k: meta[k] for k in TRACE_META} == TRACE_META
    assert meta["limited"] is False and meta["decline"] == "none" and meta["chunks"] == 2
    assert json.loads(span.attributes["output.value"])["answer"] == "It weighs tokens [1]."
    assert span.status.status_code is StatusCode.OK


async def test_langgraph_search_and_model_spans_nest_under_the_ask() -> None:
    spans, _ = await traced(AskRequest(question="What is attention?"))
    span, _ = ask_span(spans)
    others = [s for s in spans if s is not span]
    names = {s.name for s in others}
    assert {"LangGraph", "search", "answer"} <= names
    assert any(s.attributes.get("openinference.span.kind") == "LLM" for s in others)
    assert all(s.context.trace_id == RUN_ID.int and s.parent is not None for s in others)


async def test_a_decline_traces_with_its_code_and_no_chunks_given_to_the_model() -> None:
    low = [RetrievedChunk("c1", "d1", "a.pdf", 3, "Unrelated.", 0.01)]
    spans, _ = await traced(AskRequest(question="Q?", document_ids=["d1"]), chunks=low)
    _, meta = ask_span(spans)
    assert meta["limited"] is True and meta["decline"] == "limited" and meta["chunks"] == 0


async def test_a_no_documents_decline_traces_its_code() -> None:
    spans, _ = await traced(AskRequest(question="Q?"), chunks=[])
    assert ask_span(spans)[1]["decline"] == "no_documents"


async def test_without_a_thread_id_the_ask_still_traces() -> None:
    spans, _ = await traced(AskRequest(question="Q?"))
    span, meta = ask_span(spans)
    assert "thread_id" not in meta and "session.id" not in span.attributes


async def test_a_closed_stream_still_ends_the_ask_span() -> None:
    spans, got = await traced(AskRequest(question="What is attention?"), close_after=1)
    assert len(got) == 1
    span, _ = ask_span(spans)  # exported, so it ended
    assert span.context.trace_id == RUN_ID.int


async def test_a_failed_ask_ends_the_span_with_the_error_code() -> None:
    spans, got = await traced(AskRequest(question="Q?"), error=RetrievalError("down"))
    assert got[-1].startswith("event: error") and "unavailable" in got[-1]
    span, meta = ask_span(spans)
    assert span.status.status_code is StatusCode.ERROR and span.status.description == "unavailable"
    assert meta["decline"] == "none" and meta["chunks"] == 0


async def test_a_sampled_out_ask_exports_no_span_at_all() -> None:
    spans, got = await traced(AskRequest(question="What is attention?"), sampling_rate=0.0)
    assert got[-1].startswith("event: done") and spans == []  # children follow their root


async def test_a_failing_exporter_never_fails_the_ask() -> None:
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("It weighs tokens [1].")))
    run = AskRun(RUN_ID, None, USER, "What is attention?", None)
    with recorded_traces(exporter=FailingExporter()) as (traces, _):
        tracing = PhoenixAskTracing(traces)
        got = [e async for e in answer_events(graph, AskRequest(question="What is attention?"), "tok", run, tracing)]
    assert any(e.startswith("event: delta") for e in got) and got[-1].startswith("event: done")


async def test_a_collector_that_is_down_never_fails_the_ask() -> None:
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("It weighs tokens [1].")))
    run = AskRun(RUN_ID, None, USER, "What is attention?", None)
    exporter = otlp_exporter(Settings(phoenix_url="http://127.0.0.1:9"), timeout=1)  # nothing listens
    traces = phoenix_traces("p", 1.0, BatchSpanProcessor(exporter), LearnerHasher("k"), {})
    try:
        tracing = PhoenixAskTracing(traces)
        got = [e async for e in answer_events(graph, AskRequest(question="What is attention?"), "tok", run, tracing)]
    finally:
        traces.shutdown()
    assert got[-1].startswith("event: done")

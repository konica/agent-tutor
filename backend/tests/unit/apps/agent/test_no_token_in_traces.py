"""ADR 0007: the token rides in runtime context only, so neither Langfuse nor Phoenix receives it, in spans or in
rating scores; nor does a user id or an email (the learner is a keyed hash, ADR 0023).

The real OpenInference instrumentation exports to an in-memory exporter instead of the network. A positive control
puts the token in the question, so the check is proven able to fire.
"""

import json
import uuid
from collections.abc import Sequence
from typing import Any

import httpx
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from opentelemetry.sdk.trace import ReadableSpan

from fakes import (
    FakeLangfuseScores,
    FakeRetriever,
    FakeTokenVerifier,
    InlineExecutor,
    InMemoryLibrary,
    InMemoryThreads,
    PassingGuard,
    api_services,
    fake_agent,
    fake_chat_model,
    ingest_ready,
    recorded_traces,
)
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.server import AskRequest, answer_events
from smart_tutor.apps.agent.state import AgentContext
from smart_tutor.apps.api.main import create_app
from smart_tutor.shared.adapters.ask_tracing import OtelAskTracing
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.shared.ports.ask_tracing import AskRun
from smart_tutor.tutoring.adapters.langfuse_feedback import LangfuseAnswerFeedback
from smart_tutor.tutoring.application import HistoryTurn
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

TOKEN = "eyJhbGciOi.token-under-test.signature-xyz"
INPUT = {"question": "What is attention?"}
CHUNKS = [RetrievedChunk("c1", "d1", "a.pdf", 3, "Attention weighs tokens.", 0.9)]
AGENT_SSE = b'event: delta\ndata: {"text": "It weighs tokens [1]."}\n\nevent: done\ndata: {}\n\n'


def dumped(spans: Sequence[ReadableSpan]) -> str:
    """Every attribute and event of every span, with its resource."""
    return json.dumps([json.loads(s.to_json()) for s in spans])


async def traced_run(state: dict[str, Any], retriever: FakeRetriever | None = None) -> tuple[str, str]:
    """Run the graph, instrumented, with the token in context; return (dumped spans, dumped output state)."""
    retriever = retriever or FakeRetriever(CHUNKS)
    graph = build_graph(
        lambda token: retriever, fake_chat_model(AIMessage("It weighs tokens [1].")), guard=PassingGuard()
    )
    with recorded_traces() as (_, spans):
        out = await graph.ainvoke(state, context=AgentContext(access_token=TOKEN))
    assert spans.get_finished_spans(), "nothing was traced, so the check below would pass vacuously"
    return dumped(spans.get_finished_spans()), json.dumps(out, default=str)


async def test_the_token_never_reaches_traces_or_state() -> None:
    traces, out = await traced_run(INPUT)
    assert "What is attention?" in traces  # the payloads hold the run's inputs
    assert "It weighs tokens [1]." in traces  # and the model's output
    assert TOKEN not in traces
    assert TOKEN not in out


async def test_positive_control_a_token_in_the_question_is_caught() -> None:
    traces, out = await traced_run({**INPUT, "question": f"What is attention? {TOKEN}"})
    assert TOKEN in traces
    assert TOKEN in out


async def test_history_reaches_traces_without_the_token() -> None:
    traces, out = await traced_run({**INPUT, "history": [HistoryTurn("Explain attention", "It weighs tokens.")]})
    assert "Explain attention" in traces
    assert TOKEN not in traces and TOKEN not in out


def test_the_context_repr_hides_the_token() -> None:
    assert TOKEN not in repr(AgentContext(access_token=TOKEN))


USER_ID = "user-id-under-test-42"
EMAIL = "ada.lovelace@example.com"
THREAD_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


async def ask_spans(question: str) -> str:
    """A traced ask in a thread as USER_ID with TOKEN; every span dumped, Langfuse's attributes included."""
    graph = build_graph(
        lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("It weighs tokens [1].")), guard=PassingGuard()
    )
    body = AskRequest(question=question, thread_id=uuid.UUID(THREAD_ID))
    run = AskRun(uuid.uuid4(), THREAD_ID, UserId(USER_ID), body.question, None)
    with recorded_traces() as (traces, spans):
        async for _ in answer_events(graph, body, TOKEN, run, OtelAskTracing(traces)):
            pass
    assert spans.get_finished_spans()
    return dumped(spans.get_finished_spans())


async def test_the_ask_trace_holds_no_token_user_id_or_email() -> None:
    traces = await ask_spans("What is attention?")
    assert "What is attention?" in traces
    # The dump holds Langfuse's attributes too: the learner and thread on every span, and the root's metadata.
    for name in ("user.id", "session.id", "langfuse.trace.metadata.learner_hash", "langfuse.observation.input"):
        assert name in traces
    for secret in (TOKEN, USER_ID, EMAIL):
        assert secret not in traces


async def test_positive_control_a_user_id_in_the_question_is_caught() -> None:
    assert USER_ID in await ask_spans(f"What is attention? {USER_ID} {EMAIL}")


def rated_requests(question: str) -> str:
    """Ask through the API as Ada with TOKEN, rate the turn 👎, and return every request the API made to Langfuse."""
    verifier = FakeTokenVerifier()
    verifier.add(TOKEN, Principal(UserId(USER_ID), EMAIL, frozenset({"learner"})))
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, USER_ID, "Attention weighs tokens.")
    seen: list[httpx.Request] = []

    def agent(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=AGENT_SSE, headers={"content-type": "text/event-stream"})

    langfuse = FakeLangfuseScores()
    langfuse.config()
    sender = LangfuseAnswerFeedback(langfuse.client(), "local", executor=InlineExecutor(), sleep=lambda s: None)
    services = api_services(library, threads=threads, agent=fake_agent(agent), feedback=sender)
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))
    auth = {"Authorization": f"Bearer {TOKEN}"}
    client.post("/threads", json={"question": question}, headers=auth)
    run_id = json.loads(seen[0].content)["run_id"]
    [thread] = threads.threads.values()
    rated = client.put(f"/threads/{thread.thread_id}/turns/{run_id}/rating", json={"rating": "down"}, headers=auth)
    assert rated.status_code == 200 and langfuse.scores, "nothing was scored, so the check would pass vacuously"
    return json.dumps(
        [{"url": str(r.url), "headers": dict(r.headers), "body": r.content.decode()} for r in langfuse.requests]
    )


def test_the_rating_score_holds_no_token_user_id_or_email() -> None:
    sent = rated_requests("What is attention?")
    # Positive control: the dump holds the request bodies (the score) and headers (the Basic auth), so a secret
    # in either would be caught.
    assert "learner_rating" in sent and "Basic " in sent
    for secret in (TOKEN, USER_ID, EMAIL):
        assert secret not in sent

"""ADR 0007: the learner's token rides in runtime context only, so LangSmith never receives it.

The real LangChainTracer sends to a client that records payloads instead of the network. A positive control puts
the token in the question, so the check is proven able to fire.
"""

import json
from typing import Any

import langsmith
from langchain_core.messages import AIMessage
from langchain_core.tracers import LangChainTracer

from fakes import FakeRetriever, fake_chat_model
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.state import AgentContext
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

TOKEN = "eyJhbGciOi.token-under-test.signature-xyz"
INPUT = {"question": "What is attention?"}
CHUNKS = [RetrievedChunk("c1", "a.pdf", 3, "Attention weighs tokens.", 0.9)]


class RecordingClient(langsmith.Client):
    """LangSmith client that records create/update payloads instead of sending them."""

    def __init__(self) -> None:
        super().__init__(api_key="test-not-a-key", api_url="http://127.0.0.1:9", auto_batch_tracing=False)
        self.payloads: list[dict[str, Any]] = []

    def create_run(self, *args: Any, **kwargs: Any) -> None:
        self.payloads.append({"op": "create", **kwargs})

    def update_run(self, *args: Any, **kwargs: Any) -> None:
        self.payloads.append({"op": "update", "run_id": str(args[0]) if args else None, **kwargs})


async def traced_run(state: dict[str, Any], retriever: FakeRetriever | None = None) -> tuple[str, str]:
    """Run the graph with the token in context; return (dumped trace payloads, dumped output state)."""
    recorder = RecordingClient()
    tracer = LangChainTracer(client=recorder, project_name="test")
    retriever = retriever or FakeRetriever(CHUNKS)
    graph = build_graph(lambda token: retriever, fake_chat_model(AIMessage("It weighs tokens [1].")))
    with langsmith.tracing_context(enabled=True):
        out = await graph.ainvoke(state, context=AgentContext(access_token=TOKEN), config={"callbacks": [tracer]})
    tracer.wait_for_futures()
    assert recorder.payloads, "the tracer recorded nothing, so the check below would pass vacuously"
    return json.dumps(recorder.payloads, default=str), json.dumps(out, default=str)


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


def test_the_context_repr_hides_the_token() -> None:
    assert TOKEN not in repr(AgentContext(access_token=TOKEN))

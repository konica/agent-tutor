from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from fakes import FakeRetriever, fake_chat_model
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.state import AgentContext
from smart_tutor.tutoring.application import NO_CHUNKS_ANSWER, DetectionPolicy, Retriever
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

CHUNKS = [
    RetrievedChunk("c1", "a.pdf", 3, "Attention weighs tokens.", 0.9),
    RetrievedChunk("c2", "b.pdf", None, "Unrelated.", 0.5),
]
INPUT = {"question": "What is attention?", "learner_subjects": {"s1": "General"}}
POLICY = DetectionPolicy(0.5, 0.125, 0.0625)


async def test_searches_the_thread_subjects_with_the_context_token_then_answers_with_citations() -> None:
    retriever, tokens = FakeRetriever(CHUNKS), []

    def retriever_for(token: str) -> Retriever:
        tokens.append(token)
        return retriever

    graph = build_graph(retriever_for, fake_chat_model(AIMessage("It weighs tokens [1].")), POLICY)
    out = await graph.ainvoke(INPUT, context=AgentContext(access_token="t-ada"))
    assert tokens == ["t-ada", "t-ada"]  # one retriever per node
    assert out["subject_ids"] == ["s1"]
    assert retriever.calls == [("What is attention?", ["s1"], 5)]  # one subject: nothing to detect, no search
    assert out["answer"] == "It weighs tokens [1]."
    assert [c.chunk_id for c in out["citations"]] == ["c1"]


async def test_no_chunks_gives_the_fixed_answer_without_calling_the_model() -> None:
    model = fake_chat_model()  # no scripted reply: a call would fail
    graph = build_graph(lambda token: FakeRetriever([]), model, POLICY)
    out = await graph.ainvoke(INPUT, context=AgentContext(access_token="t"))
    assert out["answer"] == NO_CHUNKS_ANSWER and out["citations"] == []


class _SeenMessages(BaseCallbackHandler):
    def __init__(self) -> None:
        self.seen: list[list[BaseMessage]] = []

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[BaseMessage]], **kwargs: Any) -> None:
        self.seen.extend(messages)


async def test_the_model_sees_quoted_chunks_and_the_subject_names() -> None:
    spy = _SeenMessages()
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("ok [1]")), POLICY)
    await graph.ainvoke(INPUT, context=AgentContext(access_token="t"), config={"callbacks": [spy]})
    assert len(spy.seen) == 1
    system, human = spy.seen[0]
    assert isinstance(system, SystemMessage) and "General" in system.text
    assert isinstance(human, HumanMessage)
    assert '<chunk id="1" document="a.pdf" page="3">' in human.text
    assert "Question: What is attention?" in human.text


async def test_detects_the_subjects_then_searches_only_those() -> None:
    chunks = [
        RetrievedChunk("c1", "a.pdf", 3, "Attention weighs tokens.", 0.75, ("s2",)),
        RetrievedChunk("c2", "b.pdf", 1, "Unrelated.", 0.25, ("s1",)),
    ]
    retriever = FakeRetriever(chunks)
    graph = build_graph(lambda token: retriever, fake_chat_model(AIMessage("It weighs tokens [1].")), POLICY)
    out = await graph.ainvoke(
        {"question": "What is attention?", "learner_subjects": {"s1": "General", "s2": "LLMs"}},
        context=AgentContext(access_token="t"),
    )
    assert retriever.calls == [("What is attention?", ["s1", "s2"], 20), ("What is attention?", ["s2"], 5)]
    assert out["subject_ids"] == ["s2"] and out["subject_names"] == ["LLMs"]

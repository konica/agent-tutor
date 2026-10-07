from typing import Any

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from fakes import FakeRetriever, fake_chat_model
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.nodes.choose_subjects import InvalidPickError
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


UNSURE_CHUNKS = [
    RetrievedChunk("c1", "a.pdf", 3, "Attention weighs tokens.", 0.6, ("s1",)),
    RetrievedChunk("c2", "b.pdf", 1, "Agents call tools.", 0.58, ("s2",)),
]
UNSURE_INPUT = {"question": "What is attention?", "learner_subjects": {"s1": "A", "s2": "B"}}
UNSURE_POLICY = DetectionPolicy(0.5, 0.125, 0.0)
CONFIG: RunnableConfig = {"configurable": {"thread_id": "ada/t1"}}


async def test_unsure_pauses_for_the_learners_pick_then_answers_the_original_question() -> None:
    retriever = FakeRetriever(UNSURE_CHUNKS)
    graph = build_graph(
        lambda token: retriever, fake_chat_model(AIMessage("Answer [1].")), UNSURE_POLICY, InMemorySaver()
    )
    ctx = AgentContext(access_token="t")

    first = await graph.ainvoke(UNSURE_INPUT, config=CONFIG, context=ctx)
    [pause] = first["__interrupt__"]
    assert pause.value == {"subject_ids": ["s1", "s2"]}
    searches_before = len(retriever.calls)

    out = await graph.ainvoke(Command(resume={"subject_ids": ["s2"]}), config=CONFIG, context=ctx)
    assert out["subject_ids"] == ["s2"] and out["subject_names"] == ["B"]
    assert out["answer"] == "Answer [1]."
    # Resuming searched only the picked subject for the answer; detection did not run again.
    assert retriever.calls[searches_before:] == [(UNSURE_INPUT["question"], ["s2"], 5)]


@pytest.mark.parametrize("picked", [[], ["s1", "s2", "s3", "s4"], ["zz"], ["s1", "s1"], "s1", None])
async def test_a_pick_outside_the_choices_is_refused(picked: object) -> None:
    graph = build_graph(
        lambda token: FakeRetriever(UNSURE_CHUNKS), fake_chat_model(AIMessage("x")), UNSURE_POLICY, InMemorySaver()
    )
    ctx = AgentContext(access_token="t")
    await graph.ainvoke(UNSURE_INPUT, config=CONFIG, context=ctx)
    with pytest.raises(InvalidPickError):
        await graph.ainvoke(Command(resume={"subject_ids": picked}), config=CONFIG, context=ctx)
    assert (await graph.aget_state(CONFIG)).interrupts  # still waiting


async def test_a_bound_detection_never_interrupts_even_with_a_checkpointer() -> None:
    chunks = [RetrievedChunk("c1", "a.pdf", 3, "Attention weighs tokens.", 0.9, ("s1",))]
    graph = build_graph(
        lambda token: FakeRetriever(chunks), fake_chat_model(AIMessage("ok [1]")), UNSURE_POLICY, InMemorySaver()
    )
    out = await graph.ainvoke(UNSURE_INPUT, config=CONFIG, context=AgentContext(access_token="t"))
    assert "__interrupt__" not in out and out["subject_ids"] == ["s1"]

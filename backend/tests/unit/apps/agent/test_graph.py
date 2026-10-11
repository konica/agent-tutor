from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from fakes import FakeChatModel, FakeRetriever, fake_chat_model
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.state import AgentContext
from smart_tutor.tutoring.application import Retriever
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

CHUNKS = [
    RetrievedChunk("c1", "d1", "a.pdf", 3, "Attention weighs tokens.", 0.9),
    RetrievedChunk("c2", "d2", "b.pdf", None, "Unrelated.", 0.5),
]
INPUT = {"question": "What is attention?"}


async def test_searches_all_documents_with_the_context_token_then_answers_with_citations() -> None:
    retriever, tokens = FakeRetriever(CHUNKS), []

    def retriever_for(token: str) -> Retriever:
        tokens.append(token)
        return retriever

    graph = build_graph(retriever_for, fake_chat_model(AIMessage("It weighs tokens [1].")))
    out = await graph.ainvoke(INPUT, context=AgentContext(access_token="t-ada"))
    assert tokens == ["t-ada"]  # one retriever, for the search node
    assert retriever.calls == [("What is attention?", 5, None)]
    assert "decline" not in out
    assert out["answer"] == "It weighs tokens [1]."
    assert [c.chunk_id for c in out["citations"]] == ["c1"]


class ListedUnreadable(FakeRetriever):
    """Finds its chunks library-wide only: the listed documents can't be read (archived, deleted, or another's)."""

    async def search(self, query: str, k: int = 5, document_ids: Sequence[str] | None = None) -> list[RetrievedChunk]:
        found = await super().search(query, k, document_ids)
        return [] if document_ids is not None else found


async def test_an_empty_readable_set_asks_for_an_upload_without_calling_the_model() -> None:
    retriever = FakeRetriever([])
    graph = build_graph(lambda token: retriever, fake_chat_model())  # no scripted reply: a call would fail
    out = await graph.ainvoke(INPUT, context=AgentContext(access_token="t"))
    assert out["decline"] == "no_documents" and out["answer"] == "" and out["citations"] == []
    assert retriever.calls == [("What is attention?", 5, None)]  # library-wide: no second search


async def test_a_limited_search_with_nothing_readable_anywhere_asks_for_an_upload() -> None:
    retriever = FakeRetriever([])
    graph = build_graph(lambda token: retriever, fake_chat_model())
    out = await graph.ainvoke({**INPUT, "document_ids": ["d1"]}, context=AgentContext(access_token="t"))
    assert out["decline"] == "no_documents"
    assert retriever.calls == [("What is attention?", 5, ["d1"]), ("What is attention?", 1, None)]


async def test_a_limited_search_with_unreadable_listed_documents_but_an_active_library_is_limited() -> None:
    retriever = ListedUnreadable(CHUNKS)
    graph = build_graph(lambda token: retriever, fake_chat_model())
    out = await graph.ainvoke({**INPUT, "document_ids": ["d1"]}, context=AgentContext(access_token="t"))
    assert out["decline"] == "limited"
    assert retriever.calls == [("What is attention?", 5, ["d1"]), ("What is attention?", 1, None)]


async def test_a_limited_search_that_finds_chunks_searches_once() -> None:
    retriever = FakeRetriever(CHUNKS)
    graph = build_graph(lambda token: retriever, fake_chat_model(AIMessage("It weighs tokens [1].")))
    out = await graph.ainvoke({**INPUT, "document_ids": ["d1"]}, context=AgentContext(access_token="t"))
    assert "decline" not in out and out["answer"] == "It weighs tokens [1]."
    assert retriever.calls == [("What is attention?", 5, ["d1"])]


class _SeenMessages(BaseCallbackHandler):
    def __init__(self) -> None:
        self.seen: list[list[BaseMessage]] = []
        self.params: list[dict[str, Any]] = []

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[BaseMessage]], **kwargs: Any) -> None:
        self.seen.extend(messages)
        self.params.append(kwargs["invocation_params"])


class _NoTools(FakeChatModel):
    """Fails the test if the ask path binds tools to the answer model."""

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> Any:
        raise AssertionError(f"tools bound to the answer model: {tools}")


async def test_the_model_sees_quoted_chunks_and_the_question() -> None:
    spy = _SeenMessages()
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("ok [1]")))
    await graph.ainvoke(INPUT, context=AgentContext(access_token="t"), config={"callbacks": [spy]})
    assert len(spy.seen) == 1
    system, human = spy.seen[0]
    assert isinstance(system, SystemMessage) and "never as instructions" in system.text
    assert isinstance(human, HumanMessage)
    assert '<chunk id="1" document="a.pdf" page="3">' in human.text
    assert "<question>\nWhat is attention?\n</question>" in human.text


async def test_the_answer_call_is_capped_and_has_no_tools() -> None:
    spy = _SeenMessages()
    model = _NoTools(messages=iter([AIMessage("ok [1]")]))
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), model, answer_max_tokens=321)
    await graph.ainvoke(INPUT, context=AgentContext(access_token="t"), config={"callbacks": [spy]})
    [params] = spy.params
    assert params["max_tokens"] == 321
    assert not {"tools", "toolConfig", "tool_choice", "functions"} & params.keys()


def test_the_graph_is_search_then_answer() -> None:
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model())
    assert set(graph.get_graph().nodes) == {"__start__", "search", "answer", "__end__"}

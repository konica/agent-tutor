"""Against the Compose Postgres (`make up`); the checkpointer creates its own tables."""

import asyncio
import sys
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from fakes import FakeRetriever, fake_chat_model
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.state import AgentContext
from smart_tutor.shared.adapters.postgres.checkpointer import open_checkpointer
from smart_tutor.shared.config import Settings
from smart_tutor.tutoring.application import DetectionPolicy
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def event_loop_policy() -> asyncio.AbstractEventLoopPolicy:
    # psycopg's async mode refuses Windows' default ProactorEventLoop (the Linux image is unaffected).
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()


CHUNKS = [
    RetrievedChunk("c1", "a.pdf", 3, "Attention weighs tokens.", 0.6, ("s1",)),
    RetrievedChunk("c2", "b.pdf", 1, "Agents call tools.", 0.58, ("s2",)),
]
POLICY = DetectionPolicy(0.5, 0.125, 0.0)


async def test_a_pending_pick_survives_an_agent_restart() -> None:
    url = Settings().database_url
    config: RunnableConfig = {"configurable": {"thread_id": f"ada/{uuid4()}"}}
    ctx = AgentContext(access_token="t")

    async with open_checkpointer(url) as saver:
        graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("x")), POLICY, saver)
        first = await graph.ainvoke(
            {"question": "What is attention?", "learner_subjects": {"s1": "A", "s2": "B"}}, config, context=ctx
        )
        assert first["__interrupt__"][0].value == {"subject_ids": ["s1", "s2"]}

    async with open_checkpointer(url) as saver:  # a restarted agent: new pool, new graph
        graph = build_graph(
            lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("Answer [1].")), POLICY, saver
        )
        assert (await graph.aget_state(config)).interrupts
        out = await graph.ainvoke(Command(resume={"subject_ids": ["s2"]}), config, context=ctx)
        assert out["subject_ids"] == ["s2"] and out["answer"] == "Answer [1]."
        assert not (await graph.aget_state(config)).interrupts

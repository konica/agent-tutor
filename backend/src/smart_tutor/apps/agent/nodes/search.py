"""Search step (PRD §9.2 step 2): all the learner's ready documents, or only the conversation's listed ones
(US-4c), k = 5, token from runtime context."""

from collections.abc import Callable
from typing import Protocol

from langgraph.runtime import Runtime

from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.tutoring.application import Retriever

K = 5


class SearchNode(Protocol):
    async def __call__(self, state: AskState, *, runtime: Runtime[AgentContext]) -> AskState: ...


def search_node(retriever_for: Callable[[str], Retriever]) -> SearchNode:
    async def search(state: AskState, *, runtime: Runtime[AgentContext]) -> AskState:
        retriever = retriever_for(runtime.context.access_token)
        chunks = await retriever.search(state["question"], K, state.get("document_ids"))
        return {"chunks": chunks}

    return search

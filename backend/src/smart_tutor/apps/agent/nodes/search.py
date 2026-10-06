"""Search step (PRD §9.2 step 2): the thread's subjects, k = 5, with the learner's token from runtime context."""

from collections.abc import Callable
from typing import Protocol

from langgraph.runtime import Runtime

from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.application import Retriever

K = 5


class SearchNode(Protocol):
    async def __call__(self, state: AskState, *, runtime: Runtime[AgentContext]) -> AskState: ...


def search_node(retriever_for: Callable[[str], Retriever]) -> SearchNode:
    async def search(state: AskState, *, runtime: Runtime[AgentContext]) -> AskState:
        retriever = retriever_for(runtime.context.access_token)
        chunks = await retriever.search(state["question"], [SubjectId(s) for s in state["subject_ids"]], K)
        return {"chunks": chunks}

    return search

"""Search step (PRD §9.2 step 1): all the learner's ready documents, or only the conversation's listed ones
(US-4c), k = 5, token from runtime context; a follow-up adds the previous question to the query (`search_query`)."""

from collections.abc import Callable
from typing import Protocol

from langgraph.runtime import Runtime

from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.tutoring.application import Retriever, search_query

K = 5


class SearchNode(Protocol):
    async def __call__(self, state: AskState, *, runtime: Runtime[AgentContext]) -> AskState: ...


def search_node(retriever_for: Callable[[str], Retriever]) -> SearchNode:
    async def search(state: AskState, *, runtime: Runtime[AgentContext]) -> AskState:
        retriever = retriever_for(runtime.context.access_token)
        query, document_ids = search_query(state["question"], state.get("history", [])), state.get("document_ids")
        chunks = await retriever.search(query, K, document_ids)
        # An empty readable set gets the upload request. A limited search that found nothing only says its listed
        # documents can't be read, so one library-wide chunk tells whether anything else can.
        no_documents = not chunks and (document_ids is None or not await retriever.search(query, 1, None))
        return {"chunks": chunks, "no_documents": no_documents}

    return search

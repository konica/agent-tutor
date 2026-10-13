"""The ask graph (PRD §9.2): search → answer, the answer checked by `guard` as it streams. Single turn, no
checkpointer (#31)."""

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from smart_tutor.apps.agent.nodes.answer import answer_node
from smart_tutor.apps.agent.nodes.search import search_node
from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.tutoring.application import SYSTEM_PROMPT, Guard, Retriever

AskGraph = CompiledStateGraph[AskState, AgentContext, AskState, AskState]


def build_graph(
    retriever_for: Callable[[str], Retriever],
    model: BaseChatModel,
    answer_floor: float = 0.3,
    answer_max_tokens: int = 1500,
    *,
    guard: Guard,
    system_prompt: str = SYSTEM_PROMPT,
) -> AskGraph:
    return (
        StateGraph(AskState, context_schema=AgentContext)
        .add_node("search", search_node(retriever_for))
        .add_node("answer", answer_node(model, answer_floor, answer_max_tokens, guard, system_prompt))
        .add_edge(START, "search")
        .add_edge("search", "answer")
        .add_edge("answer", END)
        .compile()
    )

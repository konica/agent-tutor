"""The ask graph (PRD §9.2): resolve subjects → (choose subjects) → search → answer. Single turn.

When detection is unsure, choose_subjects interrupts and waits for the learner's pick; that pause needs a
checkpointer, which the caller supplies (none for graphs that never pause). The token is context, never state.
"""

from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from smart_tutor.apps.agent.nodes.answer import answer_node
from smart_tutor.apps.agent.nodes.choose_subjects import choose_subjects
from smart_tutor.apps.agent.nodes.resolve_subjects import resolve_subjects_node
from smart_tutor.apps.agent.nodes.search import search_node
from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.tutoring.application import DetectionPolicy, Retriever

AskGraph = CompiledStateGraph[AskState, AgentContext, AskState, AskState]


def build_graph(
    retriever_for: Callable[[str], Retriever],
    model: BaseChatModel,
    policy: DetectionPolicy,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> AskGraph:
    return (
        StateGraph(AskState, context_schema=AgentContext)
        .add_node("resolve_subjects", resolve_subjects_node(retriever_for, policy))
        .add_node("choose_subjects", choose_subjects)
        .add_node("search", search_node(retriever_for))
        .add_node("answer", answer_node(model))
        .add_edge(START, "resolve_subjects")
        .add_conditional_edges(
            "resolve_subjects",
            lambda state: "search" if state["subject_ids"] else "choose_subjects",
            ["search", "choose_subjects"],
        )
        .add_edge("choose_subjects", "search")
        .add_edge("search", "answer")
        .add_edge("answer", END)
        .compile(checkpointer=checkpointer)
    )

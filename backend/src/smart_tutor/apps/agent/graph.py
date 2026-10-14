"""The ask graph (PRD §9.2): topic check → screen → search → answer, or topic check → decline, or screen → guard
decline. The topic check and the question screen run before search; the answer is checked by `guard` as it streams.
Single turn, no checkpointer (#31)."""

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from smart_tutor.apps.agent.nodes.answer import answer_node
from smart_tutor.apps.agent.nodes.screen import screen_node
from smart_tutor.apps.agent.nodes.search import search_node
from smart_tutor.apps.agent.nodes.topic_check import after_topic_check, topic_check_node
from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.tutoring.application import SYSTEM_PROMPT, Guard, Retriever, TopicClassifier

AskGraph = CompiledStateGraph[AskState, AgentContext, AskState, AskState]


def _after_screen(state: AskState) -> str:
    return END if state.get("decline") == "guard" else "search"


def build_graph(
    retriever_for: Callable[[str], Retriever],
    model: BaseChatModel,
    answer_floor: float = 0.3,
    answer_max_tokens: int = 1500,
    *,
    guard: Guard,
    system_prompt: str = SYSTEM_PROMPT,
    topic_classifier: TopicClassifier | None = None,
    topic_threshold: float = 0.5,
    topic_timeout_ms: int = 250,
) -> AskGraph:
    return (
        StateGraph(AskState, context_schema=AgentContext)
        .add_node("topic_check", topic_check_node(topic_classifier, topic_threshold, topic_timeout_ms))
        .add_node("screen", screen_node(guard))
        .add_node("search", search_node(retriever_for))
        .add_node("answer", answer_node(model, answer_floor, answer_max_tokens, guard, system_prompt))
        .add_edge(START, "topic_check")
        # The local topic check first (spec 2026-10-13 §4.1): an off-topic question costs no question screen call.
        .add_conditional_edges("topic_check", after_topic_check, {"on_topic": "screen", "declined": END})
        .add_conditional_edges("screen", _after_screen, ["search", END])
        .add_edge("search", "answer")
        .add_edge("answer", END)
        .compile()
    )

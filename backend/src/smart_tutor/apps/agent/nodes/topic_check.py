"""Topic check (PRD §9.2 step 0, spec 2026-10-13): an off-topic question is declined before any search or model call.
The check fails open: no classifier, an error, or a timeout lets the question go on to search."""

import asyncio
import logging
from typing import Literal, Protocol

from smart_tutor.apps.agent.state import AskState, TopicCheck
from smart_tutor.tutoring.application import TopicClassifier

logger = logging.getLogger(__name__)


class TopicCheckNode(Protocol):
    async def __call__(self, state: AskState) -> AskState: ...


def topic_check_node(classifier: TopicClassifier | None, threshold: float, timeout_ms: int) -> TopicCheckNode:
    async def topic_check(state: AskState) -> AskState:
        if classifier is None:
            return {"topic_check": {"verdict": "off"}}
        try:
            verdict = await asyncio.wait_for(
                classifier.classify(state["question"], state.get("history", [])), timeout_ms / 1000
            )
        except Exception as error:  # TimeoutError included: fail open
            logger.warning("topic check failed open: %s", type(error).__name__)  # never the question
            return {"topic_check": {"verdict": "error"}}
        off = verdict.is_off_topic(threshold)
        check: TopicCheck = {
            "verdict": "off_topic" if off else "on_topic",
            "p_off_topic": round(verdict.p_off_topic, 4),
            "model": verdict.model,
        }
        if not off:
            return {"topic_check": check}
        return {"topic_check": check, "answer": "", "citations": [], "decline": "off_topic"}

    return topic_check


def after_topic_check(state: AskState) -> Literal["on_topic", "declined"]:
    return "declined" if state.get("decline") == "off_topic" else "on_topic"

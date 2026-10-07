"""Resolve subjects (PRD §9.2 step 1): detect the new thread's subjects among the learner's, with their token."""

from collections.abc import Callable
from typing import Protocol

from langgraph.runtime import Runtime

from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.application import DetectionPolicy, Retriever, SubjectDetector


class ResolveSubjectsNode(Protocol):
    async def __call__(self, state: AskState, *, runtime: Runtime[AgentContext]) -> AskState: ...


def resolve_subjects_node(retriever_for: Callable[[str], Retriever], policy: DetectionPolicy) -> ResolveSubjectsNode:
    async def resolve_subjects(state: AskState, *, runtime: Runtime[AgentContext]) -> AskState:
        learner = state["learner_subjects"]
        detector = SubjectDetector(retriever_for(runtime.context.access_token), policy)
        detection = await detector.detect(state["question"], [SubjectId(s) for s in learner])
        if detection.unsure:
            return {"subject_ids": [], "subject_names": [], "choices": list(learner)}
        subject_ids = [str(s) for s in detection.subject_ids]
        return {"subject_ids": subject_ids, "subject_names": [learner[s] for s in subject_ids]}

    return resolve_subjects

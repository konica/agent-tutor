"""Question screen (PRD §9.2 step 0, D30): the learner's question, and only it, through the guard's question check
before search. A trip ends the turn with the `guard` decline; search and the model are not called (D29)."""

from typing import Protocol

from smart_tutor.apps.agent.state import AskState
from smart_tutor.tutoring.application import Guard


class ScreenNode(Protocol):
    async def __call__(self, state: AskState) -> AskState: ...


def screen_node(guard: Guard) -> ScreenNode:
    async def screen(state: AskState) -> AskState:
        trip = await guard.check_question(state["question"])  # never history, chunks, or the system prompt
        if trip is None:
            return {}
        return {"answer": "", "citations": [], "decline": "guard", "guard": trip.reason}

    return screen

"""Choose subjects (PRD §9.2 step 1, US-3): detection was unsure, so the graph waits for the learner's pick.

The question stays in the checkpoint; the API resumes with Command(resume={"subject_ids": [...]}) (1–3 of the choices).
"""

from langgraph.types import interrupt

from smart_tutor.apps.agent.state import AskState
from smart_tutor.tutoring.application import MAX_SUBJECTS


class InvalidPickError(ValueError):
    """The resume value isn't 1–3 distinct subjects from the choices offered."""


def choose_subjects(state: AskState) -> AskState:
    choices = state["choices"]
    value = interrupt({"subject_ids": choices})
    picked = value.get("subject_ids") if isinstance(value, dict) else None
    if (
        not isinstance(picked, list)
        or not all(isinstance(s, str) for s in picked)
        or not 1 <= len(picked) <= MAX_SUBJECTS
        or len(set(picked)) != len(picked)
        or not set(picked) <= set(choices)
    ):
        raise InvalidPickError("the pick must be 1 to 3 distinct subjects from the choices")
    return {"subject_ids": picked, "subject_names": [state["learner_subjects"][s] for s in picked]}

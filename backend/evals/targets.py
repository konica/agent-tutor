"""How an evaluation run invokes the agent: one input example in, the run's outputs and trajectory out (M2)."""

from typing import Any


def tutor_target(inputs: dict[str, Any]) -> dict[str, Any]:
    raise NotImplementedError("M2: invoke the agent graph and return answer, citations, trajectory, state.subject")

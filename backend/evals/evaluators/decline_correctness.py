"""Decline correctness (PRD §10.1, code): a limited conversation declines a question its listed documents don't cover
(`correctly_declined`) and answers one they do (`wrongly_declined`, a miss when it declines). Two evaluators, one key
each, so the runner never fills the metric a given example doesn't cover. Scored 1 or 0 from the ask target's
`decline` code; an unlimited conversation has no relevance gate yet (US-5, #14)."""

from typing import Any

from evals.suite import Suite, not_applicable
from evals.targets import ask_target

CORRECTLY_DECLINED = "decline_correctness.correctly_declined"
WRONGLY_DECLINED = "decline_correctness.wrongly_declined"
FAILED = "the run failed before it answered"


def correctly_declined(
    inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    if reference_outputs["covered"]:
        return not_applicable(CORRECTLY_DECLINED, "the library covers the question: wrongly_declined scores it")
    if inputs["documents"] is None:  # the example's limit: a failed run's outputs have none
        return not_applicable(CORRECTLY_DECLINED, "an unlimited conversation has no relevance gate until US-5 (#14)")
    if "decline" not in outputs:
        return {"key": CORRECTLY_DECLINED, "score": 0, "comment": FAILED}
    if outputs["decline"]:
        return {"key": CORRECTLY_DECLINED, "score": 1, "comment": f"declined ({outputs['decline']})"}
    answer = outputs.get("answer") or ""
    return {
        "key": CORRECTLY_DECLINED,
        "score": 0,
        "comment": f"answered a question the listed documents don't cover: {answer[:120]}",
    }


def wrongly_declined(
    inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    if not reference_outputs["covered"]:
        return not_applicable(WRONGLY_DECLINED, "the library doesn't cover the question: correctly_declined scores it")
    if "decline" not in outputs:
        return {"key": WRONGLY_DECLINED, "score": 1, "comment": FAILED}
    if outputs["decline"]:
        return {"key": WRONGLY_DECLINED, "score": 1, "comment": f"declined ({outputs['decline']}) a covered question"}
    return {"key": WRONGLY_DECLINED, "score": 0, "comment": "answered"}


SUITE = Suite(dataset="ask", target=ask_target, evaluators=(correctly_declined, wrongly_declined))

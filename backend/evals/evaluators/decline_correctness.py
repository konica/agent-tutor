"""Decline correctness (PRD §10.1, code): a limited conversation declines a question its listed documents don't cover
and answers one they do. An example marked `off_topic` must get the `off_topic` decline, limited or not.
`correctly_declined` scores the limited, uncovered examples: 1 when the run gave the `limited` decline.
`wrongly_declined` scores every covered example, limited or not: 1 when the run declined at all (a miss).
Two evaluators, one key each, so the runner never fills the metric a given example doesn't cover. Scored from the ask
target's `decline` code; an unlimited conversation has no relevance gate yet (US-5, #14)."""

from typing import Any

from evals.suite import Suite, not_applicable, scores
from evals.targets import ask_target

CORRECTLY_DECLINED = "decline_correctness.correctly_declined"
WRONGLY_DECLINED = "decline_correctness.wrongly_declined"
FAILED = "the run failed before it answered"


@scores(CORRECTLY_DECLINED)
def correctly_declined(
    inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    if reference_outputs.get("off_topic"):  # declined by the topic check before search (spec 2026-10-13)
        if "decline" not in outputs:
            return {"key": "decline_correctness.correctly_declined", "score": 0, "comment": FAILED}
        if outputs["decline"] == "off_topic":
            return {"key": "decline_correctness.correctly_declined", "score": 1, "comment": "declined (off_topic)"}
        return {
            "key": "decline_correctness.correctly_declined",
            "score": 0,
            "comment": f"not declined as off-topic: {outputs['decline'] or 'answered'}",
        }
    if reference_outputs["covered"]:
        return not_applicable(CORRECTLY_DECLINED, "the library covers the question: wrongly_declined scores it")
    if inputs["documents"] is None:  # the example's limit: a failed run's outputs have none
        return not_applicable(CORRECTLY_DECLINED, "an unlimited conversation has no relevance gate until US-5 (#14)")
    if "decline" not in outputs:
        return {"key": "decline_correctness.correctly_declined", "score": 0, "comment": FAILED}
    if outputs["decline"] == "limited":
        return {"key": "decline_correctness.correctly_declined", "score": 1, "comment": "declined (limited)"}
    if outputs["decline"]:
        return {
            "key": "decline_correctness.correctly_declined",
            "score": 0,
            "comment": f"declined ({outputs['decline']}), not the limited decline of the listed documents",
        }
    answer = outputs.get("answer") or ""
    return {
        "key": "decline_correctness.correctly_declined",
        "score": 0,
        "comment": f"answered a question the listed documents don't cover: {answer[:120]}",
    }


@scores(WRONGLY_DECLINED)
def wrongly_declined(
    inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
) -> dict[str, Any]:
    if not reference_outputs["covered"]:
        return not_applicable(WRONGLY_DECLINED, "the library doesn't cover the question: correctly_declined scores it")
    if "decline" not in outputs:
        return {"key": "decline_correctness.wrongly_declined", "score": 1, "comment": FAILED}
    if outputs["decline"]:
        return {
            "key": "decline_correctness.wrongly_declined",
            "score": 1,
            "comment": f"declined ({outputs['decline']}) a covered question",
        }
    return {"key": "decline_correctness.wrongly_declined", "score": 0, "comment": "answered"}


SUITE = Suite(dataset="ask", target=ask_target, evaluators=(correctly_declined, wrongly_declined))

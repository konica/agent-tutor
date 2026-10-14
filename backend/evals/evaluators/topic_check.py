"""Topic check (PRD §10.1, spec 2026-10-13 §6.3, code): the classifier alone on the topic_check dataset's held-out
messages. `false_rejections` scores the on-topic examples (1 = declined, a miss); `off_topic_caught` scores the
off-topic ones (1 = declined). The suite is skipped until backend/models/topic_check holds a model."""

from typing import Any

from evals.suite import Suite, not_applicable, scores
from evals.targets import TOPIC_MODEL, topic_check_target

FALSE_REJECTIONS = "topic_check.false_rejections"
OFF_TOPIC_CAUGHT = "topic_check.off_topic_caught"
FAILED = "the run failed before it classified"


@scores(FALSE_REJECTIONS)
def false_rejections(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if reference_outputs["off_topic"]:
        return not_applicable(FALSE_REJECTIONS, "an off-topic example: off_topic_caught scores it")
    if "off_topic" not in outputs:
        return {"key": "topic_check.false_rejections", "score": 1, "comment": FAILED}
    rejected = bool(outputs["off_topic"])
    comment = f"{'declined' if rejected else 'passed'} (p_off_topic {outputs['p_off_topic']:.3f})"
    return {"key": "topic_check.false_rejections", "score": int(rejected), "comment": comment}


@scores(OFF_TOPIC_CAUGHT)
def off_topic_caught(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not reference_outputs["off_topic"]:
        return not_applicable(OFF_TOPIC_CAUGHT, "an on-topic example: false_rejections scores it")
    if "off_topic" not in outputs:
        return {"key": "topic_check.off_topic_caught", "score": 0, "comment": FAILED}
    caught = bool(outputs["off_topic"])
    comment = f"{'declined' if caught else 'missed'} (p_off_topic {outputs['p_off_topic']:.3f})"
    return {"key": "topic_check.off_topic_caught", "score": int(caught), "comment": comment}


def _no_model() -> str | None:
    if (TOPIC_MODEL / "manifest.json").exists():
        return None
    return "no topic-check model in backend/models/topic_check yet (make topic-check-train)"


SUITE = Suite(
    dataset="topic_check",
    target=topic_check_target,
    evaluators=(false_rejections, off_topic_caught),
    skip=_no_model,
)

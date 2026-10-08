"""Subject-detection metrics (PRD §10.1): exactly correct, contains a wrong subject, asked when clear.

Denominators: `exact_set` and `asked_when_clear` average over clear items only (single- and multi-subject);
`contains_wrong` averages over all items, ambiguous ones included, where binding any subset of the straddled
subjects is not wrong.
"""

from collections import defaultdict
from collections.abc import Collection, Iterable, Mapping
from typing import Any

METRICS = ("exact_set", "contains_wrong", "asked_when_clear")


def item_scores(bound: Collection[str] | None, expected: Collection[str], clear: bool) -> dict[str, float]:
    """Scores for one item; `bound=None` means the detector asked. Only the keys that apply are returned."""
    want = set(expected)
    scores = {"contains_wrong": 0.0 if bound is None else float(not set(bound) <= want)}
    if clear:
        scores["exact_set"] = float(bound is not None and set(bound) == want)
        scores["asked_when_clear"] = float(bound is None)
    return scores


def subject_detection(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> list[dict[str, Any]]:
    """LangSmith evaluator. An unsure detection counts as asked, though it still lists the best subject."""
    bound = None if outputs["unsure"] else outputs["subjects"]
    scores = item_scores(bound, reference_outputs["expected_subjects"], reference_outputs["clear"])
    return [{"key": key, "score": score} for key, score in scores.items()]


def summarize(rows: Iterable[Mapping[str, float]]) -> dict[str, float]:
    """Mean per key over the rows that have it."""
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for key, score in row.items():
            values[key].append(score)
    return {key: sum(scores) / len(scores) for key, scores in values.items()}

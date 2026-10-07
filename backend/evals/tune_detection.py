"""Pick detection thresholds: replay labeled per-subject scores through candidate policies (PRD §10.3)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import product

from evals.evaluators.subject_detection import item_scores, summarize
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.domain.detection import DetectionPolicy


@dataclass(frozen=True)
class LabeledScores:
    """One labeled first question: its best chunk score per subject, the right subject set, and whether it is clear."""

    scores: dict[str, float]
    expected: frozenset[str]
    clear: bool


def measure(policy: DetectionPolicy, items: Sequence[LabeledScores]) -> dict[str, float]:
    rows = []
    for item in items:
        bound = policy.bind({SubjectId(k): v for k, v in item.scores.items()})
        rows.append(item_scores(bound, item.expected, item.clear))
    return summarize(rows)


def slack(metrics: Mapping[str, float], targets: Mapping[str, tuple[str, float]]) -> float:
    """Tightest margin to a target; negative when any target is missed."""
    margins = [
        metrics[metric] - value if comparator == "min" else value - metrics[metric]
        for metric, (comparator, value) in targets.items()
    ]
    return min(margins)


def sweep(
    items: Sequence[LabeledScores],
    targets: Mapping[str, tuple[str, float]],
    thresholds: Sequence[float],
    margins: Sequence[float],
    multi_margins: Sequence[float],
) -> list[tuple[DetectionPolicy, dict[str, float], float]]:
    """Every policy in the grid, best first: most slack, then exact_set up, contains_wrong down, then the settings."""
    ranked = []
    for t, m, mm in product(thresholds, margins, multi_margins):
        policy = DetectionPolicy(t, m, mm)
        metrics = measure(policy, items)
        ranked.append((policy, metrics, slack(metrics, targets)))
    ranked.sort(
        key=lambda r: (
            -r[2],
            -r[1].get("exact_set", 0.0),
            r[1].get("contains_wrong", 0.0),
            r[0].detect_threshold,
            r[0].detect_margin,
            r[0].multi_margin,
        )
    )
    return ranked

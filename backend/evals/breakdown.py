"""The gold-evidence metrics broken down by the rows' difficulty and category (spec §7.7).

A flat mean hides which kind of question fails, so the run output also groups each gold metric's scores by a row
metadata field. It is for reading only: the gate never sees it and the exit code doesn't depend on it. The keys are
spelled out here: importing them from the evaluators would pull in the target and the model factory.
"""

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

METRICS = (
    "evidence.retrieved_recall",
    "evidence.cited_recall",
    "evidence.gold_rank",
    "evidence.distractor_cited",
    "answer_correctness",
)
DIMENSIONS = ("difficulty", "category")
# metric -> the scores of its examples, each with the example's row metadata
Labelled = dict[str, list[tuple[float | None, dict[str, Any]]]]
HEADING = "Gold evidence by difficulty and category"
NOTE = "Never gates. evidence.distractor_cited is lower-is-better; the other metrics are higher-is-better."


@dataclass(frozen=True)
class BreakdownRow:
    metric: str
    dimension: str
    value: str
    mean: float
    examples: int


def rows(labelled: Mapping[str, Sequence[tuple[float | None, dict[str, Any]]]]) -> list[BreakdownRow]:
    """Each gold metric's mean per value of each dimension, for the rows that have it. An unscored example is 0."""
    found: list[BreakdownRow] = []
    for metric in METRICS:
        for dimension in DIMENSIONS:
            groups: defaultdict[str, list[float]] = defaultdict(list)
            for score, metadata in labelled.get(metric, []):
                if dimension in metadata:
                    groups[str(metadata[dimension])].append(0.0 if score is None else float(score))
            found += [
                BreakdownRow(metric, dimension, value, sum(got) / len(got), len(got))
                for value, got in sorted(groups.items())
            ]
    return found


def render(found: Sequence[BreakdownRow]) -> str:
    if not found:
        return ""
    table = [("metric", "dimension", "value", "mean", "examples")]
    table += [(r.metric, r.dimension, r.value, f"{r.mean:.3f}", str(r.examples)) for r in found]
    widths = [max(len(line[i]) for line in table) for i in range(5)]
    lines = ["  ".join(cell.ljust(w) for cell, w in zip(line, widths, strict=True)).rstrip() for line in table]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join([f"{HEADING} ({NOTE})", "", *lines])


def render_markdown(found: Sequence[BreakdownRow]) -> str:
    if not found:
        return ""
    lines = [
        f"### {HEADING}",
        "",
        NOTE,
        "",
        "| metric | dimension | value | mean | examples |",
        "|---|---|---|---|---|",
    ]
    lines += [f"| {r.metric} | {r.dimension} | {r.value} | {r.mean:.3f} | {r.examples} |" for r in found]
    return "\n".join(lines)

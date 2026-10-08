"""Pick detection thresholds: replay labeled per-subject scores through candidate policies (PRD §10.3).

Usage: uv run --extra eval python -m evals.tune_detection [--split full|smoke]   (no LangSmith; embeds the questions)
"""

import argparse
import asyncio
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from itertools import product

from langchain_core.embeddings import Embeddings

from evals import gate
from evals.corpus_index import CorpusIndex, SeedCorpusRetriever, subject_id
from evals.detection_dataset import DetectionItem, learner_subjects, load_items
from evals.evaluators.subject_detection import item_scores, summarize
from evals.targets import seed_index, ssm_policy
from smart_tutor.shared.adapters.model_factory import ModelFactory
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.application.subject_detector import DETECTION_K
from smart_tutor.tutoring.domain.detection import DetectionPolicy, best_scores


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


def _frange(start: float, stop: float, step: float) -> list[float]:
    return [round(start + i * step, 6) for i in range(round((stop - start) / step) + 1)]


def labeled_scores(items: Sequence[DetectionItem], index: CorpusIndex, embeddings: Embeddings) -> list[LabeledScores]:
    """Each item's best chunk score per learner subject, searched the way detection searches (one search, K chunks)."""

    def one(item: DetectionItem) -> LabeledScores:
        ids = [subject_id(n) for n in learner_subjects(item, index.documents)]
        retriever = SeedCorpusRetriever(index, item.learner_documents, embeddings)
        chunks = asyncio.run(retriever.search(item.question, ids, DETECTION_K))
        return LabeledScores(
            scores=dict(best_scores(chunks, among=ids)),
            expected=frozenset(subject_id(n) for n in item.expected_subjects),
            clear=item.clear,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        return list(pool.map(one, items))


def _show(policy: DetectionPolicy, metrics: Mapping[str, float], margin: float) -> str:
    shown = " ".join(f"{k}={v:.3f}" for k, v in metrics.items())
    return (
        f"T={policy.detect_threshold:.2f} M={policy.detect_margin:.3f} MM={policy.multi_margin:.3f}  "
        f"{shown}  slack={margin:+.3f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=["smoke", "full"], default="full")
    args = parser.parse_args()
    settings = Settings()
    index = seed_index(settings)
    embeddings = ModelFactory(settings).embedding()
    items = labeled_scores(load_items(args.split), index, embeddings)
    goals = gate.targets(gate.load_thresholds(), "release_1", "subject_detection")
    ranked = sweep(
        items,
        goals,
        _frange(0.20, 0.80, 0.01),
        _frange(0.0, 0.15, 0.005),
        _frange(0.0, 0.10, 0.005),
    )
    print(f"Top 10 of {len(ranked)} policies on {len(items)} {args.split} items (targets {dict(goals)}):")
    for policy, metrics, margin in ranked[:10]:
        print("  " + _show(policy, metrics, margin))
    try:
        current = ssm_policy(settings)
    except Exception as error:  # SSM unreachable or parameters unset: the sweep above still stands
        print(f"Current SSM policy unavailable ({type(error).__name__}: {error})")
        return
    metrics = measure(current, items)
    print("Current SSM policy:")
    print("  " + _show(current, metrics, slack(metrics, goals)))


if __name__ == "__main__":
    main()

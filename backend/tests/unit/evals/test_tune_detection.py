from evals.corpus_index import build_index, subject_id
from evals.detection_dataset import DetectionItem
from evals.seed_corpus.manifest import SeedDocument
from evals.tune_detection import LabeledScores, labeled_scores, measure, slack, sweep
from fakes import FakePdfExtractor, PageChunker, fake_embeddings
from smart_tutor.tutoring.domain.detection import DetectionPolicy

GOAL = {"exact_set": ("min", 0.9), "contains_wrong": ("max", 0.03), "asked_when_clear": ("max", 0.1)}
ITEMS = [
    LabeledScores({"A": 0.60, "B": 0.40}, frozenset({"A"}), True),
    LabeledScores({"A": 0.55, "B": 0.54}, frozenset({"A", "B"}), True),
    LabeledScores({"A": 0.45, "B": 0.44}, frozenset({"A", "B"}), False),
]


def test_labeled_scores_use_subject_ids_and_the_items_expected_set() -> None:
    docs = [
        SeedDocument(i, "arxiv", i, "CC BY 4.0", i * 4, (s,), f"Doc {i}") for i, s in (("a", "Math"), ("b", "Physics"))
    ]
    pages = {"a": "alpha page", "b": "beta page"}
    index = build_index(
        docs, lambda d: f"%PDF-1.4 {pages[d.id]}".encode(), FakePdfExtractor(), PageChunker(), fake_embeddings()
    )
    item = DetectionItem("x", "single", False, ("a", "b"), "alpha page", ("Math",), ())
    [labeled] = labeled_scores([item], index, fake_embeddings())
    assert labeled.expected == frozenset({subject_id("Math")})
    assert labeled.clear is True
    assert set(labeled.scores) == {subject_id("Math"), subject_id("Physics")}


def test_measure_applies_the_policy_to_each_item() -> None:
    metrics = measure(DetectionPolicy(0.5, 0.1, 0.02), ITEMS)
    assert metrics == {"exact_set": 1.0, "contains_wrong": 0.0, "asked_when_clear": 0.0}


def test_measure_counts_a_too_high_threshold_as_asking() -> None:
    assert measure(DetectionPolicy(0.7, 0.1, 0.02), ITEMS)["asked_when_clear"] == 1.0


def test_slack_is_the_tightest_margin_to_a_target() -> None:
    assert slack({"exact_set": 0.95, "contains_wrong": 0.0, "asked_when_clear": 0.05}, GOAL) == 0.03


def test_sweep_ranks_policies_meeting_the_targets_first() -> None:
    ranked = sweep(ITEMS, GOAL, thresholds=[0.5, 0.7], margins=[0.1], multi_margins=[0.0, 0.02])
    best, metrics, best_slack = ranked[0]
    assert best == DetectionPolicy(0.5, 0.1, 0.02) and best_slack >= 0
    assert ranked[-1][2] < 0

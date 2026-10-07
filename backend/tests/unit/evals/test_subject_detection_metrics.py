import pytest

from evals.evaluators.subject_detection import item_scores, subject_detection, summarize


@pytest.mark.parametrize(
    ("bound", "expected", "clear", "scores"),
    [
        (["A"], ["A"], True, {"exact_set": 1.0, "contains_wrong": 0.0, "asked_when_clear": 0.0}),
        (["A", "B"], ["A", "B"], True, {"exact_set": 1.0, "contains_wrong": 0.0, "asked_when_clear": 0.0}),
        (["A"], ["A", "B"], True, {"exact_set": 0.0, "contains_wrong": 0.0, "asked_when_clear": 0.0}),
        (["A", "C"], ["A"], True, {"exact_set": 0.0, "contains_wrong": 1.0, "asked_when_clear": 0.0}),
        (None, ["A"], True, {"exact_set": 0.0, "contains_wrong": 0.0, "asked_when_clear": 1.0}),
        (None, ["A", "B"], False, {"contains_wrong": 0.0}),  # ambiguous: asking is right
        (["A"], ["A", "B"], False, {"contains_wrong": 0.0}),  # a subset of the straddled subjects is not wrong
        (["C"], ["A", "B"], False, {"contains_wrong": 1.0}),
    ],
)
def test_item_scores(bound, expected, clear, scores) -> None:
    assert item_scores(bound, expected, clear) == scores


def test_unsure_counts_as_asked_even_though_the_best_subject_is_listed() -> None:
    results = subject_detection(
        {"subjects": ["A"], "unsure": True, "scores": {"A": 0.4}}, {"expected_subjects": ["A"], "clear": True}
    )
    assert {r["key"]: r["score"] for r in results} == {"exact_set": 0.0, "contains_wrong": 0.0, "asked_when_clear": 1.0}


def test_summarize_averages_each_key_over_the_items_that_have_it() -> None:
    rows = [
        {"exact_set": 1.0, "contains_wrong": 0.0},
        {"exact_set": 0.0, "contains_wrong": 1.0},
        {"contains_wrong": 0.0},
    ]
    assert summarize(rows) == {"exact_set": 0.5, "contains_wrong": pytest.approx(1 / 3)}

"""Decline correctness (PRD §10.1): a limited conversation declines what its documents don't cover, not what they do."""

from typing import Any

from evals.evaluators.decline_correctness import correctly_declined, wrongly_declined
from evals.suite import NOT_APPLICABLE

COVERED = {"covered": True, "sources": ["react-2022"]}
UNCOVERED = {"covered": False, "sources": []}
LIMITED = {"question": "q", "learner": "learner@example.com", "documents": ["react-2022"]}
UNLIMITED = {"question": "q", "learner": "learner@example.com", "documents": None}


def _outputs(decline: str | None, limited: bool = True) -> dict[str, Any]:
    return {"answer": "Some answer text.", "decline": decline, "limit": ["d1"] if limited else None}


def _not_applicable(result: dict[str, Any], key: str) -> bool:
    return result["key"] == key and result["score"] is None and result["value"] == NOT_APPLICABLE


def test_a_limited_conversation_that_declines_an_uncovered_question_scores_1() -> None:
    result = correctly_declined(LIMITED, _outputs("limited"), UNCOVERED)
    assert result["key"] == "decline_correctness.correctly_declined" and result["score"] == 1


def test_a_limited_conversation_that_answers_an_uncovered_question_scores_0_and_quotes_the_answer() -> None:
    result = correctly_declined(LIMITED, _outputs(None), UNCOVERED)
    assert result["score"] == 0 and "Some answer text." in result["comment"]


def test_a_missing_answer_does_not_break_the_comment() -> None:
    result = correctly_declined(LIMITED, {"answer": None, "decline": None, "limit": ["d1"]}, UNCOVERED)
    assert result["score"] == 0


def test_an_unlimited_conversation_has_no_relevance_gate_to_score() -> None:
    result = correctly_declined(UNLIMITED, _outputs(None, limited=False), UNCOVERED)
    assert _not_applicable(result, "decline_correctness.correctly_declined") and "US-5" in result["comment"]


def test_a_covered_question_is_not_scored_by_correctly_declined() -> None:
    result = correctly_declined(LIMITED, _outputs(None), COVERED)
    assert _not_applicable(result, "decline_correctness.correctly_declined")


def test_declining_a_covered_question_scores_1_as_a_wrong_decline() -> None:
    result = wrongly_declined(LIMITED, _outputs("limited"), COVERED)
    assert result["key"] == "decline_correctness.wrongly_declined" and result["score"] == 1


def test_answering_a_covered_question_scores_0_as_a_wrong_decline() -> None:
    assert wrongly_declined(LIMITED, _outputs(None), COVERED)["score"] == 0


def test_an_uncovered_question_is_not_scored_by_wrongly_declined() -> None:
    result = wrongly_declined(LIMITED, _outputs("limited"), UNCOVERED)
    assert _not_applicable(result, "decline_correctness.wrongly_declined")


def test_a_failed_run_counts_against_the_metric_that_applies() -> None:
    missed = correctly_declined(LIMITED, {}, UNCOVERED)
    assert missed["score"] == 0 and "failed" in missed["comment"]
    wrong = wrongly_declined(LIMITED, {}, COVERED)
    assert wrong["score"] == 1 and "failed" in wrong["comment"]
    assert _not_applicable(correctly_declined(LIMITED, {}, COVERED), "decline_correctness.correctly_declined")
    assert _not_applicable(wrongly_declined(LIMITED, {}, UNCOVERED), "decline_correctness.wrongly_declined")


def test_a_failed_run_of_an_unlimited_example_is_not_applicable_to_correctly_declined() -> None:
    result = correctly_declined(UNLIMITED, {}, UNCOVERED)
    assert _not_applicable(result, "decline_correctness.correctly_declined")

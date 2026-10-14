"""Search step ran (PRD §10.1): every turn searches its readable documents, and a limited search stays in its limit."""

from typing import Any

from evals.evaluators.search_step_ran import search_step_ran


def _call(document_ids: list[str] | None, found: list[str], k: int = 5) -> dict[str, Any]:
    return {"tool": "search", "query": "q", "k": k, "document_ids": document_ids, "found": found}


def test_a_library_wide_search_scores_1() -> None:
    result = search_step_ran({"limit": None, "trajectory": [_call(None, ["d1", "d2"])]})
    assert result["key"] == "search_step_ran" and result["score"] == 1


def test_a_limited_search_over_the_listed_documents_scores_1() -> None:
    result = search_step_ran({"limit": ["d1", "d2"], "trajectory": [_call(["d2", "d1"], ["d1"])]})
    assert result["score"] == 1


def test_a_limited_turn_that_searched_the_whole_library_instead_scores_0() -> None:
    result = search_step_ran({"limit": ["d1"], "trajectory": [_call(None, ["d1", "d9"])]})
    assert result["score"] == 0 and "listed" in result["comment"]


def test_a_limited_search_that_found_another_documents_chunks_scores_0() -> None:
    result = search_step_ran({"limit": ["d1"], "trajectory": [_call(["d1"], ["d1", "d9"])]})
    assert result["score"] == 0 and "d9" in result["comment"]


def test_the_library_wide_check_after_an_empty_limited_search_is_allowed() -> None:
    trajectory = [_call(["d1"], []), _call(None, ["d9"], k=1)]
    assert search_step_ran({"limit": ["d1"], "trajectory": trajectory})["score"] == 1


def test_a_turn_without_a_search_scores_0() -> None:
    assert search_step_ran({"limit": None, "trajectory": []})["score"] == 0


def test_a_failed_run_does_not_count_as_a_search() -> None:
    result = search_step_ran({})
    assert result["score"] == 0 and "failed" in result["comment"]


def test_an_off_topic_decline_without_a_search_is_not_applicable() -> None:
    result = search_step_ran({"limit": None, "trajectory": [], "decline": "off_topic"})
    assert result["score"] is None and result["value"] == "n/a"


def test_an_off_topic_decline_that_still_searched_scores_0() -> None:
    result = search_step_ran({"limit": None, "trajectory": [_call(None, ["d1"])], "decline": "off_topic"})
    assert result["score"] == 0 and "off-topic" in result["comment"]

"""The release gate: thresholds.yaml's comparators applied to an experiment's scores (PRD §10.1)."""

from pathlib import Path

import pytest

from evals.gate import Row, Threshold, check, load_thresholds, passed, ran, render, render_markdown

SEARCH = Threshold("search_step_ran", "min", 1.0)
RELEVANCE = Threshold("answer_relevance", "min", 0.85)
FALSE_REJECTIONS = Threshold("subject_name_check.false_rejections", "max", 0.05)
INJECTION = Threshold("injection_resistance", "max_failures", 0)


def _yaml(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "thresholds.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_release_1_flattens_nested_metrics_into_dotted_names() -> None:
    thresholds = load_thresholds("release_1")
    assert SEARCH in thresholds
    assert RELEVANCE in thresholds
    assert FALSE_REJECTIONS in thresholds
    assert INJECTION in thresholds
    assert Threshold("metadata_extraction.authors_f1", "min", 0.85) in thresholds
    assert all(t.metric != "judge_alignment" for t in thresholds)  # another release's table


def test_an_unknown_release_is_refused() -> None:
    with pytest.raises(ValueError, match="release_9"):
        load_thresholds("release_9")


def test_a_metric_with_two_comparators_is_refused(tmp_path: Path) -> None:
    path = _yaml(tmp_path, "release_1:\n  x: {type: code, min: 0.5, max: 0.9}\n")
    with pytest.raises(ValueError, match="x"):
        load_thresholds("release_1", path)


def test_a_metric_without_a_comparator_is_refused(tmp_path: Path) -> None:
    path = _yaml(tmp_path, "release_1:\n  x: {type: code, mn: 0.5}\n")
    with pytest.raises(ValueError, match="x"):
        load_thresholds("release_1", path)


def test_min_passes_at_the_target_and_fails_below_it() -> None:
    at, below = check([RELEVANCE], {"answer_relevance": [0.8, 0.9]}), check([RELEVANCE], {"answer_relevance": [0.8]})
    assert at == [Row("answer_relevance", "pass", RELEVANCE, pytest.approx(0.85), 2)]
    assert below[0].status == "fail"


def test_max_passes_at_the_target_and_fails_above_it() -> None:
    assert check([FALSE_REJECTIONS], {FALSE_REJECTIONS.metric: [0.05]})[0].status == "pass"
    assert check([FALSE_REJECTIONS], {FALSE_REJECTIONS.metric: [0.0, 0.2]})[0].status == "fail"


def test_max_failures_counts_examples_scoring_below_1() -> None:
    clean = check([INJECTION], {"injection_resistance": [True, 1, 1.0]})
    one = check([INJECTION], {"injection_resistance": [1.0, False]})
    assert clean[0].status == "pass" and clean[0].observed == 0
    assert one[0].status == "fail" and one[0].observed == 1


def test_a_missing_score_counts_as_zero() -> None:
    rows = check([SEARCH], {"search_step_ran": [1.0, None]})
    assert rows[0].status == "fail" and rows[0].observed == pytest.approx(0.5) and rows[0].examples == 2


def test_a_metric_no_suite_scored_is_not_run_and_does_not_fail_the_gate() -> None:
    rows = check([SEARCH, INJECTION], {"search_step_ran": [1.0]})
    assert rows[1] == Row("injection_resistance", "not run", INJECTION, None, 0)
    assert passed(rows) and ran(rows)


def test_nothing_scored_means_nothing_ran() -> None:
    assert not ran(check([SEARCH], {}))


def test_a_score_without_a_threshold_is_reported_and_does_not_fail_the_gate() -> None:
    rows = check([SEARCH], {"search_step_ran": [1.0], "serch_step_ran": [0.0]})
    assert rows[1] == Row("serch_step_ran", "no threshold", None, 0.0, 1)
    assert passed(rows)


def test_one_breach_fails_the_gate() -> None:
    assert not passed(check([SEARCH, RELEVANCE], {"search_step_ran": [1.0], "answer_relevance": [0.5]}))


def test_the_table_shows_each_metric_its_target_and_result_then_the_experiment_links() -> None:
    rows = check([SEARCH, RELEVANCE, INJECTION], {"search_step_ran": [1.0], "answer_relevance": [0.5]})
    text = render(rows, {"smart-tutor-ask (smoke smoke-v1)": "https://smith.langchain.com/x"})
    lines = text.splitlines()
    assert any("search_step_ran" in line and ">= 1.00" in line and "1.000" in line and "PASS" in line for line in lines)
    assert any("answer_relevance" in line and "0.500" in line and "FAIL" in line for line in lines)
    assert any("injection_resistance" in line and "<= 0 failures" in line and "not run" in line for line in lines)
    assert "smart-tutor-ask (smoke smoke-v1): https://smith.langchain.com/x" in text
    assert lines[-1].startswith("Gate: FAIL")


def test_the_markdown_table_links_each_experiment_and_says_the_verdict() -> None:
    rows = check([SEARCH, RELEVANCE, INJECTION], {"search_step_ran": [1.0], "answer_relevance": [0.5]})
    text = render_markdown(rows, {"smart-tutor-ask (smoke smoke-v1)": "https://smith.langchain.com/x"}, "Smoke evals")
    lines = text.splitlines()
    assert lines[0] == "### Smoke evals: FAIL (1 passed, 1 failed, 1 not run)"
    assert "| metric | target | observed | examples | result |" in lines
    assert "| search_step_ran | >= 1.00 | 1.000 | 1 | PASS |" in lines
    assert "| answer_relevance | >= 0.85 | 0.500 | 1 | **FAIL** |" in lines
    assert "| injection_resistance | <= 0 failures | - | 0 | not run |" in lines
    assert "- [smart-tutor-ask (smoke smoke-v1)](https://smith.langchain.com/x)" in lines


def test_an_experiment_without_a_url_is_named_not_linked() -> None:
    rows = check([SEARCH], {"search_step_ran": [1.0]})
    text = render_markdown(rows, {"smart-tutor-ask (smoke smoke-v1)": "smart-tutor-ask-smoke-1a2b"}, "Smoke evals")
    assert "- smart-tutor-ask (smoke smoke-v1): smart-tutor-ask-smoke-1a2b" in text.splitlines()

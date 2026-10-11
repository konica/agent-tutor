"""Suites: evaluator modules with a SUITE, discovered by the runner and grouped by dataset."""

import pytest

from evals.evaluators import answer_relevance, search_step_ran
from evals.suite import DatasetSuites, Suite, by_dataset, discover
from evals.targets import ask_target


def test_every_evaluator_module_with_a_suite_is_discovered() -> None:
    suites = discover()
    assert search_step_ran.SUITE in suites and answer_relevance.SUITE in suites


def test_suites_on_one_dataset_share_one_experiment() -> None:
    groups = by_dataset([search_step_ran.SUITE, answer_relevance.SUITE])
    assert groups == [
        DatasetSuites("ask", ask_target, (search_step_ran.search_step_ran, answer_relevance.answer_relevance))
    ]


def test_suites_on_different_datasets_run_apart() -> None:
    def other_target():  # pragma: no cover - never called
        raise AssertionError

    other = Suite("describe", other_target, (search_step_ran.search_step_ran,))
    assert [g.dataset for g in by_dataset([search_step_ran.SUITE, other])] == ["ask", "describe"]


def test_one_dataset_with_two_targets_is_refused() -> None:
    def other_target():  # pragma: no cover - never called
        raise AssertionError

    with pytest.raises(ValueError, match="ask"):
        by_dataset([search_step_ran.SUITE, Suite("ask", other_target, ())])

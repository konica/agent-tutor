"""Suites: evaluator modules with a SUITE, discovered by the runner and grouped by dataset."""

import pytest

from evals.evaluators import answer_relevance, search_step_ran
from evals.suite import DatasetSuites, Suite, by_dataset, discover, metric_of
from evals.targets import ask_target


def test_every_evaluator_module_with_a_suite_is_discovered() -> None:
    suites = discover()
    assert search_step_ran.SUITE in suites and answer_relevance.SUITE in suites


def test_every_evaluator_declares_the_metric_it_scores() -> None:
    # without it, an evaluator that raised on every example would read as "not run" and pass the gate
    for suite in discover():
        for evaluator in suite.evaluators:
            metric = metric_of(evaluator)
            assert metric is not None, evaluator
            assert metric.split(".")[-1] == evaluator.__name__, (metric, evaluator.__name__)


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


def test_a_datasets_suites_carry_the_first_skip() -> None:
    def target():  # pragma: no cover - never called
        raise AssertionError

    def skip() -> str | None:
        return "not ready"

    [group] = by_dataset([Suite("d", target, ()), Suite("d", target, (), skip=skip)])
    assert group.skip is skip

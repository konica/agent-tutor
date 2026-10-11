"""The runner: one LangSmith experiment per dataset with the split, then the gate decides the exit code."""

from typing import Any

import pytest

from evals.dataset import Dataset, Example, Split
from evals.run import main, run_split
from evals.suite import DatasetSuites, Suite
from fakes.langsmith import FakeLangSmith

ASK = Dataset(
    "ask",
    "smart-tutor-ask",
    "",
    {
        "smoke": Split(
            "smoke",
            "smoke-v1",
            (Example({"question": "a"}, {"covered": True}), Example({"question": "b"}, {"covered": False})),
        )
    },
)


def make_target():
    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        return {"answer": f"about {inputs['question']}"}

    return target


def scored(key: str, score: float):
    def evaluator(outputs: dict[str, Any]) -> dict[str, Any]:
        return {"key": key, "score": score, "comment": "fixed"}

    return evaluator


async def test_suites_on_one_dataset_run_as_one_experiment_on_the_versioned_split() -> None:
    client = FakeLangSmith()
    group = DatasetSuites("ask", make_target, (scored("search_step_ran", 1.0), scored("answer_relevance", 0.9)))
    scores, links = await run_split(client, [group], "smoke", load=lambda key: ASK, metadata={"agent_model": "m"})
    assert scores == {"search_step_ran": [1.0, 1.0], "answer_relevance": [0.9, 0.9]}
    assert len(client.experiments) == 1
    experiment = client.experiments[0]
    assert experiment.prefix == "smart-tutor-ask-smoke"
    assert experiment.metadata == {"agent_model": "m", "split": "smoke", "dataset_version": "smoke-v1"}
    assert links == {"smart-tutor-ask (smoke smoke-v1)": "https://smith.example/smart-tutor-ask-smoke-1"}


async def test_a_dataset_without_the_split_runs_nothing() -> None:
    client = FakeLangSmith()
    group = DatasetSuites("ask", make_target, (scored("search_step_ran", 1.0),))
    scores, links = await run_split(client, [group], "full", load=lambda key: ASK)
    assert scores == {} and links == {} and client.experiments == []


def _suites(score: float) -> list[Suite]:
    return [
        Suite("ask", make_target, (scored("search_step_ran", 1.0),)),
        Suite("ask", make_target, (scored("answer_relevance", score),)),
    ]


def test_a_passing_run_exits_0_and_prints_the_table_with_the_link(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--split", "smoke"], client=FakeLangSmith(), suites=_suites(0.9), load=lambda key: ASK)
    out = capsys.readouterr().out
    assert code == 0
    assert "https://smith.example/smart-tutor-ask-smoke-1" in out
    assert "injection_resistance" in out and "not run" in out


def test_a_breached_threshold_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--split", "smoke"], client=FakeLangSmith(), suites=_suites(0.5), load=lambda key: ASK)
    assert code == 1
    assert "FAIL" in capsys.readouterr().out


def test_a_split_no_suite_has_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--split", "full"], client=FakeLangSmith(), suites=_suites(0.9), load=lambda key: ASK)
    assert code == 1
    assert "full" in capsys.readouterr().err

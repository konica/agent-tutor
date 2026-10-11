"""The runner: one LangSmith experiment per dataset with the split, then the gate decides the exit code."""

from pathlib import Path
from typing import Any

import pytest
from langsmith.utils import LangSmithError

from evals.dataset import Dataset, Example, Split
from evals.learners import LoadError
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


async def test_a_callable_object_target_runs_as_a_coroutine_function() -> None:
    class ObjectTarget:
        async def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
            return {"answer": inputs["question"]}

    group = DatasetSuites("ask", ObjectTarget, (scored("search_step_ran", 1.0),))
    scores, _ = await run_split(FakeLangSmith(), [group], "smoke", load=lambda key: ASK)
    assert scores == {"search_step_ran": [1.0, 1.0]}


def _flaky_relevance(inputs: dict[str, Any]) -> dict[str, Any]:
    if inputs["question"] == "b":
        raise RuntimeError("judge failed")
    return {"key": "answer_relevance", "score": 0.9, "comment": ""}


async def test_an_example_whose_evaluator_raised_counts_as_unscored() -> None:
    group = DatasetSuites("ask", make_target, (_flaky_relevance,))
    scores, _ = await run_split(FakeLangSmith(), [group], "smoke", load=lambda key: ASK)
    assert scores == {"answer_relevance": [0.9, None]}


def test_a_run_where_an_evaluator_raised_fails_the_gate(capsys: pytest.CaptureFixture[str]) -> None:
    suites = [Suite("ask", make_target, (scored("search_step_ran", 1.0), _flaky_relevance))]
    assert main(["--split", "smoke"], client=FakeLangSmith(), suites=suites, load=lambda key: ASK) == 1


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


def test_a_suite_that_scored_nothing_says_so_too(capsys: pytest.CaptureFixture[str]) -> None:
    def broken(inputs: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("judge failed")

    code = main(
        ["--split", "smoke"],
        client=FakeLangSmith(),
        suites=[Suite("ask", make_target, (broken,))],
        load=lambda key: ASK,
    )
    assert code == 1
    assert "every evaluator failed" in capsys.readouterr().err


def test_a_target_that_cannot_start_stops_the_run_before_any_experiment(capsys: pytest.CaptureFixture[str]) -> None:
    def unloaded():
        raise LoadError("learner@example.com doesn't hold x (make evals-learners)")

    client = FakeLangSmith()
    code = main(
        ["--split", "smoke"], client=client, suites=[Suite("ask", unloaded, (scored("a", 1.0),))], load=lambda key: ASK
    )
    assert code == 1
    assert "make evals-learners" in capsys.readouterr().err
    assert client.experiments == []


@pytest.mark.parametrize("release", ["release_9", "judge_alignment"])
def test_a_release_that_is_not_in_thresholds_exits_1(release: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["--split", "smoke", "--release", release], client=FakeLangSmith(), suites=_suites(0.9), load=lambda key: ASK
    )
    assert code == 1
    assert release in capsys.readouterr().err


def test_a_missing_langsmith_key_exits_1_with_a_hint(capsys: pytest.CaptureFixture[str]) -> None:
    class NoKey(FakeLangSmith):
        def has_dataset(self, *, dataset_name: str) -> bool:
            raise LangSmithError("Authentication failed")

    code = main(["--split", "smoke"], client=NoKey(), suites=_suites(0.9), load=lambda key: ASK)
    assert code == 1
    assert "LANGSMITH_API_KEY" in capsys.readouterr().err


def test_a_summary_file_gets_the_markdown_table(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n", encoding="utf-8")
    code = main(
        ["--split", "smoke", "--summary", str(summary)],
        client=FakeLangSmith(),
        suites=_suites(0.5),
        load=lambda key: ASK,
    )
    text = summary.read_text(encoding="utf-8")
    assert code == 1
    assert text.startswith("earlier step\n")  # appended, never overwritten
    assert "### Smoke evals: FAIL" in text
    assert "(https://smith.example/smart-tutor-ask-smoke-1)" in text


def test_a_run_that_stops_early_says_why_in_the_summary(tmp_path: Path) -> None:
    class NoKey(FakeLangSmith):
        def has_dataset(self, *, dataset_name: str) -> bool:
            raise LangSmithError("Authentication failed")

    summary = tmp_path / "summary.md"
    code = main(
        ["--split", "smoke", "--summary", str(summary)], client=NoKey(), suites=_suites(0.9), load=lambda key: ASK
    )
    assert code == 1
    assert "LANGSMITH_API_KEY" in summary.read_text(encoding="utf-8")


def test_a_run_where_nothing_ran_says_so_in_the_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    code = main(
        ["--split", "full", "--summary", str(summary)],
        client=FakeLangSmith(),
        suites=_suites(0.9),
        load=lambda key: ASK,
    )
    assert code == 1
    assert "Nothing ran" in summary.read_text(encoding="utf-8")

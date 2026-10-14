"""The runner: one Langfuse experiment (a dataset run) per dataset with the split, then the gate decides the exit
code."""

from pathlib import Path
from typing import Any

import pytest

from evals.dataset import Dataset, Example, publish_split
from evals.langfuse_client import LangfuseError, Score
from evals.learners import LoadError
from evals.run import main, run_split
from evals.suite import DatasetSuites, Suite, not_applicable, scores
from fakes.langfuse import FakeLangfuse

ASK = Dataset(
    "ask",
    "smart-tutor-ask",
    "",
    (Example({"question": "a"}, {"covered": True}), Example({"question": "b"}, {"covered": False})),
)
LINK = "https://langfuse.example/datasets/smart-tutor-ask/smoke-v1/runs/1"


def published() -> FakeLangfuse:
    """A Langfuse holding smoke-v1 of ASK."""
    client = FakeLangfuse()
    publish_split(client, ASK, "smoke", ASK.examples)
    return client


def make_target():
    async def target(inputs: dict[str, Any]) -> dict[str, Any]:
        return {"answer": f"about {inputs['question']}"}

    return target


def scored(key: str, score: float):
    def evaluator(outputs: dict[str, Any]) -> dict[str, Any]:
        return {"key": key, "score": score, "comment": "fixed"}

    return evaluator


def test_suites_on_one_dataset_run_as_one_experiment_on_the_versioned_split() -> None:
    client = published()
    group = DatasetSuites("ask", make_target, (scored("search_step_ran", 1.0), scored("answer_relevance", 0.9)))
    scores, links = run_split(
        client, [group], "smoke", run_name="local run", load=lambda key: ASK, metadata={"agent_model": "m"}
    )
    assert scores == {"search_step_ran": [1.0, 1.0], "answer_relevance": [0.9, 0.9]}
    [run] = client.runs
    assert run.dataset == "smart-tutor-ask/smoke-v1" and run.name == "local run"
    assert run.metadata == {"agent_model": "m", "split": "smoke", "dataset_version": "smoke-v1"}
    assert links == {"smart-tutor-ask (smoke smoke-v1)": LINK}


def test_each_item_is_scored_in_langfuse_with_its_comment_and_not_applicable_results_left_out() -> None:
    client = published()
    group = DatasetSuites("ask", make_target, (_declines,))
    run_split(client, [group], "smoke", run_name="r", load=lambda key: ASK)
    assert client.runs[0].scores == [[], [Score("decline_correctness.correctly_declined", 1.0, "declined")]]


def test_a_callable_object_target_runs() -> None:
    class ObjectTarget:
        async def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
            return {"answer": inputs["question"]}

    group = DatasetSuites("ask", ObjectTarget, (scored("search_step_ran", 1.0),))
    scores, _ = run_split(published(), [group], "smoke", run_name="r", load=lambda key: ASK)
    assert scores == {"search_step_ran": [1.0, 1.0]}


def test_an_example_whose_target_raised_is_scored_as_a_failed_run() -> None:
    def make_failing():
        async def target(inputs: dict[str, Any]) -> dict[str, Any]:
            if inputs["question"] == "b":
                raise RuntimeError("MCP is down")
            return {"answer": "fine"}

        return target

    def answered(outputs: dict[str, Any]) -> dict[str, Any]:
        return {"key": "search_step_ran", "score": int("answer" in outputs), "comment": ""}

    client = published()
    scores, _ = run_split(
        client, [DatasetSuites("ask", make_failing, (answered,))], "smoke", run_name="r", load=lambda key: ASK
    )
    assert scores == {"search_step_ran": [1, 0]}
    assert client.runs[0].outputs[1] == {"error": "RuntimeError: MCP is down"}


def _flaky_relevance(inputs: dict[str, Any]) -> dict[str, Any]:
    if inputs["question"] == "b":
        raise RuntimeError("judge failed")
    return {"key": "answer_relevance", "score": 0.9, "comment": ""}


def test_an_example_whose_evaluator_raised_counts_as_unscored() -> None:
    group = DatasetSuites("ask", make_target, (_flaky_relevance,))
    scores, _ = run_split(published(), [group], "smoke", run_name="r", load=lambda key: ASK)
    assert scores == {"answer_relevance": [0.9, None]}


@scores("answer_relevance")
async def _judge_down(inputs: dict[str, Any]) -> dict[str, Any]:
    raise RuntimeError("AccessDeniedException")


def test_a_declared_metric_whose_evaluator_raised_on_every_example_is_unscored_not_absent() -> None:
    group = DatasetSuites("ask", make_target, (_judge_down,))
    scores_, _ = run_split(published(), [group], "smoke", run_name="r", load=lambda key: ASK)
    assert scores_ == {"answer_relevance": [None, None]}


def test_a_judge_that_fails_on_every_example_fails_the_gate(capsys: pytest.CaptureFixture[str]) -> None:
    suites = [Suite("ask", make_target, (scored("search_step_ran", 1.0), _judge_down))]
    assert main(["--split", "smoke"], client=published(), suites=suites, load=lambda key: ASK) == 1
    assert "FAIL" in capsys.readouterr().out


def test_a_run_where_an_evaluator_raised_fails_the_gate(capsys: pytest.CaptureFixture[str]) -> None:
    suites = [Suite("ask", make_target, (scored("search_step_ran", 1.0), _flaky_relevance))]
    assert main(["--split", "smoke"], client=published(), suites=suites, load=lambda key: ASK) == 1


def _declines(inputs: dict[str, Any]) -> dict[str, Any]:
    if inputs["question"] == "a":
        return not_applicable("decline_correctness.correctly_declined", "covered")
    return {"key": "decline_correctness.correctly_declined", "score": 1, "comment": "declined"}


def test_a_not_applicable_result_is_left_out_of_its_metric() -> None:
    group = DatasetSuites("ask", make_target, (_declines,))
    scores, _ = run_split(published(), [group], "smoke", run_name="r", load=lambda key: ASK)
    assert scores == {"decline_correctness.correctly_declined": [1]}


def _declines_or_raises(inputs: dict[str, Any]) -> dict[str, Any]:
    if inputs["question"] == "a":
        return not_applicable("decline_correctness.correctly_declined", "covered")
    raise RuntimeError("evaluator failed")


def test_a_raise_beside_a_not_applicable_result_leaves_one_unscored_example() -> None:
    group = DatasetSuites("ask", make_target, (_declines_or_raises,))
    scores, _ = run_split(published(), [group], "smoke", run_name="r", load=lambda key: ASK)
    assert scores == {"decline_correctness.correctly_declined": [None]}


def test_a_metric_that_applied_to_no_example_is_not_run() -> None:
    group = DatasetSuites("ask", make_target, (lambda inputs: not_applicable("answer_relevance", "n/a"),))
    scores, _ = run_split(published(), [group], "smoke", run_name="r", load=lambda key: ASK)
    assert scores == {}


def test_a_dataset_without_the_split_runs_nothing() -> None:
    client = published()
    group = DatasetSuites("ask", make_target, (scored("search_step_ran", 1.0),))
    scores, links = run_split(client, [group], "full", run_name="r", load=lambda key: ASK)
    assert scores == {} and links == {} and client.runs == []


def test_the_newest_version_runs_and_its_tag_is_recorded() -> None:
    client = published()
    publish_split(client, ASK, "smoke", (*ASK.examples, Example({"question": "c"}, {"covered": True})))
    group = DatasetSuites("ask", make_target, (scored("search_step_ran", 1.0),))
    scores, links = run_split(client, [group], "smoke", run_name="r", load=lambda key: ASK)
    assert scores == {"search_step_ran": [1.0, 1.0, 1.0]}
    assert client.runs[0].dataset == "smart-tutor-ask/smoke-v2"
    assert client.runs[0].metadata["dataset_version"] == "smoke-v2"
    assert "smart-tutor-ask (smoke smoke-v2)" in links


def test_a_pinned_version_runs_instead_of_the_newest() -> None:
    client = published()
    publish_split(client, ASK, "smoke", (*ASK.examples, Example({"question": "c"}, {"covered": True})))
    pinned = Dataset("ask", "smart-tutor-ask", "", ASK.examples, {"smoke": "smoke-v1"})
    group = DatasetSuites("ask", make_target, (scored("search_step_ran", 1.0),))
    scores, _ = run_split(client, [group], "smoke", run_name="r", load=lambda key: pinned)
    assert scores == {"search_step_ran": [1.0, 1.0]}
    assert client.runs[0].dataset == "smart-tutor-ask/smoke-v1"


def test_a_split_never_published_says_how_to_publish_it(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--split", "full"], client=published(), suites=_suites(0.9), load=lambda key: ASK)
    assert code == 1
    assert "make evals-publish" in capsys.readouterr().err


def test_a_pin_to_a_missing_version_stops_the_run_before_any_experiment(capsys: pytest.CaptureFixture[str]) -> None:
    client = published()
    pinned = Dataset("ask", "smart-tutor-ask", "", ASK.examples, {"smoke": "smoke-v9"})
    code = main(["--split", "smoke"], client=client, suites=_suites(0.9), load=lambda key: pinned)
    assert code == 1
    assert "smoke-v9" in capsys.readouterr().err
    assert client.runs == []


def _suites(score: float) -> list[Suite]:
    return [
        Suite("ask", make_target, (scored("search_step_ran", 1.0),)),
        Suite("ask", make_target, (scored("answer_relevance", score),)),
    ]


def test_a_passing_run_exits_0_and_prints_the_table_with_the_link(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--split", "smoke"], client=published(), suites=_suites(0.9), load=lambda key: ASK)
    out = capsys.readouterr().out
    assert code == 0
    assert LINK in out
    assert "injection_resistance" in out and "not run" in out


def test_a_breached_threshold_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    client = published()
    code = main(["--split", "smoke"], client=client, suites=_suites(0.5), load=lambda key: ASK)
    assert code == 1
    assert "FAIL" in capsys.readouterr().out
    assert len(client.runs) == 1  # the experiment is in Langfuse either way


def test_the_run_is_named_and_recorded_with_its_environment_and_models() -> None:
    client = published()
    main(["--split", "smoke", "--environment", "ci"], client=client, suites=_suites(0.9), load=lambda key: ASK)
    [run] = client.runs
    assert run.name.startswith("ci ") and run.name.endswith("Z")
    assert run.metadata["environment"] == "ci"
    assert {"agent_model", "judge_model"} <= set(run.metadata)


def test_a_run_is_local_unless_told_otherwise() -> None:
    client = published()
    main(["--split", "smoke"], client=client, suites=_suites(0.9), load=lambda key: ASK)
    assert client.runs[0].metadata["environment"] == "local"


def test_a_split_no_suite_has_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--split", "full"], client=published(), suites=_suites(0.9), load=lambda key: ASK)
    assert code == 1
    assert "full" in capsys.readouterr().err


def test_a_suite_that_scored_nothing_says_so_too(capsys: pytest.CaptureFixture[str]) -> None:
    def broken(inputs: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("judge failed")

    code = main(
        ["--split", "smoke"],
        client=published(),
        suites=[Suite("ask", make_target, (broken,))],
        load=lambda key: ASK,
    )
    assert code == 1
    assert "every evaluator failed" in capsys.readouterr().err


def test_a_target_that_cannot_start_stops_the_run_before_any_experiment(capsys: pytest.CaptureFixture[str]) -> None:
    def unloaded():
        raise LoadError("learner@example.com doesn't hold x (make evals-learners)")

    client = published()
    code = main(
        ["--split", "smoke"], client=client, suites=[Suite("ask", unloaded, (scored("a", 1.0),))], load=lambda key: ASK
    )
    assert code == 1
    assert "make evals-learners" in capsys.readouterr().err
    assert client.runs == []


@pytest.mark.parametrize("release", ["release_9", "judge_alignment"])
def test_a_release_that_is_not_in_thresholds_exits_1(release: str, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        ["--split", "smoke", "--release", release], client=published(), suites=_suites(0.9), load=lambda key: ASK
    )
    assert code == 1
    assert release in capsys.readouterr().err


class Unreachable(FakeLangfuse):
    def dataset_names(self) -> list[str]:
        raise LangfuseError("401: Invalid credentials")


def test_a_langfuse_failure_exits_1_with_a_hint(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["--split", "smoke"], client=Unreachable(), suites=_suites(0.9), load=lambda key: ASK)
    assert code == 1
    err = capsys.readouterr().err
    assert "401: Invalid credentials" in err and "LANGFUSE_PUBLIC_KEY" in err and "18:00" in err


def test_missing_langfuse_keys_exit_1_with_a_hint(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert main(["--split", "smoke"], suites=_suites(0.9), load=lambda key: ASK) == 1
    assert "LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY not set" in capsys.readouterr().err


def test_a_summary_file_gets_the_markdown_table(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    summary.write_text("earlier step\n", encoding="utf-8")
    code = main(
        ["--split", "smoke", "--summary", str(summary)],
        client=published(),
        suites=_suites(0.5),
        load=lambda key: ASK,
    )
    text = summary.read_text(encoding="utf-8")
    assert code == 1
    assert text.startswith("earlier step\n")  # appended, never overwritten
    assert "### Smoke evals: FAIL" in text
    assert f"({LINK})" in text


def test_a_run_that_stops_early_says_why_in_the_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    code = main(
        ["--split", "smoke", "--summary", str(summary)], client=Unreachable(), suites=_suites(0.9), load=lambda key: ASK
    )
    assert code == 1
    assert "LANGFUSE_PUBLIC_KEY" in summary.read_text(encoding="utf-8")


def test_a_run_where_nothing_ran_says_so_in_the_summary(tmp_path: Path) -> None:
    summary = tmp_path / "summary.md"
    code = main(
        ["--split", "full", "--summary", str(summary)],
        client=published(),  # smoke only: full has no version
        suites=_suites(0.9),
        load=lambda key: ASK,
    )
    assert code == 1
    assert "Nothing ran" in summary.read_text(encoding="utf-8")


def test_a_suite_that_is_not_ready_is_skipped_and_its_metrics_stay_not_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = published()
    group = DatasetSuites("ask", make_target, (scored("search_step_ran", 1.0),), skip=lambda: "no model yet")
    scores, links = run_split(client, [group], "smoke", run_name="r", load=lambda key: ASK)
    assert scores == {} and links == {} and client.runs == []
    assert "no model yet" in capsys.readouterr().err


def test_a_dataset_that_opts_out_of_a_split_is_skipped_without_asking_to_publish(
    capsys: pytest.CaptureFixture[str],
) -> None:
    full_only = Dataset("ask", "smart-tutor-ask", "", ASK.examples, splits=("full",))
    group = DatasetSuites("ask", make_target, (scored("search_step_ran", 1.0),))
    scores, links = run_split(published(), [group], "smoke", run_name="r", load=lambda key: full_only)
    assert scores == {} and links == {}
    err = capsys.readouterr().err
    assert "opts out" in err and "publish" not in err

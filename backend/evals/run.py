"""Run an evaluation split as Langfuse experiments and check the scores against thresholds.yaml (PRD §10).

Usage: uv run --env-file ../.env --extra eval python -m evals.run --split smoke|full
    [--release release_1] [--environment local|ci] [--summary PATH]

Every suite in evaluators/ whose dataset has a published version of the split runs, on its newest version unless the
dataset file pins one; suites on one dataset share one experiment. An experiment is a dataset run on that version in
the smart-tutor-evals project (ADR 0023), named after the environment and the time it started, with each example's
run traced and its scores on the trace. The gate prints each of the release's metrics as pass, fail, or not run, with
the experiments' links, and the run exits 1 when a metric fails or when nothing ran. --summary appends the same table
as Markdown to a file (GitHub's $GITHUB_STEP_SUMMARY). Needs the local stack with the eval learners loaded
(make evals-learners), your AWS profile (agent and judge models), and a key pair of smart-tutor-evals
(LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_BASE_URL).
"""

import argparse
import inspect
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from evals.dataset import Dataset, DatasetError, load_dataset, version_name, version_to_run
from evals.gate import check, load_thresholds, passed, ran, render, render_markdown
from evals.langfuse_client import ItemEvaluator, LangfuseClient, LangfuseError, Score, SdkLangfuse, Task
from evals.learners import LoadError
from evals.suite import NOT_APPLICABLE, DatasetSuites, Evaluator, Suite, by_dataset, discover
from evals.targets import Target
from smart_tutor.shared.config import Settings

MAX_CONCURRENCY = 4  # examples in flight; Bedrock throttling backs off in the models' boto config
HOST_HOURS = "the host is off 18:00–07:00 Asia/Ho_Chi_Minh"


@dataclass(frozen=True)
class _Result:
    key: str
    score: float | None  # None when not applicable, or when the evaluator gave no score
    applicable: bool


def _failure_scored(target: Target) -> Task:
    """The target, with a failure as outputs the evaluators score as a failed run (each fails closed when its outputs
    are missing). Langfuse would drop the example instead, and the gate would average only the survivors."""

    async def run(inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            return await target(inputs)
        except Exception as e:
            print(f"An example failed: {type(e).__name__}: {e}", file=sys.stderr)
            return {"error": f"{type(e).__name__}: {e}"}

    return run


def _recorded(evaluator: Evaluator, results: list[_Result | None]) -> ItemEvaluator:
    """The evaluator as Langfuse runs it: called with the arguments its parameters name, its score posted on the
    example's trace, and every result appended to `results` (None when it raised), because Langfuse keeps neither a
    not-applicable result nor the key of an evaluator that raised."""
    wanted = set(inspect.signature(evaluator).parameters)

    async def evaluate(
        inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
    ) -> list[Score]:
        given = {"inputs": inputs, "outputs": outputs, "reference_outputs": reference_outputs}
        try:
            found = evaluator(**{k: v for k, v in given.items() if k in wanted})
            if inspect.isawaitable(found):
                found = await found
            applicable = found.get("value") != NOT_APPLICABLE
            score = found.get("score") if applicable else None
            result = _Result(found["key"], None if score is None else float(score), applicable)
        except Exception:
            results.append(None)
            raise
        results.append(result)
        return [] if result.score is None else [Score(result.key, result.score, found.get("comment"))]

    evaluate.__name__ = evaluate.__qualname__ = getattr(evaluator, "__name__", type(evaluator).__name__)
    return evaluate


def _scores(results: Sequence[_Result | None]) -> dict[str, list[float | None]]:
    """One evaluator's scores by metric. An example it raised on counts as unscored (None) under each metric it
    scored elsewhere, not as absent, or the gate would average only the survivors. A not-applicable result is left
    out of its metric."""
    scores: defaultdict[str, list[float | None]] = defaultdict(list)
    for key in {r.key for r in results if r is not None}:
        for result in results:
            if result is None:
                scores[key].append(None)
            elif result.key == key and result.applicable:
                scores[key].append(result.score)
    return dict(scores)


def run_split(
    client: LangfuseClient,
    groups: Sequence[DatasetSuites],
    split: str,
    *,
    run_name: str,
    load: Callable[[str], Dataset] = load_dataset,
    metadata: Mapping[str, str] | None = None,
) -> tuple[dict[str, list[float | None]], dict[str, str]]:
    """Each metric's scores, one per example, and each experiment's link."""
    scores: defaultdict[str, list[float | None]] = defaultdict(list)
    links: dict[str, str] = {}
    for group in groups:
        dataset = load(group.dataset)
        if split not in dataset.splits:
            print(f"{dataset.name} has no {split} split (its file opts out)", file=sys.stderr)
            continue
        if group.skip is not None and (why := group.skip()) is not None:  # its metrics stay "not run"
            print(f"{dataset.name} skipped: {why}", file=sys.stderr)
            continue
        version = version_to_run(client, dataset, split)
        if version is None:  # its metrics stay "not run"
            print(f"{dataset.name} has no {split} version yet: publish one (make evals-publish)", file=sys.stderr)
            continue
        results: list[list[_Result | None]] = [[] for _ in group.evaluators]
        links[f"{dataset.name} ({split} {version})"] = client.run_experiment(
            version_name(dataset, version),
            run_name=run_name,
            description=f"{split} evals on {version_name(dataset, version)}",
            metadata={**(metadata or {}), "split": split, "dataset_version": version},
            task=_failure_scored(group.target()),
            evaluators=[_recorded(e, r) for e, r in zip(group.evaluators, results, strict=True)],
            max_concurrency=MAX_CONCURRENCY,
        )
        for evaluator_results in results:
            for key, found in _scores(evaluator_results).items():
                scores[key] += found
    return dict(scores), links


def _append(path: Path | None, text: str) -> None:
    if path is not None:
        with path.open("a", encoding="utf-8") as f:
            f.write(text + "\n")


def _stop(summary: Path | None, message: str) -> int:
    """Say why the run stopped, on stderr and in the job summary."""
    print(message, file=sys.stderr)
    _append(summary, f"**{message}**")
    return 1


def main(
    argv: Sequence[str] | None = None,
    *,
    client: LangfuseClient | None = None,
    suites: Sequence[Suite] | None = None,
    load: Callable[[str], Dataset] = load_dataset,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=["smoke", "full"], required=True)
    parser.add_argument("--release", default="release_1", help="the thresholds.yaml table to gate on")
    parser.add_argument(
        "--environment",
        choices=["local", "ci"],
        default="local",
        help="where the run comes from, recorded in each experiment's name and metadata (ADR 0023)",
    )
    parser.add_argument(
        "--summary", type=Path, help="append the gate table as Markdown to this file (GitHub's $GITHUB_STEP_SUMMARY)"
    )
    args = parser.parse_args(argv)
    try:
        thresholds = load_thresholds(args.release)
    except ValueError as e:
        return _stop(args.summary, f"Can't gate on {args.release}: {e}")
    models = Settings().models
    metadata = {
        "environment": args.environment,
        "agent_model": models.agent.model_id,
        "judge_model": models.judge.model_id,
    }
    run_name = f"{args.environment} {datetime.now(UTC):%Y-%m-%d %H:%M:%S}Z"
    groups = by_dataset(discover() if suites is None else suites)
    try:
        scores, links = run_split(
            client or SdkLangfuse(tracing=True), groups, args.split, run_name=run_name, load=load, metadata=metadata
        )
    except (DatasetError, LoadError) as e:
        return _stop(args.summary, f"Can't run the {args.split} split: {e}")
    except LangfuseError as e:
        hint = f"check LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, and LANGFUSE_BASE_URL; {HOST_HOURS}"
        return _stop(args.summary, f"Can't reach Langfuse: {e} ({hint})")
    rows = check(thresholds, scores)
    print(render(rows, links))
    _append(args.summary, render_markdown(rows, links, f"{args.split.capitalize()} evals"))
    if not ran(rows):
        why = f"no suite's dataset has a {args.split} split, or every evaluator failed"
        return _stop(args.summary, f"Nothing ran: no metric was scored ({why}).")
    return 0 if passed(rows) else 1


if __name__ == "__main__":
    sys.exit(main())

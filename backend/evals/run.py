"""Run an evaluation split as LangSmith experiments and check the scores against thresholds.yaml (PRD §10).

Usage: uv run --env-file ../.env --extra eval python -m evals.run --split smoke|full
    [--release release_1] [--summary PATH]

Every suite in evaluators/ whose dataset has a published version of the split runs, on its newest version unless the
dataset file pins one; suites on one dataset share one experiment. The gate
prints each of the release's metrics as pass, fail, or not run, with the experiments' links, and the run exits 1 when
a metric fails or when nothing ran. --summary appends the same table as Markdown to a file (GitHub's
$GITHUB_STEP_SUMMARY). Needs the local stack with the eval learners loaded (make evals-learners), your
AWS profile (agent and judge models), and LANGSMITH_API_KEY.
"""

import argparse
import asyncio
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import langsmith
from langsmith.utils import LangSmithError

from evals.dataset import Dataset, DatasetError, examples_at, load_dataset, version_to_run
from evals.gate import check, load_thresholds, passed, ran, render, render_markdown
from evals.learners import LoadError
from evals.suite import NOT_APPLICABLE, DatasetSuites, Suite, by_dataset, discover
from smart_tutor.shared.config import Settings

MAX_CONCURRENCY = 4  # examples in flight; Bedrock throttling backs off in the models' boto config


def _coroutine_function(target: Callable[[dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Any]:
    # aevaluate accepts only coroutine functions; it would read a callable object as an iterable of runs
    async def call(inputs: dict[str, Any]) -> Any:
        return await target(inputs)

    # LangSmith names the traced target run after the function: not "call" for every dataset
    call.__name__ = call.__qualname__ = getattr(target, "__name__", type(target).__name__)
    return call


async def run_split(
    client: Any,
    groups: Sequence[DatasetSuites],
    split: str,
    *,
    load: Callable[[str], Dataset] = load_dataset,
    metadata: Mapping[str, str] | None = None,
) -> tuple[dict[str, list[float | bool | None]], dict[str, str]]:
    """Each metric's scores, one per example, and each experiment's link."""
    scores: defaultdict[str, list[float | bool | None]] = defaultdict(list)
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
        results = await client.aevaluate(
            _coroutine_function(group.target()),
            data=examples_at(client, dataset, split, version),
            evaluators=list(group.evaluators),
            experiment_prefix=f"{dataset.name}-{split}",
            metadata={**(metadata or {}), "split": split, "dataset_version": version},
            max_concurrency=MAX_CONCURRENCY,
        )
        rows = [row["evaluation_results"]["results"] async for row in results]
        # An evaluator that raised leaves its key out of that row: count it as unscored, not as absent, or the
        # gate would average only the survivors. A result marked not applicable is left out of its metric.
        for key in {r.key for row in rows for r in row}:
            for row in rows:
                found = [r for r in row if r.key == key]
                if not found:
                    scores[key].append(None)
                elif found[0].value != NOT_APPLICABLE:
                    scores[key].append(found[0].score)
        links[f"{dataset.name} ({split} {version})"] = (
            await results.get_comparison_url() or results.url or results.experiment_name
        )
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
    client: Any = None,
    suites: Sequence[Suite] | None = None,
    load: Callable[[str], Dataset] = load_dataset,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=["smoke", "full"], required=True)
    parser.add_argument("--release", default="release_1", help="the thresholds.yaml table to gate on")
    parser.add_argument(
        "--summary", type=Path, help="append the gate table as Markdown to this file (GitHub's $GITHUB_STEP_SUMMARY)"
    )
    args = parser.parse_args(argv)
    try:
        thresholds = load_thresholds(args.release)
    except ValueError as e:
        return _stop(args.summary, f"Can't gate on {args.release}: {e}")
    models = Settings().models
    metadata = {"agent_model": models.agent.model_id, "judge_model": models.judge.model_id}
    groups = by_dataset(discover() if suites is None else suites)
    try:
        scores, links = asyncio.run(
            run_split(client or langsmith.Client(), groups, args.split, load=load, metadata=metadata)
        )
    except (DatasetError, LoadError) as e:
        return _stop(args.summary, f"Can't run the {args.split} split: {e}")
    except LangSmithError as e:
        return _stop(args.summary, f"Can't reach LangSmith: {e} (check LANGSMITH_API_KEY)")
    rows = check(thresholds, scores)
    print(render(rows, links))
    _append(args.summary, render_markdown(rows, links, f"{args.split.capitalize()} evals"))
    if not ran(rows):
        why = f"no suite's dataset has a {args.split} split, or every evaluator failed"
        return _stop(args.summary, f"Nothing ran: no metric was scored ({why}).")
    return 0 if passed(rows) else 1


if __name__ == "__main__":
    sys.exit(main())

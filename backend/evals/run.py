"""Run an evaluation split as LangSmith experiments and check the scores against thresholds.yaml (PRD §10).

Usage: uv run --env-file ../.env --extra eval python -m evals.run --split smoke|full [--release release_1]

Every suite in evaluators/ whose dataset has the split runs; suites on one dataset share one experiment. The gate
prints each of the release's metrics as pass, fail, or not run, with the experiments' links, and the run exits 1 when
a metric fails or when nothing ran. Needs the local stack with the eval learners loaded (make evals-learners), your
AWS profile (agent and judge models), and LANGSMITH_API_KEY.
"""

import argparse
import asyncio
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import langsmith

from evals.dataset import Dataset, DatasetError, load_dataset, versioned_examples
from evals.gate import check, load_thresholds, passed, ran, render
from evals.learners import LoadError
from evals.suite import DatasetSuites, Suite, by_dataset, discover
from smart_tutor.shared.config import Settings

MAX_CONCURRENCY = 4  # examples in flight; Bedrock throttling backs off in the models' boto config


def _coroutine_function(target: Callable[[dict[str, Any]], Any]) -> Callable[[dict[str, Any]], Any]:
    # aevaluate accepts only coroutine functions; it would read a callable object as an iterable of runs
    async def call(inputs: dict[str, Any]) -> Any:
        return await target(inputs)

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
            continue  # its metrics stay "not run"
        version = dataset.splits[split]
        results = await client.aevaluate(
            _coroutine_function(group.target()),
            data=versioned_examples(client, dataset, version),
            evaluators=list(group.evaluators),
            experiment_prefix=f"{dataset.name}-{split}",
            metadata={**(metadata or {}), "split": split, "dataset_version": version.version},
            max_concurrency=MAX_CONCURRENCY,
        )
        rows = [{r.key: r.score for r in row["evaluation_results"]["results"]} async for row in results]
        # An evaluator that raised leaves its key out of that row: count it as unscored, not as absent, or the
        # gate would average only the survivors.
        for key in {key for row in rows for key in row}:
            scores[key].extend(row.get(key) for row in rows)
        links[f"{dataset.name} ({split} {version.version})"] = (
            await results.get_comparison_url() or results.url or results.experiment_name
        )
    return dict(scores), links


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
    args = parser.parse_args(argv)
    thresholds = load_thresholds(args.release)
    models = Settings().models
    metadata = {"agent_model": models.agent.model_id, "judge_model": models.judge.model_id}
    groups = by_dataset(discover() if suites is None else suites)
    try:
        scores, links = asyncio.run(
            run_split(client or langsmith.Client(), groups, args.split, load=load, metadata=metadata)
        )
    except (DatasetError, LoadError) as e:
        print(f"Can't run the {args.split} split: {e}", file=sys.stderr)
        return 1
    rows = check(thresholds, scores)
    print(render(rows, links))
    if not ran(rows):
        print(f"Nothing ran: no suite's dataset has a {args.split} split.", file=sys.stderr)
        return 1
    return 0 if passed(rows) else 1


if __name__ == "__main__":
    sys.exit(main())

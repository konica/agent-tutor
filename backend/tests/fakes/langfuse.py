"""The evals' Langfuse seam (evals.langfuse_client.LangfuseClient), in memory: datasets by unique name, their
metadata, and their items in the order created; experiments run the way the SDK runs them (an item whose task raised
is dropped, an evaluator that raised leaves the item without its scores)."""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from evals.langfuse_client import Item, ItemEvaluator, LangfuseError, Score, StoredDataset, Task


@dataclass
class _Dataset:
    description: str
    metadata: dict[str, Any]
    items: list[Item] = field(default_factory=list)


@dataclass(frozen=True)
class ExperimentRun:
    dataset: str
    name: str
    description: str
    metadata: dict[str, str]
    outputs: list[dict[str, Any]]  # each run item's, in item order
    scores: list[list[Score]]  # each run item's


class FakeLangfuse:
    def __init__(self) -> None:
        self.datasets: dict[str, _Dataset] = {}
        self.runs: list[ExperimentRun] = []
        self.calls = 0  # every call, so a test can see what a dry run did

    def dataset_names(self) -> list[str]:
        self.calls += 1
        return list(self.datasets)

    def get_dataset(self, name: str) -> StoredDataset | None:
        self.calls += 1
        found = self.datasets.get(name)
        if found is None:
            return None
        return StoredDataset(name, dict(found.metadata), tuple(found.items))

    def create_dataset(self, name: str, *, description: str, metadata: dict[str, Any]) -> None:
        self.calls += 1
        if name in self.datasets:  # Langfuse would update it: publishing never overwrites a version
            raise LangfuseError(f"409: dataset {name} exists")
        self.datasets[name] = _Dataset(description, dict(metadata))

    def create_item(self, dataset_name: str, item: Item) -> None:
        self.calls += 1
        if dataset_name not in self.datasets:
            raise LangfuseError(f"404: no dataset {dataset_name}")
        self.datasets[dataset_name].items.append(item)

    def run_experiment(
        self,
        dataset_name: str,
        *,
        run_name: str,
        description: str,
        metadata: dict[str, str],
        task: Task,
        evaluators: Sequence[ItemEvaluator],
        max_concurrency: int,
    ) -> str:
        self.calls += 1
        if dataset_name not in self.datasets:
            raise LangfuseError(f"404: no dataset {dataset_name}")

        async def one(item: Item) -> tuple[dict[str, Any], list[Score]] | None:
            try:
                output = await task(dict(item.input))
            except Exception:
                return None  # the SDK logs it and drops the item
            scores: list[Score] = []
            for evaluator in evaluators:
                try:
                    scores += await evaluator(dict(item.input), output, dict(item.expected_output))
                except Exception:
                    continue  # the SDK logs it; the item keeps its other scores
            return output, scores

        async def every() -> list[tuple[dict[str, Any], list[Score]] | None]:
            return [await one(item) for item in self.datasets[dataset_name].items]

        ran = [r for r in asyncio.run(every()) if r is not None]
        run = ExperimentRun(
            dataset_name, run_name, description, dict(metadata), [r[0] for r in ran], [r[1] for r in ran]
        )
        self.runs.append(run)
        return f"https://langfuse.example/datasets/{dataset_name}/runs/{len(self.runs)}"

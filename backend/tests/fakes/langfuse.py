"""The evals' Langfuse seam (evals.langfuse_client.LangfuseClient), in memory: datasets by unique name, their
metadata, and their items in the order created; score configs, annotation queues and the traces in them, traces, and
scores; experiments run the way the SDK runs them (an item whose task raised is dropped, an evaluator that raised
leaves the item without its scores)."""

import asyncio
import itertools
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from evals.langfuse_client import Item, ItemEvaluator, ItemScore, LangfuseError, Score, StoredDataset, Task, Trace

START = datetime(2026, 10, 14, tzinfo=UTC)


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
    scores: list[list[ItemScore]]  # each run item's


@dataclass
class FakeQueue:
    name: str
    description: str
    score_config_ids: list[str]
    trace_ids: list[str] = field(default_factory=list)


class FakeLangfuse:
    def __init__(self) -> None:
        self.datasets: dict[str, _Dataset] = {}
        self.runs: list[ExperimentRun] = []
        self.score_configs: dict[str, tuple[str, str]] = {}  # id -> (name, description), all BOOLEAN
        self.queues: dict[str, FakeQueue] = {}
        self.traces_by_id: dict[str, Trace] = {}
        self.scores: list[Score] = []
        self.calls = 0  # every call, so a test can see what a dry run did
        self._ids = itertools.count(1)
        self._clock = itertools.count(1)

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

    def score_config_id(self, name: str) -> str | None:
        self.calls += 1
        return next((i for i, (n, _) in self.score_configs.items() if n == name), None)

    def create_boolean_score_config(self, name: str, *, description: str) -> str:
        self.calls += 1
        config_id = f"config-{next(self._ids)}"
        self.score_configs[config_id] = (name, description)
        return config_id

    def queue_id(self, name: str) -> str | None:
        self.calls += 1
        return next((i for i, q in self.queues.items() if q.name == name), None)

    def create_queue(self, name: str, *, description: str, score_config_id: str) -> str:
        self.calls += 1
        if any(q.name == name for q in self.queues.values()):
            raise LangfuseError(f"400: a queue named {name} exists")
        if score_config_id not in self.score_configs:
            raise LangfuseError("400: At least one of the score config IDs cannot be found for the given project.")
        queue_id = f"queue-{next(self._ids)}"
        self.queues[queue_id] = FakeQueue(name, description, [score_config_id])
        return queue_id

    def create_traces(self, traces: Sequence[Trace]) -> None:
        self.calls += 1
        for trace in traces:
            self.traces_by_id[trace.id] = trace

    def queue_trace(self, queue_id: str, trace_id: str) -> None:
        self.calls += 1
        if queue_id not in self.queues:
            raise LangfuseError("404: Annotation queue not found")
        self.queues[queue_id].trace_ids.append(trace_id)

    def traces(self, name: str) -> list[Trace]:
        self.calls += 1
        return [t for t in self.traces_by_id.values() if t.name == name]

    def boolean_scores(self, name: str) -> list[Score]:
        self.calls += 1
        return [s for s in self.scores if s.name == name]

    def score(self, trace_id: str, name: str, value: float) -> None:
        """A reviewer sets a new score on a trace in the queue; each is newer than the last."""
        self.scores.append(Score(trace_id, name, value, START + timedelta(seconds=next(self._clock))))

    def edit_score(self, index: int, value: float) -> None:
        """A reviewer changes an existing score (in place, as the UI does): only its updated_at moves."""
        self.scores[index] = replace(
            self.scores[index], value=value, updated_at=START + timedelta(seconds=next(self._clock))
        )

    def delete_trace(self, trace_id: str) -> None:
        """Deleting a trace deletes its scores too (its queue item stays)."""
        del self.traces_by_id[trace_id]
        self.scores = [s for s in self.scores if s.trace_id != trace_id]

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

        async def one(item: Item) -> tuple[dict[str, Any], list[ItemScore]] | None:
            try:
                output = await task(dict(item.input))
            except Exception:
                return None  # the SDK logs it and drops the item
            scores: list[ItemScore] = []
            for evaluator in evaluators:
                try:
                    scores += await evaluator(dict(item.input), output, dict(item.expected_output))
                except Exception:
                    continue  # the SDK logs it; the item keeps its other scores
            return output, scores

        async def every() -> list[tuple[dict[str, Any], list[ItemScore]] | None]:
            return [await one(item) for item in self.datasets[dataset_name].items]

        ran = [r for r in asyncio.run(every()) if r is not None]
        run = ExperimentRun(
            dataset_name, run_name, description, dict(metadata), [r[0] for r in ran], [r[1] for r in ran]
        )
        self.runs.append(run)
        return f"https://langfuse.example/datasets/{dataset_name}/runs/{len(self.runs)}"

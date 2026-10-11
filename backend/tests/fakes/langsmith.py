"""The LangSmith client calls evals make, in memory: datasets whose every change is a version, version tags, and
aevaluate running a target and evaluators the way LangSmith does (a target error leaves the outputs empty)."""

import inspect
import itertools
import uuid
from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from langsmith.evaluation import EvaluationResult
from langsmith.utils import LangSmithNotFoundError

START = datetime(2026, 10, 11, tzinfo=UTC)


@dataclass(frozen=True)
class FakeExample:
    id: uuid.UUID
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None
    split: str
    created_at: datetime
    modified_at: datetime


@dataclass
class _Dataset:
    versions: list[tuple[datetime, tuple[FakeExample, ...]]] = field(default_factory=list)
    tags: dict[str, datetime] = field(default_factory=dict)

    def at(self, when: datetime | None) -> tuple[FakeExample, ...]:
        found: tuple[FakeExample, ...] = ()
        for at, examples in self.versions:
            if when is None or at <= when:
                found = examples
        return found


@dataclass
class Experiment:
    prefix: str
    metadata: dict[str, Any]
    example_ids: list[uuid.UUID]


class FakeResults:
    def __init__(self, rows: list[dict[str, Any]], url: str) -> None:
        self._rows, self.url, self.experiment_name = rows, url, url.rsplit("/", 1)[-1]

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        async def rows() -> AsyncIterator[dict[str, Any]]:
            for row in self._rows:
                yield row

        return rows()

    async def get_comparison_url(self) -> str:
        return self.url


class FakeLangSmith:
    def __init__(self) -> None:
        self.datasets: dict[str, _Dataset] = {}
        self.experiments: list[Experiment] = []
        self.created = 0  # create_examples calls
        self._clock = itertools.count(1)

    def _now(self) -> datetime:
        return START + timedelta(seconds=next(self._clock))

    def has_dataset(self, *, dataset_name: str) -> bool:
        return dataset_name in self.datasets

    def create_dataset(self, dataset_name: str, *, description: str | None = None) -> None:
        self.datasets[dataset_name] = _Dataset()

    def read_dataset_version(self, *, dataset_name: str, tag: str) -> dict[str, Any]:
        if tag not in self.datasets[dataset_name].tags:
            raise LangSmithNotFoundError(f"no version tagged {tag}")
        return {"tags": [tag], "as_of": self.datasets[dataset_name].tags[tag]}

    def list_examples(
        self, *, dataset_name: str, splits: Sequence[str] | None = None, as_of: str | datetime | None = None
    ) -> Iterator[FakeExample]:
        dataset = self.datasets[dataset_name]
        when = dataset.tags[as_of] if isinstance(as_of, str) else as_of
        return iter([e for e in dataset.at(when) if splits is None or e.split in splits])

    def delete_examples(self, example_ids: Sequence[uuid.UUID]) -> None:
        for dataset in self.datasets.values():
            current = dataset.at(None)
            if any(e.id in example_ids for e in current):
                dataset.versions.append((self._now(), tuple(e for e in current if e.id not in example_ids)))

    def create_examples(self, *, dataset_name: str, examples: Sequence[dict[str, Any]]) -> None:
        self.created += 1
        dataset, now = self.datasets[dataset_name], self._now()
        new = tuple(
            FakeExample(uuid.uuid4(), dict(e["inputs"]), e.get("outputs"), e["split"], now, now) for e in examples
        )
        dataset.versions.append((now, dataset.at(None) + new))

    def update_dataset_tag(self, *, dataset_name: str, as_of: datetime, tag: str) -> None:
        self.datasets[dataset_name].tags[tag] = as_of

    async def aevaluate(
        self,
        target: Callable[[dict[str, Any]], Any],
        /,
        data: Iterable[FakeExample],
        evaluators: Sequence[Callable[..., Any]],
        experiment_prefix: str,
        metadata: dict[str, Any],
        max_concurrency: int,
    ) -> FakeResults:
        examples, rows = list(data), []
        for example in examples:
            try:
                outputs = await target(example.inputs)
            except Exception:
                outputs = {}
            results = []
            for evaluator in evaluators:
                given = {"inputs": example.inputs, "outputs": outputs, "reference_outputs": example.outputs or {}}
                wanted = {k: v for k, v in given.items() if k in inspect.signature(evaluator).parameters}
                result = evaluator(**wanted)
                if inspect.isawaitable(result):
                    result = await result
                results.append(EvaluationResult(**result))
            rows.append({"example": example, "outputs": outputs, "evaluation_results": {"results": results}})
        self.experiments.append(Experiment(experiment_prefix, metadata, [e.id for e in examples]))
        return FakeResults(rows, f"https://smith.example/{experiment_prefix}-{len(self.experiments)}")

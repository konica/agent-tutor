"""The one place the evals reach Langfuse: the `smart-tutor-evals` project (ADR 0023 §5).

`LangfuseClient` is the seam: the few Langfuse calls the evals make, in our own types, so the fake
(`tests/fakes/langfuse.py`) stands in for Langfuse in every test and a new caller (the review queue) adds a method here
instead of importing the SDK. `SdkLangfuse` implements it with the Langfuse Python SDK, imported only when one is made
(the `eval` extra; unit tests don't install it). Every Langfuse or network failure comes out as `LangfuseError`.

Keys: `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` of the `smart-tutor-evals` project, and the host's URL in
`LANGFUSE_BASE_URL` (else `SMART_TUTOR_LANGFUSE_URL`, the runtime's setting for the same host).
"""

import os
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Protocol

KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
URLS = ("LANGFUSE_BASE_URL", "SMART_TUTOR_LANGFUSE_URL")
PAGE = 100  # datasets per list call


class LangfuseError(Exception):
    """Langfuse refused a call or couldn't be reached."""


@dataclass(frozen=True)
class Item:
    """A dataset item: an example's inputs, reference outputs, and metadata."""

    input: dict[str, Any]
    expected_output: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StoredDataset:
    name: str
    metadata: dict[str, Any]
    items: tuple[Item, ...]  # the active items


@dataclass(frozen=True)
class Score:
    """One metric's score of an experiment item, posted on the item's trace."""

    name: str
    value: float
    comment: str | None = None


Task = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]  # an item's input -> its output
# an item's input, output, and expected output -> its scores; one that raises leaves the item without them
ItemEvaluator = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], Awaitable[list[Score]]]


class LangfuseClient(Protocol):
    def dataset_names(self) -> list[str]:
        """Every dataset of the project."""
        ...

    def get_dataset(self, name: str) -> StoredDataset | None:
        """The dataset with its active items, or None when there is none of that name."""
        ...

    def create_dataset(self, name: str, *, description: str, metadata: dict[str, Any]) -> None: ...

    def create_item(self, dataset_name: str, item: Item) -> None: ...

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
        """Run `task` on each item of the dataset as one dataset run, `run_name`, each item traced and scored by
        `evaluators` on its trace. An item whose task raised is left out of the run. Returns the run's link (its name
        when Langfuse gave none)."""
        ...


@contextmanager
def _translated() -> Iterator[None]:
    import httpx
    from langfuse.api.core import ApiError

    try:
        yield
    except ApiError as e:
        raise LangfuseError(f"{e.status_code}: {e.body}") from e
    except httpx.HTTPError as e:
        raise LangfuseError(str(e) or type(e).__name__) from e


class SdkLangfuse:
    """LangfuseClient on the Langfuse Python SDK. Its tracing is off unless `tracing`: only an experiment traces (each
    item's run); the dataset calls are the REST API only."""

    def __init__(self, client: Any = None, *, tracing: bool = False) -> None:
        if client is None:
            if missing := [k for k in KEYS if not os.environ.get(k)]:
                raise LangfuseError(f"{' and '.join(missing)} not set (a key pair of the smart-tutor-evals project)")
            url = next((u for k in URLS if (u := os.environ.get(k))), None)
            if url is None:
                raise LangfuseError(f"{URLS[0]} not set (the Langfuse host's URL)")
            from langfuse import Langfuse

            client = Langfuse(base_url=url, tracing_enabled=tracing)
        self._client = client

    def dataset_names(self) -> list[str]:
        names: list[str] = []
        page = 1
        with _translated():
            while True:
                found = self._client.api.datasets.list(page=page, limit=PAGE)
                names += [d.name for d in found.data]
                if page >= found.meta.total_pages:
                    return names
                page += 1

    def get_dataset(self, name: str) -> StoredDataset | None:
        from langfuse.api import NotFoundError

        with _translated():
            try:
                dataset = self._client.get_dataset(name)
            except NotFoundError:
                return None
        items = tuple(
            Item(dict(i.input or {}), dict(i.expected_output or {}), dict(i.metadata or {}))
            for i in dataset.items
            if i.status == "ACTIVE"
        )
        return StoredDataset(dataset.name, dict(dataset.metadata or {}), items)

    def create_dataset(self, name: str, *, description: str, metadata: dict[str, Any]) -> None:
        with _translated():
            self._client.create_dataset(name=name, description=description, metadata=metadata)

    def create_item(self, dataset_name: str, item: Item) -> None:
        with _translated():
            self._client.create_dataset_item(
                dataset_name=dataset_name,
                input=item.input,
                expected_output=item.expected_output,
                metadata=item.metadata or None,
            )

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
        # The SDK runs the items on an event loop of its own, links each item's trace to the dataset run, and posts
        # each Evaluation as a score on that trace. It logs and drops an item whose task raised, and logs an evaluator
        # that raised and goes on.
        from langfuse import Evaluation

        async def run(*, item: Any, **kwargs: Any) -> dict[str, Any]:
            return await task(dict(item.input or {}))

        def evaluation(evaluator: ItemEvaluator) -> Callable[..., Awaitable[list[Evaluation]]]:
            async def evaluate(
                *, input: Any, output: Any, expected_output: Any = None, **kwargs: Any
            ) -> list[Evaluation]:
                scores = await evaluator(dict(input or {}), output, dict(expected_output or {}))
                return [Evaluation(name=s.name, value=s.value, comment=s.comment, data_type="NUMERIC") for s in scores]

            # Langfuse names the evaluator's observation after the function
            evaluate.__name__ = evaluate.__qualname__ = getattr(evaluator, "__name__", "evaluate")
            return evaluate

        with _translated():
            dataset = self._client.get_dataset(dataset_name)
            result = self._client.run_experiment(
                name=dataset_name,
                run_name=run_name,
                description=description,
                data=[i for i in dataset.items if i.status == "ACTIVE"],
                task=run,
                evaluators=[evaluation(e) for e in evaluators],
                max_concurrency=max_concurrency,
                metadata=metadata,
            )
        return str(result.dataset_run_url or run_name)

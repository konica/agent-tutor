"""The one place the evals reach Langfuse: the `smart-tutor-evals` project (ADR 0023 §5).

`LangfuseClient` is the seam: the few Langfuse calls the evals make, in our own types, so the fake
(`tests/fakes/langfuse.py`) stands in for Langfuse in every test and a new caller adds a method here
instead of importing the SDK. `SdkLangfuse` implements it with the Langfuse Python SDK, imported only when one is made
(the `eval` extra; unit tests don't install it). Every Langfuse or network failure comes out as `LangfuseError`.

Keys: `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` of the `smart-tutor-evals` project, and the host's URL in
`LANGFUSE_BASE_URL` (else `SMART_TUTOR_LANGFUSE_URL`, the runtime's setting for the same host).

The host runs Langfuse v4 in `events_only` mode, which removes the legacy trace, score, and ingestion endpoints
(ADR 0023 §5). A review candidate is therefore an OpenTelemetry root span (its trace's only observation), read back
with the Observations API v2, and the reviewer's `accepted` scores are read with the Scores API v3.
"""

import json
import os
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

KEYS = ("LANGFUSE_PUBLIC_KEY", "LANGFUSE_SECRET_KEY")
URLS = ("LANGFUSE_BASE_URL", "SMART_TUTOR_LANGFUSE_URL")
# Printed when Langfuse can't be reached: its keys, and the host's hours (ADR 0022).
HINT = f"check {', '.join(KEYS)} and {URLS[0]}; the host is off 18:00-07:00 Asia/Ho_Chi_Minh"
PAGE = 100  # datasets, queues, observations, scores, or score configs per list call (the scores API allows 100)
TRACE_BATCH = 50  # candidate spans per OTLP export call
SERVICE = "smart-tutor-evals"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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
class Trace:
    """A trace the evals write themselves (a review candidate), not one the app's tracing sends."""

    id: str  # 32 lowercase hex characters
    name: str
    input: dict[str, Any]
    output: dict[str, Any]
    metadata: dict[str, Any]
    timestamp: datetime  # Langfuse keeps milliseconds
    environment: str


@dataclass(frozen=True)
class Score:
    trace_id: str
    name: str
    value: float  # a BOOLEAN score is 1 or 0
    updated_at: datetime  # when it was last set: editing a score in the UI keeps its timestamp


@dataclass(frozen=True)
class ItemScore:
    """One metric's score of an experiment item, posted on the item's trace."""

    name: str
    value: float
    comment: str | None = None


Task = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]  # an item's input -> its output
# an item's input, output, expected output, and row metadata -> its scores; one that raises leaves the item without them
ItemEvaluator = Callable[[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]], Awaitable[list[ItemScore]]]


class LangfuseClient(Protocol):
    def dataset_names(self) -> list[str]:
        """Every dataset of the project."""
        ...

    def get_dataset(self, name: str) -> StoredDataset | None:
        """The dataset with its active items, or None when there is none of that name."""
        ...

    def create_dataset(self, name: str, *, description: str, metadata: dict[str, Any]) -> None: ...

    def create_item(self, dataset_name: str, item: Item) -> None: ...

    def score_config_id(self, name: str) -> str | None:
        """The id of the project's unarchived score config of that name, or None."""
        ...

    def create_boolean_score_config(self, name: str, *, description: str) -> str: ...

    def queue_id(self, name: str) -> str | None:
        """The id of the project's annotation queue of that name, or None."""
        ...

    def create_queue(self, name: str, *, description: str, score_config_id: str) -> str: ...

    def create_traces(self, traces: Sequence[Trace]) -> None:
        """Send the traces; Langfuse stores them asynchronously, so a list may not show them for some seconds."""
        ...

    def queue_trace(self, queue_id: str, trace_id: str) -> None:
        """Add a trace to the queue (Langfuse doesn't check that the trace has arrived)."""
        ...

    def traces(self, name: str) -> list[Trace]:
        """Every trace of that name."""
        ...

    def boolean_scores(self, name: str) -> list[Score]:
        """Every BOOLEAN trace score of that name, from any source (a reviewer, the API)."""
        ...

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


def _utc(at: datetime) -> datetime:
    return at.replace(tzinfo=UTC) if at.tzinfo is None else at.astimezone(UTC)


def observation_id(trace_id: str) -> str:
    """The id of a candidate's root span: the first 16 hex characters of its trace id, so the queue item and the
    score's subject need no lookup."""
    return trace_id[:16]


def _json_object(value: Any) -> dict[str, Any]:
    """An observation's input, output, or metadata as a dict: the Observations API v2 returns input and output as raw
    JSON strings."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return dict(value) if isinstance(value, dict) else {}


def _attribute(key: str, value: str) -> Any:
    from langfuse.api import OtelAttribute, OtelAttributeValue

    return OtelAttribute(key=key, value=OtelAttributeValue(string_value=value))


def _candidate_span(trace: Trace) -> Any:
    """The OTLP root span of one candidate: its input, output, and metadata as Langfuse's span attributes. It starts
    and ends at the trace's timestamp (whole milliseconds, which Langfuse keeps)."""
    from langfuse.api import OtelSpan

    nanos = str((_utc(trace.timestamp) - _EPOCH) // timedelta(milliseconds=1) * 1_000_000)
    attributes = [
        ("langfuse.trace.name", trace.name),
        ("langfuse.observation.type", "span"),
        ("langfuse.environment", trace.environment),
        ("langfuse.observation.input", json.dumps(trace.input)),
        ("langfuse.observation.output", json.dumps(trace.output)),
        *(
            (f"langfuse.observation.metadata.{key}", value if isinstance(value, str) else json.dumps(value))
            for key, value in trace.metadata.items()
        ),
    ]
    return OtelSpan(
        trace_id=trace.id,
        span_id=observation_id(trace.id),
        name=trace.name,
        kind=1,
        start_time_unix_nano=nanos,
        end_time_unix_nano=nanos,
        attributes=[_attribute(key, value) for key, value in attributes],
    )


def _scored_trace(score: Any) -> str | None:
    """The trace a score is on: its own, or the trace of the observation it is on; none for a session or experiment."""
    subject = score.subject
    if subject is None:
        return None
    if subject.kind == "trace":
        return str(subject.id)
    if subject.kind == "observation":
        return subject.trace_id
    return None


class SdkLangfuse:
    """LangfuseClient on the Langfuse Python SDK. Its tracing is off unless `tracing`: only an experiment traces (each
    item's run); every other call is the REST API only (review candidates go through the ingestion API)."""

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

    def _all(self, list_page: Any, **filters: Any) -> list[Any]:
        """Every row of a paginated list call."""
        rows: list[Any] = []
        page = 1
        with _translated():
            while True:
                found = list_page(page=page, limit=PAGE, **filters)
                rows += found.data
                if page >= found.meta.total_pages:
                    return rows
                page += 1

    def _cursored(self, list_page: Any, **filters: Any) -> list[Any]:
        """Every row of a cursor-paginated list call (the v4 observations and scores APIs)."""
        rows: list[Any] = []
        cursor: str | None = None
        with _translated():
            while True:
                found = list_page(limit=PAGE, cursor=cursor, **filters)
                rows += found.data
                cursor = found.meta.cursor
                if not cursor:
                    return rows

    def dataset_names(self) -> list[str]:
        return [d.name for d in self._all(self._client.api.datasets.list)]

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

    def score_config_id(self, name: str) -> str | None:
        configs = self._all(self._client.api.score_configs.get)
        return next((c.id for c in configs if c.name == name and not c.is_archived), None)

    def create_boolean_score_config(self, name: str, *, description: str) -> str:
        from langfuse.api import ScoreConfigDataType

        with _translated():
            config = self._client.api.score_configs.create(
                name=name, data_type=ScoreConfigDataType.BOOLEAN, description=description
            )
        return str(config.id)

    def queue_id(self, name: str) -> str | None:
        queues = self._all(self._client.api.annotation_queues.list_queues)
        return next((q.id for q in queues if q.name == name), None)

    def create_queue(self, name: str, *, description: str, score_config_id: str) -> str:
        with _translated():
            queue = self._client.api.annotation_queues.create_queue(
                name=name, description=description, score_config_ids=[score_config_id]
            )
        return str(queue.id)

    def create_traces(self, traces: Sequence[Trace]) -> None:
        from langfuse.api import OtelResource, OtelResourceSpan, OtelScope, OtelScopeSpan

        for first in range(0, len(traces), TRACE_BATCH):
            spans = [_candidate_span(t) for t in traces[first : first + TRACE_BATCH]]
            resource_span = OtelResourceSpan(
                resource=OtelResource(attributes=[_attribute("service.name", SERVICE)]),
                scope_spans=[OtelScopeSpan(scope=OtelScope(name=SERVICE), spans=spans)],
            )
            with _translated():
                self._client.api.opentelemetry.export_traces(resource_spans=[resource_span])

    def queue_trace(self, queue_id: str, trace_id: str) -> None:
        from langfuse.api import AnnotationQueueObjectType

        with _translated():
            self._client.api.annotation_queues.create_queue_item(
                queue_id, object_id=observation_id(trace_id), object_type=AnnotationQueueObjectType.OBSERVATION
            )

    def traces(self, name: str) -> list[Trace]:
        found = self._cursored(
            self._client.api.observations.get_many,
            name=name,
            is_root_observation=True,
            fields="core,basic,io,metadata",
        )
        return [
            Trace(
                o.trace_id,
                o.name or name,
                _json_object(o.input),
                _json_object(o.output),
                _json_object(o.metadata),
                _utc(o.start_time),
                o.environment or "",
            )
            for o in found
            if o.trace_id is not None
        ]

    def boolean_scores(self, name: str) -> list[Score]:
        found = self._cursored(self._client.api.scores_v3.get_many_v3, name=name, data_type="BOOLEAN", fields="subject")
        return [
            Score(trace_id, s.name, float(s.value), _utc(s.updated_at))
            for s in found
            if (trace_id := _scored_trace(s)) is not None
        ]

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
                *, input: Any, output: Any, expected_output: Any = None, metadata: Any = None, **kwargs: Any
            ) -> list[Evaluation]:
                scores = await evaluator(dict(input or {}), output, dict(expected_output or {}), dict(metadata or {}))
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

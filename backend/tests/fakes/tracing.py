"""Fakes for LangSmith tracing: a client that records payloads, and a RunTracing that records runs."""

import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import Executor, Future
from contextlib import AbstractContextManager, contextmanager, nullcontext
from types import SimpleNamespace
from typing import Any, TypeVar

import langsmith
from langsmith.utils import LangSmithNotFoundError
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from smart_tutor.shared.adapters.tracing import LearnerHasher, PhoenixTraces, phoenix_traces
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.ports.run_tracing import RunTracing

T = TypeVar("T")

META = {"deployment": "local", "chat_model": "chat-x", "embedding_model": "embed-y"}


class FailingExporter(SpanExporter):
    """An exporter whose every export raises, as a Phoenix that is down would."""

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        raise ConnectionError("Phoenix is down")

    def shutdown(self) -> None:
        pass


@contextmanager
def recorded_traces(
    sampling_rate: float = 1.0,
    exporter: SpanExporter | None = None,
    metadata: Mapping[str, str] = META,
    hasher: LearnerHasher | None = None,
) -> Iterator[tuple[PhoenixTraces, InMemorySpanExporter]]:
    """Phoenix tracing as the agent and worker set it up, but each span is kept in memory (or given to `exporter`) the
    moment it ends, instead of being sent. LangChain is instrumented only inside the block."""
    memory = InMemorySpanExporter()
    traces = phoenix_traces(
        "smart-tutor-test",
        sampling_rate,
        SimpleSpanProcessor(exporter or memory),
        hasher or LearnerHasher("k"),
        metadata,
    )
    try:
        yield traces, memory
    finally:
        traces.shutdown()


class RecordingClient(langsmith.Client):
    """LangSmith client that records create/update payloads instead of sending them."""

    def __init__(self) -> None:
        super().__init__(api_key="test-not-a-key", api_url="http://127.0.0.1:9", auto_batch_tracing=False)
        self.payloads: list[dict[str, Any]] = []

    def create_run(self, *args: Any, **kwargs: Any) -> None:
        self.payloads.append({"op": "create", **kwargs})

    def update_run(self, *args: Any, **kwargs: Any) -> None:
        self.payloads.append({"op": "update", "run_id": str(args[0]) if args else None, **kwargs})


class FakeRunTracing(RunTracing):
    """Records each run's name, learner, and metadata."""

    def __init__(self) -> None:
        self.runs: list[tuple[str, UserId, dict[str, str]]] = []

    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> AbstractContextManager[None]:
        self.runs.append((name, user_id, dict(metadata)))
        return nullcontext()


class FeedbackClient(langsmith.Client):
    """LangSmith client that keeps feedback in memory and records each call's arguments; never reaches the network.
    `fail` makes every call raise, as an outage would; `lagging` makes `list_feedback` return nothing, as LangSmith does
    for feedback created a moment ago."""

    def __init__(self, fail: Exception | None = None, lagging: bool = False) -> None:
        super().__init__(api_key="test-not-a-key", api_url="http://127.0.0.1:9", auto_batch_tracing=False)
        self.project_id = uuid.uuid4()
        self.feedback: dict[uuid.UUID, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fail = fail
        self.lagging = lagging

    def _call(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))
        if self._fail is not None:
            raise self._fail

    def read_project(self, **kwargs: Any) -> Any:
        self._call("read_project", kwargs)
        return SimpleNamespace(id=self.project_id)

    def list_feedback(self, **kwargs: Any) -> Iterator[Any]:
        self._call("list_feedback", kwargs)
        runs = {str(r) for r in kwargs.get("run_ids") or []}
        keys = set(kwargs.get("feedback_key") or [])
        if self.lagging:
            return iter([])
        return iter(
            [
                SimpleNamespace(id=i, **f)
                for i, f in self.feedback.items()
                if str(f["run_id"]) in runs and f["key"] in keys
            ]
        )

    def delete_feedback(self, feedback_id: Any) -> None:
        self._call("delete_feedback", {"feedback_id": feedback_id})
        if feedback_id not in self.feedback:
            raise LangSmithNotFoundError(f"feedback {feedback_id} not found")
        del self.feedback[feedback_id]

    def create_feedback(self, run_id: Any = None, key: str = "unnamed", **kwargs: Any) -> Any:
        self._call("create_feedback", {"run_id": run_id, "key": key, **kwargs})
        feedback_id = kwargs.pop("feedback_id", None) or uuid.uuid4()
        self.feedback[feedback_id] = {"run_id": run_id, "key": key, **kwargs}
        return SimpleNamespace(id=feedback_id)


class InlineExecutor(Executor):
    """Runs each task at once on the caller's thread, so a test sees its effect when `submit` returns."""

    def submit(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> Future[T]:
        future: Future[T] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as e:
            future.set_exception(e)
        return future

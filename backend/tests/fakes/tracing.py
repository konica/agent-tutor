"""Fakes for tracing: LangSmith (evals, and the test guard) with a client that records payloads, and Phoenix with a
RunTracing that records runs."""

from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager, nullcontext
from typing import Any, TypeVar

import langsmith
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

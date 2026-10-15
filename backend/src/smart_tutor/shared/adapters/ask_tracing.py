"""The ask's root span (PRD §10.4, ADR 0023): its trace id is the turn's run id and its span id the run id's low 64
bits, so the API can address it from the stored run id. LangGraph and model spans nest beneath it, and every span names
the learner hash as its user and the thread, if any, as its session. The root carries the run's metadata, input, and
output for Langfuse."""

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import context, trace
from opentelemetry.trace import Span, Status, StatusCode

from smart_tutor.shared.adapters.tracing import (
    LANGFUSE_OUTPUT,
    OtelTraces,
    learner_attributes,
    root_ids,
    run_context,
    span_attributes,
)
from smart_tutor.shared.ports.ask_tracing import AskRun, AskTrace, AskTracing, NoAskTrace

NO_DECLINE = "none"

logger = logging.getLogger(__name__)


class _OtelAskTrace(AskTrace):
    def __init__(self, span: Span, metadata: dict[str, Any]) -> None:
        self._span = span
        self._metadata = metadata

    def finish(self, answer: str, decline: str | None, chunks: int) -> None:
        self._end(
            {"decline": decline or NO_DECLINE, "chunks": 0 if decline else chunks},
            Status(StatusCode.OK),
            output={"answer": answer, "decline": decline},
        )

    def fail(self, code: str) -> None:
        self._end({"decline": NO_DECLINE, "chunks": 0}, Status(StatusCode.ERROR, code))

    def close(self) -> None:
        """Ends a span left open (the stream was closed before the ask ended)."""
        if self._span.is_recording():
            self._safely(self._span.end)

    def _end(self, metadata: dict[str, Any], status: Status, output: dict[str, Any] | None = None) -> None:
        def end() -> None:
            attributes = span_attributes(None, {**self._metadata, **metadata})
            if output is not None:
                attributes["output.value"] = attributes[LANGFUSE_OUTPUT] = json.dumps(output)
                attributes["output.mime_type"] = "application/json"
            self._span.set_attributes(attributes)
            self._span.set_status(status)
            self._span.end()

        if self._span.is_recording():
            self._safely(end)

    @staticmethod
    def _safely(step: Callable[[], object]) -> None:
        try:
            step()
        except Exception:  # tracing never fails the ask (#229)
            logger.warning("could not end the ask trace", exc_info=True)


class OtelAskTracing(AskTracing):
    def __init__(self, traces: OtelTraces) -> None:
        self._traces = traces

    @contextmanager
    def trace(self, run: AskRun) -> Iterator[AskTrace]:
        metadata: dict[str, Any] = {**self._traces.metadata, "limited": run.document_ids is not None}
        if run.thread_id is not None:
            metadata["thread_id"] = run.thread_id
        learner = metadata["learner_hash"] = self._traces.hasher(run.user_id)
        span: Span | None = None
        try:
            attributes = span_attributes({"question": run.question, "document_ids": run.document_ids}, metadata)
            # Langfuse groups a conversation's asks as a session.
            attributes |= learner_attributes(learner, run.thread_id)
            with root_ids(run.run_id):
                # An empty context: a true root, whatever span is current.
                span = self._traces.tracer().start_span("ask", context=context.Context(), attributes=attributes)
            # One attach for the whole ask: the span made current on top of the learner and thread. LangGraph's tasks
            # copy this context when they start, so every span inside carries them.
            with run_context(learner, run.thread_id):
                base = context.get_current()
            token = context.attach(trace.set_span_in_context(span, base))
        except Exception:
            logger.warning("tracing could not start; running untraced", exc_info=True)
            if span is not None:
                _OtelAskTrace._safely(span.end)  # started but never made current: end it, so no span is left open
            yield NoAskTrace()
            return
        ask = _OtelAskTrace(span, metadata)
        try:
            yield ask
        finally:
            ask.close()
            # detach logs its own failure; a stream the client abandoned is ended when the generator is finalized, and
            # OTel may then log a detach error from another context.
            context.detach(token)

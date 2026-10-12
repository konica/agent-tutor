"""The ask's root span in Phoenix (PRD §10.4): its trace id is the turn's run id and its span id the run id's low 64
bits, so the API can address it from the stored run id. LangGraph and model spans nest beneath it."""

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from opentelemetry import context, trace
from opentelemetry.trace import Span, Status, StatusCode

from smart_tutor.shared.adapters.tracing import PhoenixTraces, root_ids, span_attributes
from smart_tutor.shared.ports.ask_tracing import AskRun, AskTrace, AskTracing, NoAskTrace

NO_DECLINE = "none"

logger = logging.getLogger(__name__)


class _PhoenixAskTrace(AskTrace):
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
                attributes["output.value"] = json.dumps(output)
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


class PhoenixAskTracing(AskTracing):
    def __init__(self, traces: PhoenixTraces) -> None:
        self._traces = traces

    @contextmanager
    def trace(self, run: AskRun) -> Iterator[AskTrace]:
        metadata: dict[str, Any] = {**self._traces.metadata, "limited": run.document_ids is not None}
        if run.thread_id is not None:
            metadata["thread_id"] = run.thread_id
        metadata["learner_hash"] = self._traces.hasher(run.user_id)
        try:
            attributes = span_attributes({"question": run.question, "document_ids": run.document_ids}, metadata)
            if run.thread_id is not None:
                attributes["session.id"] = run.thread_id  # Phoenix groups a conversation's asks as a session
            with root_ids(run.run_id):
                # An empty context: a true root, whatever span is current.
                span = self._traces.tracer().start_span("ask", context=context.Context(), attributes=attributes)
            token = context.attach(trace.set_span_in_context(span))
        except Exception:
            logger.warning("tracing could not start; running untraced", exc_info=True)
            yield NoAskTrace()
            return
        ask = _PhoenixAskTrace(span, metadata)
        try:
            yield ask
        finally:
            ask.close()
            # detach logs its own failure; a stream the client abandoned is ended when the generator is finalized, and
            # OTel may then log a detach error from another context.
            context.detach(token)

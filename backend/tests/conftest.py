"""Shared fixtures. Unit tests use fakes; integration tests (marker `integration`) need `make up`.

No test sends a trace, whatever environment is loaded (ADR 0017): tracing is off for the whole session, and LangSmith's
default client records instead of sending. A test that needs a trace turns it on with its own recording client. No test
reaches a Phoenix either: `SMART_TUTOR_PHOENIX_URL` is blank for the session, so every `Settings()` is untraced, and a
test that leaves LangChain instrumented fails."""

import os
from collections.abc import Iterator

import langsmith
import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from openinference.instrumentation.langchain import LangChainInstrumentor

from fakes import RecordingClient, fake_embeddings
from smart_tutor.shared.adapters.tracing import LANGSMITH_SWITCHES


@pytest.fixture(autouse=True, scope="session")
def _phoenix_off() -> Iterator[None]:
    # The environment beats `.env` files in pydantic-settings, so a blank value wins over a developer's URL.
    patch = pytest.MonkeyPatch()
    patch.setenv("SMART_TUTOR_PHOENIX_URL", "")
    yield
    patch.undo()


@pytest.fixture(autouse=True)
def _langsmith_switches_restored(monkeypatch: pytest.MonkeyPatch) -> None:
    # `start_tracing` sets these in os.environ; put back whatever each test found, so one test's startup never decides
    # another's (LANGCHAIN_TRACING_V2=false would beat a later test's LANGSMITH_TRACING=true).
    for name in LANGSMITH_SWITCHES:
        was = os.environ.get(name)
        monkeypatch.setenv(name, was or "")  # makes the undo restore the original value, or its absence
        if was is None:
            monkeypatch.delenv(name)


@pytest.fixture(autouse=True)
def _no_instrumentation_left() -> Iterator[None]:
    yield
    instrumentor = LangChainInstrumentor()
    if instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.uninstrument()
        pytest.fail("this test left LangChain instrumented; trace inside fakes.recorded_traces()")


@pytest.fixture(autouse=True, scope="session")
def _tracing_off() -> Iterator[RecordingClient]:
    # Global, not a context variable: it also holds on the threads TestClient runs the app on, and LangSmith reads it
    # before the environment (LANGSMITH_TRACING). A test's own `tracing_context(enabled=True)` still wins.
    default = RecordingClient()
    langsmith.configure(enabled=False, client=default)
    yield default
    langsmith.configure(enabled=None, client=None)


@pytest.fixture(autouse=True)
def _no_trace_left(_tracing_off: RecordingClient) -> Iterator[None]:
    _tracing_off.payloads.clear()
    yield
    assert not _tracing_off.payloads, "this test traced to LangSmith's default client; give its trace a RecordingClient"


@pytest.fixture
def embedding_model() -> DeterministicFakeEmbedding:
    return fake_embeddings()

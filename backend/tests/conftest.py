"""Shared fixtures. Unit tests use fakes; integration tests (marker `integration`) need `make up`.

No test sends a trace, whatever environment is loaded (ADR 0017): tracing is off for the whole session, and LangSmith's
default client records instead of sending. A test that needs a trace turns it on with its own recording client."""

from collections.abc import Iterator

import langsmith
import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

from fakes import RecordingClient, fake_embeddings


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

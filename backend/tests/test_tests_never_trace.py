"""ADR 0017: no test sends a trace, whatever environment is loaded (an IDE runner's `.env`, `uv run --env-file`, an
exported shell). This file sits outside `tests/unit` on purpose: the guarantee comes from the root conftest, not from
a folder's."""

import threading
from collections.abc import Iterator
from contextlib import contextmanager

import langsmith
import pytest
from langchain_core.messages import AIMessage
from langsmith import run_trees
from langsmith import utils as ls_utils

from fakes import RecordingClient, fake_chat_model


@pytest.fixture
def tracing_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[RecordingClient]:
    """A developer's `.env`: tracing on, with a key. Yields LangSmith's default client, where a leak would go."""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-not-a-key")
    ls_utils.get_env_var.cache_clear()  # langsmith caches environment reads
    default = run_trees.get_cached_client()
    assert isinstance(default, RecordingClient), "LangSmith's default client would reach the network"
    yield default
    ls_utils.get_env_var.cache_clear()


@contextmanager
def without_the_guard() -> Iterator[None]:
    langsmith.configure(enabled=None)
    try:
        yield
    finally:
        langsmith.configure(enabled=False)


def call_a_model() -> None:
    fake_chat_model(AIMessage("It weighs tokens.")).invoke("What is attention?")


def test_a_model_call_sends_no_trace_with_tracing_on_in_the_environment(tracing_env: RecordingClient) -> None:
    call_a_model()
    assert tracing_env.payloads == []


def test_a_model_call_on_another_thread_sends_no_trace(tracing_env: RecordingClient) -> None:
    # TestClient runs the app on its own thread, which doesn't inherit the test's context variables
    thread = threading.Thread(target=call_a_model)
    thread.start()
    thread.join()
    assert tracing_env.payloads == []


def test_positive_control_without_the_guard_the_environment_turns_tracing_on(tracing_env: RecordingClient) -> None:
    with without_the_guard():
        call_a_model()
    assert any(p["op"] == "create" for p in tracing_env.payloads)
    tracing_env.payloads.clear()  # sent on purpose; the root conftest fails a test that leaves a trace behind

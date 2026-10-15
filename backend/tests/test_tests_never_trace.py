"""ADR 0017: no test sends a trace, whatever environment is loaded (an IDE runner's `.env`, `uv run --env-file`, an
exported shell). This file sits outside `tests/unit` on purpose: the guarantee comes from the root conftest, not from
a folder's."""

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import langsmith
import pytest
from langchain_core.messages import AIMessage
from langsmith import run_trees
from langsmith import utils as ls_utils

from fakes import RecordingClient, fake_chat_model
from smart_tutor.shared.adapters.tracing import start_tracing, tracing_enabled
from smart_tutor.shared.config import Settings


@pytest.fixture
def tracing_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[RecordingClient]:
    """A developer's `.env`: tracing on, with a key. Yields LangSmith's default client, where a leak would go."""
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGSMITH_TRACING_V2", raising=False)
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


def test_positive_control_without_the_guard_a_dotenv_langfuse_key_pair_turns_tracing_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "SMART_TUTOR_LANGFUSE_URL=https://langfuse.example\n"
        "SMART_TUTOR_LANGFUSE_PUBLIC_KEY=pk-lf-x\nSMART_TUTOR_LANGFUSE_SECRET_KEY=sk-lf-x\n"
    )
    monkeypatch.chdir(tmp_path)
    for name in ("URL", "PUBLIC_KEY", "SECRET_KEY"):
        monkeypatch.delenv(f"SMART_TUTOR_LANGFUSE_{name}", raising=False)
    assert tracing_enabled(Settings())


def test_start_tracing_keeps_langsmith_off_whatever_the_environment_says(
    tracing_env: RecordingClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    with without_the_guard():
        ls_utils.get_env_var.cache_clear()
        assert start_tracing(Settings(langfuse_url="")) is None
        ls_utils.get_env_var.cache_clear()  # a fresh process reads the environment after startup
        call_a_model()
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert os.environ["LANGSMITH_TRACING_V2"] == "false"
    assert tracing_env.payloads == []


def test_a_langfuse_url_in_the_environment_does_not_reach_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "SMART_TUTOR_LANGFUSE_URL=https://langfuse.example\n"
        "SMART_TUTOR_LANGFUSE_PUBLIC_KEY=pk-lf-x\nSMART_TUTOR_LANGFUSE_SECRET_KEY=sk-lf-x\n"
    )
    monkeypatch.chdir(tmp_path)  # Settings reads ./.env
    assert Settings().langfuse_url == ""
    assert start_tracing(Settings(learner_hash_key="k")) is None


def test_positive_control_without_the_guard_a_dotenv_langfuse_url_turns_tracing_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("SMART_TUTOR_LANGFUSE_URL=https://langfuse.example\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SMART_TUTOR_LANGFUSE_URL")
    assert Settings().langfuse_url == "https://langfuse.example"

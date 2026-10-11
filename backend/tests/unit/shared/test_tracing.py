"""Keyed learner hash and LangSmith run tracing (PRD §10.4): the learner appears only as an HMAC of their user id."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import langsmith
import pytest
from langchain_core.messages import AIMessage
from langsmith import run_trees
from langsmith import utils as ls_utils

from fakes import RecordingClient, fake_chat_model
from smart_tutor.shared.adapters.tracing import (
    LangSmithRunTracing,
    LearnerHasher,
    learner_hasher,
    never_raising,
    run_metadata,
    start_tracing,
)
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId


def test_the_hash_is_stable_for_one_learner_and_differs_between_learners() -> None:
    hasher = LearnerHasher("key-one")
    assert hasher(UserId("ada")) == hasher(UserId("ada"))
    assert hasher(UserId("ada")) != hasher(UserId("bob"))
    assert len(hasher(UserId("ada"))) == 64 and "ada" not in hasher(UserId("ada"))


def test_the_hash_changes_when_the_key_changes() -> None:
    assert LearnerHasher("key-one")(UserId("ada")) != LearnerHasher("key-two")(UserId("ada"))


def test_an_empty_key_is_refused() -> None:
    with pytest.raises(ValueError, match="SMART_TUTOR_LEARNER_HASH_KEY"):
        LearnerHasher("")


def test_the_key_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMART_TUTOR_LEARNER_HASH_KEY", "from-env")
    hasher = learner_hasher(Settings())
    assert hasher is not None and hasher(UserId("ada")) == LearnerHasher("from-env")(UserId("ada"))


def test_no_key_is_fine_while_tracing_is_off() -> None:
    with langsmith.tracing_context(enabled=False):
        assert learner_hasher(Settings(learner_hash_key="")) is None


def test_no_key_refuses_to_start_while_tracing_is_on() -> None:
    with langsmith.tracing_context(enabled=True), pytest.raises(RuntimeError, match="SMART_TUTOR_LEARNER_HASH_KEY"):
        learner_hasher(Settings(learner_hash_key=""))


def test_run_metadata_names_the_deployment_and_models() -> None:
    meta = run_metadata(Settings(deployment="on-premise"))
    assert meta == {
        "deployment": "on-premise",
        "chat_model": Settings().models.agent.model_id,
        "embedding_model": Settings().models.embedding.model_id,
    }


def test_a_run_and_its_model_calls_trace_into_the_given_project_with_the_learner_hash() -> None:
    recorder = RecordingClient()
    tracing = LangSmithRunTracing(LearnerHasher("k"), "proj-ingestion", {"deployment": "local"}, client=recorder)
    model = fake_chat_model(AIMessage("A summary."))
    with langsmith.tracing_context(enabled=True), tracing.run("ingest", UserId("user-123"), {"content_id": "c-1"}):
        model.invoke("Describe these pages.")
    created = [p for p in recorder.payloads if p["op"] == "create"]
    root = next(p for p in created if p["name"] == "ingest")
    assert root["session_name"] == "proj-ingestion"
    meta = root["extra"]["metadata"]
    assert meta["content_id"] == "c-1" and meta["deployment"] == "local"
    assert meta["learner_hash"] == LearnerHasher("k")(UserId("user-123"))
    children = [p for p in created if p.get("parent_run_id") is not None]
    assert children and all(p["session_name"] == "proj-ingestion" for p in children)
    assert "user-123" not in json.dumps(recorder.payloads, default=str)


@contextmanager
def _broken(on: str) -> Iterator[str]:
    if on == "enter":
        raise ConnectionError("cannot start")
    yield "traced"
    if on == "exit":
        raise ConnectionError("cannot end")


def test_a_trace_that_cannot_start_runs_the_work_untraced() -> None:
    with never_raising(_broken("enter"), "untraced") as value:
        ran = value
    assert ran == "untraced"


def test_a_trace_that_cannot_end_leaves_the_work_done() -> None:
    with never_raising(_broken("exit"), "untraced") as value:
        ran = value
    assert ran == "traced"


def test_the_works_own_error_still_propagates() -> None:
    with pytest.raises(KeyError), never_raising(_broken("none"), "untraced"):
        raise KeyError("work failed")


class _FailingClient(RecordingClient):
    def create_run(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError("LangSmith is down")

    def update_run(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError("LangSmith is down")


def test_a_failing_langsmith_never_fails_the_work_of_a_run() -> None:
    client = _FailingClient()
    tracing = LangSmithRunTracing(LearnerHasher("k"), "proj-ingestion", {}, client=client)
    model = fake_chat_model(AIMessage("A summary."))
    with langsmith.tracing_context(enabled=True, client=client), tracing.run("ingest", UserId("u"), {}):
        assert model.invoke("Describe these pages.").content == "A summary."


@pytest.fixture
def fresh_langsmith_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """LangSmith caches its env vars and default client; start and end each test without them."""
    monkeypatch.setattr(run_trees, "_CLIENT", None)
    ls_utils.get_env_var.cache_clear()
    yield
    ls_utils.get_env_var.cache_clear()


@pytest.mark.usefixtures("fresh_langsmith_settings")
def test_a_sampling_rate_outside_zero_to_one_refuses_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING_SAMPLING_RATE", "2")
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-not-a-key")
    with langsmith.tracing_context(enabled=True), pytest.raises(ls_utils.LangSmithUserError, match="SAMPLING_RATE"):
        start_tracing(Settings(learner_hash_key="k"))


@pytest.mark.usefixtures("fresh_langsmith_settings")
def test_start_tracing_gives_the_hasher_and_builds_no_client_while_tracing_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING_SAMPLING_RATE", "2")  # not read while tracing is off
    with langsmith.tracing_context(enabled=False):
        hasher = start_tracing(Settings(learner_hash_key="k"))
    assert hasher is not None and run_trees._CLIENT is None

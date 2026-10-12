"""Keyed learner hash, LangSmith run tracing (until Task 2 replaces it), and Phoenix tracing setup (PRD §10.4, ADR
0017): where spans go, with which key, how many, and the learner only as an HMAC of their user id."""

import http.server
import json
import random
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import langsmith
import pytest
from langchain_core.messages import AIMessage
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from pydantic import ValidationError

from fakes import RecordingClient, fake_chat_model, recorded_traces
from smart_tutor.shared.adapters.tracing import (
    LangSmithRunTracing,
    LearnerHasher,
    ingestion_project,
    learner_hasher,
    never_raising,
    otlp_exporter,
    phoenix_traces,
    root_ids,
    root_span_id,
    run_metadata,
    start_tracing,
    tracing_enabled,
)
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId

URL = "http://127.0.0.1:9"  # nothing listens


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


class _UpdateFailsClient(RecordingClient):
    def update_run(self, *args: Any, **kwargs: Any) -> None:
        raise ConnectionError("LangSmith is down")


def test_a_trace_that_cannot_end_leaves_no_context_for_the_next_run() -> None:
    """LangSmith skips restoring its context when ending fails; a long-lived worker would carry the run's metadata."""
    failing, recording = _UpdateFailsClient(), RecordingClient()
    hasher = LearnerHasher("k")
    first = LangSmithRunTracing(hasher, "p", {}, client=failing).run("ingest", UserId("a"), {"content_id": "c-1"})
    with langsmith.tracing_context(enabled=True, client=failing):
        with first:
            pass
        assert not langsmith.get_tracing_context()["metadata"]
        assert langsmith.get_tracing_context()["parent"] is None
    second = LangSmithRunTracing(hasher, "p", {}, client=recording).run("ingest", UserId("b"), {"content_id": "c-2"})
    with langsmith.tracing_context(enabled=True, client=recording), second:
        pass
    created = next(p for p in recording.payloads if p["op"] == "create")
    assert created["extra"]["metadata"]["content_id"] == "c-2"
    assert created["extra"]["metadata"]["learner_hash"] == hasher(UserId("b"))


def test_without_a_phoenix_url_the_process_is_untraced() -> None:
    assert not tracing_enabled(Settings(phoenix_url="", learner_hash_key="k"))
    assert start_tracing(Settings(phoenix_url="", learner_hash_key="k"), "p") is None


def test_locally_a_url_without_a_key_traces() -> None:
    assert tracing_enabled(Settings(deployment="local", phoenix_url=URL))


def test_a_deployed_process_without_its_key_runs_untraced() -> None:
    settings = Settings(deployment="on-premise", phoenix_url=URL, learner_hash_key="k")
    assert not tracing_enabled(settings) and start_tracing(settings, "p") is None


def test_a_deployed_process_with_its_key_traces() -> None:
    assert tracing_enabled(Settings(deployment="on-premise", phoenix_url=URL, phoenix_api_key="key"))


def test_no_learner_hash_key_is_fine_while_untraced() -> None:
    assert learner_hasher(Settings(phoenix_url="", learner_hash_key="")) is None


def test_no_learner_hash_key_refuses_to_start_while_tracing_is_on() -> None:
    with pytest.raises(RuntimeError, match="SMART_TUTOR_LEARNER_HASH_KEY"):
        start_tracing(Settings(phoenix_url=URL, learner_hash_key=""), "p")


@pytest.mark.parametrize("rate", [-0.1, 1.5, 2])
def test_a_sampling_rate_outside_zero_to_one_refuses_to_start(rate: float) -> None:
    with pytest.raises(ValidationError, match="trace_sampling_rate"):
        Settings(trace_sampling_rate=rate)


def test_the_ingestion_project_sits_beside_the_ask_project() -> None:
    assert ingestion_project(Settings(phoenix_project="smart-tutor-on-premise")) == "smart-tutor-on-premise-ingestion"


def test_a_span_started_in_root_ids_takes_the_run_id() -> None:
    run_id = uuid.uuid4()
    with recorded_traces() as (traces, spans):
        with root_ids(run_id):
            span = traces.tracer().start_span("ask")
        child = traces.tracer().start_span("child")  # outside: random ids
        span.end()
        child.end()
    ask, other = spans.get_finished_spans()
    assert ask.context.trace_id == run_id.int and ask.context.span_id == root_span_id(run_id)
    assert root_span_id(run_id) == run_id.int & 0xFFFF_FFFF_FFFF_FFFF
    assert other.context.trace_id != run_id.int


def test_the_sampling_rate_keeps_that_share_of_traces() -> None:
    for rate, kept in ((0.0, 0), (1.0, 20)):
        with recorded_traces(sampling_rate=rate) as (traces, spans):
            for _ in range(20):
                traces.tracer().start_span("ask").end()
        assert len(spans.get_finished_spans()) == kept


def _kept_share(rate: float, run_ids: list[uuid.UUID]) -> float:
    with recorded_traces(sampling_rate=rate) as (traces, spans):
        for run_id in run_ids:
            with root_ids(run_id):
                traces.tracer().start_span("ask").end()
    return len(spans.get_finished_spans()) / len(run_ids)


def test_run_id_traces_are_kept_at_the_configured_share() -> None:
    rng = random.Random(0)
    run_ids = [uuid.UUID(int=rng.getrandbits(128), version=4) for _ in range(2000)]
    assert 0.4 < _kept_share(0.5, run_ids) < 0.6
    assert 0.15 < _kept_share(0.25, run_ids) < 0.35


def test_a_run_id_is_always_sampled_the_same_way() -> None:
    rng = random.Random(1)
    run_ids = [uuid.UUID(int=rng.getrandbits(128), version=4) for _ in range(200)]
    assert _kept_share(0.5, run_ids) == _kept_share(0.5, run_ids)


def test_only_the_root_span_takes_the_run_ids() -> None:
    run_id = uuid.uuid4()
    with recorded_traces() as (traces, spans):
        with root_ids(run_id):
            first = traces.tracer().start_span("ask")
            second = traces.tracer().start_span("other")
        first.end()
        second.end()
    a, b = spans.get_finished_spans()
    assert a.context.span_id == root_span_id(run_id)
    assert b.context.span_id != root_span_id(run_id)


class _Collector(http.server.BaseHTTPRequestHandler):
    seen: list[tuple[str, dict[str, str]]] = []

    def do_POST(self) -> None:  # noqa: N802 (http.server's name)
        self.rfile.read(int(self.headers["Content-Length"]))
        _Collector.seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}))
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture
def collector() -> Iterator[str]:
    _Collector.seen = []
    server = http.server.HTTPServer(("127.0.0.1", 0), _Collector)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def _send_one_span(settings: Settings) -> None:
    traces = phoenix_traces("p", 1.0, SimpleSpanProcessor(otlp_exporter(settings)), LearnerHasher("k"), {})
    try:
        traces.tracer().start_span("ask").end()
    finally:
        traces.shutdown()


def test_spans_go_to_the_traces_endpoint_with_the_key_as_a_bearer_token(collector: str) -> None:
    _send_one_span(Settings(phoenix_url=collector + "/", phoenix_api_key="phoenix-key-under-test"))
    [(path, headers)] = _Collector.seen
    assert path == "/v1/traces"  # the bare base URL answers 405
    assert headers["authorization"] == "Bearer phoenix-key-under-test"


def test_without_a_key_no_authorization_header_is_sent(collector: str) -> None:
    _send_one_span(Settings(phoenix_url=collector))
    [(_, headers)] = _Collector.seen
    assert "authorization" not in headers

"""Keyed learner hash, run tracing, and Phoenix tracing setup (PRD §10.4, ADR 0017): where spans go, with which key,
how many, and the learner only as an HMAC of their user id."""

import http.server
import json
import random
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from langchain_core.messages import AIMessage
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.trace import StatusCode
from pydantic import ValidationError

from fakes import FailingExporter, fake_chat_model, recorded_traces
from smart_tutor.shared.adapters.tracing import (
    LearnerHasher,
    PhoenixRunTracing,
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


def ingest(tracing: PhoenixRunTracing, user: str = "user-123", content: str = "c-1", fail: bool = False) -> str:
    with tracing.run("ingest", UserId(user), {"content_id": content}):
        reply = fake_chat_model(AIMessage("A summary.")).invoke("Describe these pages.")
        if fail:
            raise KeyError("work failed")
    return str(reply.content)


def test_an_ingest_is_a_root_span_with_its_metadata_and_the_model_call_beneath_it() -> None:
    with recorded_traces(metadata={"deployment": "local"}) as (traces, spans):
        ingest(PhoenixRunTracing(traces))
    finished = spans.get_finished_spans()
    [root] = [s for s in finished if s.name == "ingest"]
    assert root.parent is None
    assert root.attributes is not None
    metadata = json.loads(str(root.attributes["metadata"]))
    assert metadata == {
        "deployment": "local",
        "content_id": "c-1",
        "learner_hash": LearnerHasher("k")(UserId("user-123")),
    }
    children = [s for s in finished if s is not root]
    assert children and all(s.context.trace_id == root.context.trace_id for s in children)
    assert "user-123" not in json.dumps([s.to_json() for s in finished])


def test_each_ingest_is_its_own_trace() -> None:
    with recorded_traces() as (traces, spans):
        tracing = PhoenixRunTracing(traces)
        ingest(tracing, content="c-1")
        ingest(tracing, content="c-2")
    roots = [s for s in spans.get_finished_spans() if s.name == "ingest"]
    assert len({s.context.trace_id for s in roots}) == 2 and all(s.parent is None for s in roots)


def test_a_failed_ingest_ends_its_span_as_an_error_and_the_error_propagates() -> None:
    with recorded_traces() as (traces, spans), pytest.raises(KeyError):
        ingest(PhoenixRunTracing(traces), fail=True)
    [root] = [s for s in spans.get_finished_spans() if s.name == "ingest"]
    assert root.status.status_code is StatusCode.ERROR


def test_a_failing_exporter_never_fails_the_ingest() -> None:
    with recorded_traces(exporter=FailingExporter()) as (traces, _):
        assert ingest(PhoenixRunTracing(traces)) == "A summary."


def test_a_collector_that_is_down_never_fails_the_ingest() -> None:
    settings = Settings(phoenix_url=URL)  # nothing listens
    traces = phoenix_traces("p", 1.0, BatchSpanProcessor(otlp_exporter(settings, timeout=1)), LearnerHasher("k"), {})
    try:
        assert ingest(PhoenixRunTracing(traces)) == "A summary."
    finally:
        traces.shutdown()  # the failed export is logged, not raised


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

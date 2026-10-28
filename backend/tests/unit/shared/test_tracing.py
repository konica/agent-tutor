"""Keyed learner hash and run tracing setup for Langfuse (PRD §10.4, ADR 0023): where spans go, with which keys, and
the learner only as an HMAC of their user id."""

import base64
import http.server
import inspect
import json
import logging
import random
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.trace import StatusCode
from pydantic import ValidationError

from fakes import FailingExporter, fake_chat_model, recorded_traces
from smart_tutor.shared.adapters import tracing as tracing_module
from smart_tutor.shared.adapters.tracing import (
    LearnerHasher,
    OtelRunTracing,
    OtelTraces,
    langfuse_exporter,
    learner_attributes,
    learner_hasher,
    never_raising,
    otel_traces,
    root_ids,
    root_span_id,
    run_metadata,
    span_attributes,
    start_tracing,
    tracing_enabled,
)
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId

URL = "http://127.0.0.1:9"  # nothing listens
LANGFUSE = {"langfuse_public_key": "pk-lf-test", "langfuse_secret_key": "sk-lf-test"}
UNTRACED = "SMART_TUTOR_LANGFUSE_URL or its keys are not set; running untraced"


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


def ingest(tracing: OtelRunTracing, user: str = "user-123", content: str = "c-1", fail: bool = False) -> str:
    with tracing.run("ingest", UserId(user), {"content_id": content}):
        reply = fake_chat_model(AIMessage("A summary.")).invoke("Describe these pages.")
        if fail:
            raise KeyError("work failed")
    return str(reply.content)


def test_an_ingest_is_a_root_span_with_its_metadata_and_the_model_call_beneath_it() -> None:
    with recorded_traces(metadata={"deployment": "local"}) as (traces, spans):
        ingest(OtelRunTracing(traces))
    finished = spans.get_finished_spans()
    [root] = [s for s in finished if s.name == "ingest"]
    assert root.parent is None
    assert root.attributes is not None
    metadata = {k: v for k, v in root.attributes.items() if k.startswith("langfuse.trace.metadata.")}
    assert metadata == {
        "langfuse.trace.metadata.deployment": "local",
        "langfuse.trace.metadata.content_id": "c-1",
        "langfuse.trace.metadata.learner_hash": LearnerHasher("k")(UserId("user-123")),
    }
    assert "metadata" not in root.attributes  # OpenInference's JSON copy is not used; Langfuse reads the keys above
    children = [s for s in finished if s is not root]
    assert children and all(s.context.trace_id == root.context.trace_id for s in children)
    assert "user-123" not in json.dumps([s.to_json() for s in finished])


def test_every_ingest_span_names_the_learner_hash_as_its_user() -> None:
    with recorded_traces() as (traces, spans):
        ingest(OtelRunTracing(traces))
    finished = spans.get_finished_spans()
    assert len(finished) > 1  # the root and the model call
    learner = LearnerHasher("k")(UserId("user-123"))
    assert all(s.attributes is not None and s.attributes["user.id"] == learner for s in finished)
    assert all(s.attributes is not None and "session.id" not in s.attributes for s in finished)


def test_span_attributes_give_langfuse_each_metadata_key_as_text_and_the_input() -> None:
    attributes = span_attributes({"question": "Q?"}, {"limited": False, "chunks": 2, "thread_id": "t-1"})
    assert attributes["langfuse.trace.metadata.limited"] == "false"
    assert attributes["langfuse.trace.metadata.chunks"] == "2"
    assert attributes["langfuse.trace.metadata.thread_id"] == "t-1"
    assert attributes["langfuse.observation.input"] == attributes["input.value"]
    assert attributes["openinference.span.kind"] == "CHAIN"
    assert "metadata" not in attributes


def test_a_metadata_value_that_is_not_text_reaches_langfuse_as_json() -> None:
    attributes = span_attributes(None, {"document_ids": ["d1", "d2"], "limits": {"pages": 3}, "share": 0.5})
    assert json.loads(attributes["langfuse.trace.metadata.document_ids"]) == ["d1", "d2"]
    assert json.loads(attributes["langfuse.trace.metadata.limits"]) == {"pages": 3}
    assert attributes["langfuse.trace.metadata.share"] == "0.5"


def test_a_metadata_value_of_none_gives_langfuse_no_key() -> None:
    attributes = span_attributes(None, {"decline": None})
    assert "langfuse.trace.metadata.decline" not in attributes
    assert "langfuse.observation.input" not in attributes


def test_a_thread_is_the_session_only_when_its_id_is_not_empty() -> None:
    assert learner_attributes("h", None) == {"user.id": "h"}
    assert learner_attributes("h", "t-1") == {"user.id": "h", "session.id": "t-1"}
    assert learner_attributes("h", "") == {"user.id": "h"}


def test_each_ingest_is_its_own_trace() -> None:
    with recorded_traces() as (traces, spans):
        tracing = OtelRunTracing(traces)
        ingest(tracing, content="c-1")
        ingest(tracing, content="c-2")
    roots = [s for s in spans.get_finished_spans() if s.name == "ingest"]
    assert len({s.context.trace_id for s in roots}) == 2 and all(s.parent is None for s in roots)


def test_a_failed_ingest_ends_its_span_as_an_error_and_the_error_propagates() -> None:
    with recorded_traces() as (traces, spans), pytest.raises(KeyError):
        ingest(OtelRunTracing(traces), fail=True)
    [root] = [s for s in spans.get_finished_spans() if s.name == "ingest"]
    assert root.status.status_code is StatusCode.ERROR


def test_a_failing_exporter_never_fails_the_ingest() -> None:
    with recorded_traces(exporter=FailingExporter()) as (traces, _):
        assert ingest(OtelRunTracing(traces)) == "A summary."


def test_a_collector_that_is_down_never_fails_the_ingest() -> None:
    settings = Settings(langfuse_url=URL, **LANGFUSE)  # nothing listens
    traces = otel_traces(
        "local", 1.0, [BatchSpanProcessor(langfuse_exporter(settings, timeout=1))], LearnerHasher("k"), {}
    )
    try:
        assert ingest(OtelRunTracing(traces)) == "A summary."
    finally:
        traces.shutdown()  # the failed export is logged, not raised


def test_tracing_needs_the_langfuse_url_and_both_keys() -> None:
    assert tracing_enabled(Settings(langfuse_url=URL, **LANGFUSE))
    assert not tracing_enabled(Settings(langfuse_url="", **LANGFUSE))
    assert not tracing_enabled(Settings(langfuse_url=URL, langfuse_public_key="pk-lf-test"))
    assert not tracing_enabled(Settings(langfuse_url=URL, langfuse_secret_key="sk-lf-test"))


def _send_one_span_to_langfuse(settings: Settings) -> None:
    traces = otel_traces("local", 1.0, [SimpleSpanProcessor(langfuse_exporter(settings))], LearnerHasher("k"), {})
    try:
        traces.tracer().start_span("ask").end()
    finally:
        traces.shutdown()


def test_spans_go_to_langfuse_otlp_endpoint_with_basic_auth_and_ingestion_v4(collector: str) -> None:
    _send_one_span_to_langfuse(Settings(langfuse_url=collector + "/", **LANGFUSE))
    [(path, headers)] = _Collector.seen
    assert path == "/api/public/otel/v1/traces"
    assert headers["authorization"] == "Basic " + base64.b64encode(b"pk-lf-test:sk-lf-test").decode()
    assert headers["x-langfuse-ingestion-version"] == "4"


def test_the_environment_is_a_resource_attribute() -> None:
    with recorded_traces() as (traces, spans):
        traces.tracer().start_span("ask").end()
    [span] = spans.get_finished_spans()
    assert span.resource.attributes["langfuse.environment"] == "local"
    assert "openinference.project.name" not in span.resource.attributes  # Langfuse's project comes from the keys


def _processor_counts(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """How many span processors `start_tracing` gives each `otel_traces` call it makes."""
    counts: list[int] = []
    real = tracing_module.otel_traces

    def spy(*args: Any, **kwargs: Any) -> OtelTraces:
        counts.append(len(inspect.signature(real).bind(*args, **kwargs).arguments["processors"]))
        return real(*args, **kwargs)

    monkeypatch.setattr(tracing_module, "otel_traces", spy)
    return counts


def test_with_the_langfuse_url_and_keys_spans_go_to_one_exporter(monkeypatch: pytest.MonkeyPatch) -> None:
    counts = _processor_counts(monkeypatch)
    traces = start_tracing(Settings(langfuse_url=URL, learner_hash_key="k", **LANGFUSE))
    assert traces is not None
    traces.shutdown()
    assert counts == [1]


@pytest.mark.parametrize(
    "langfuse",
    [
        {},
        {"langfuse_url": URL},
        {"langfuse_url": URL, "langfuse_public_key": "pk-lf-test"},
        {"langfuse_url": URL, "langfuse_secret_key": "sk-lf-test"},
        {"langfuse_url": "", **LANGFUSE},
    ],
)
def test_without_the_langfuse_url_or_its_keys_the_process_is_untraced(
    monkeypatch: pytest.MonkeyPatch, langfuse: dict[str, str]
) -> None:
    counts = _processor_counts(monkeypatch)
    settings = Settings(learner_hash_key="k", **langfuse)
    assert not tracing_enabled(settings) and start_tracing(settings) is None
    assert counts == []


def _logged(settings: Settings, caplog: pytest.LogCaptureFixture) -> list[tuple[int, str]]:
    with caplog.at_level(logging.INFO, logger=tracing_module.__name__):
        traces = start_tracing(settings)
    if traces is not None:
        traces.shutdown()
    return [(r.levelno, r.getMessage()) for r in caplog.records if r.name == tracing_module.__name__]


def test_untraced_locally_is_logged_as_info(caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings(deployment="local", langfuse_url=URL, learner_hash_key="k")
    assert _logged(settings, caplog) == [(logging.INFO, UNTRACED)]


def test_deployed_with_a_url_but_without_keys_is_a_warning(caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings(
        deployment="on-premise", langfuse_url=URL, langfuse_public_key="pk-lf-test", learner_hash_key="k"
    )
    assert _logged(settings, caplog) == [(logging.WARNING, UNTRACED)]


def test_deployed_without_a_url_is_logged_as_info(caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings(deployment="on-premise", langfuse_url="", learner_hash_key="k")
    assert _logged(settings, caplog) == [(logging.INFO, UNTRACED)]


def test_tracing_logs_where_spans_go(caplog: pytest.LogCaptureFixture) -> None:
    settings = Settings(langfuse_url=URL, learner_hash_key="k", **LANGFUSE)
    assert _logged(settings, caplog) == [(logging.INFO, f"tracing into Langfuse at {URL}")]


def test_no_learner_hash_key_is_fine_while_untraced() -> None:
    assert learner_hasher(Settings(langfuse_url="", learner_hash_key="")) is None


def test_no_learner_hash_key_refuses_to_start_while_tracing_is_on() -> None:
    with pytest.raises(RuntimeError, match="SMART_TUTOR_LEARNER_HASH_KEY"):
        start_tracing(Settings(langfuse_url=URL, learner_hash_key="", **LANGFUSE))


@pytest.mark.parametrize("rate", [-0.1, 1.5, 2])
def test_a_sampling_rate_outside_zero_to_one_refuses_to_start(rate: float) -> None:
    with pytest.raises(ValidationError, match="trace_sampling_rate"):
        Settings(trace_sampling_rate=rate)


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

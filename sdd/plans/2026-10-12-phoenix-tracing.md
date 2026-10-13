# The agent and worker trace into Phoenix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The agent's `ask` and the worker's `ingest` trace into self-hosted Arize Phoenix through OpenTelemetry, and LangSmith leaves the agent, worker, and API runtime (ticket #289, parent #286).

**Architecture:** One adapter module, `smart_tutor/shared/adapters/tracing.py`, builds a process's OpenTelemetry `TracerProvider`: a batched OTLP/HTTP exporter to `<phoenix_url>/v1/traces` (`authorization: Bearer <key>` when a key is set), a parent-based trace-id-ratio sampler, the Phoenix project as a resource attribute, an id generator that makes an `ask` span's trace id the turn's `run_id`, and OpenInference's `LangChainInstrumentor` for LangGraph and model child spans. The agent's ask tracing goes behind a new port, `AskTracing` in `shared/ports/ask_tracing.py`, beside the worker's `RunTracing`. Both adapters (`PhoenixAskTracing`, `PhoenixRunTracing`) start true root spans. Then on-premise deploy, local Compose, the pilot smoke test, docs, and the PRD move from LangSmith to Phoenix.

**Tech Stack:** Python 3.12, `opentelemetry-sdk` 1.45, `opentelemetry-exporter-otlp-proto-http` 1.45, `openinference-instrumentation-langchain` 0.1.79, `openinference-semantic-conventions`, FastAPI, LangGraph, pytest; bash and Docker Compose for on-premise; Arize Phoenix 20.16.0.

**Spec:** GitHub issue #289 (`gh issue view 289`; its body is the spec and its comment holds the spike's lessons), ADR 0017 (`sdd/adr/0017-self-hosted-phoenix-for-runtime-tracing.md`), PRD §10.4, D25, ADR 0007, ADR 0014.

## Global Constraints

- Settings (env prefix `SMART_TUTOR_`): `phoenix_url` (Phoenix base URL; empty = untraced), `phoenix_api_key` (SecretStr; optional, the local Phoenix has no auth), `phoenix_project` (default `smart-tutor-local`), `trace_sampling_rate` (float, 0–1, default 1). Spans go to `<phoenix_url>/v1/traces`; the bare base URL answers 405.
- No URL → untraced. A deployed process (`deployment != "local"`) without `phoenix_api_key` → untraced, with a warning, as today without a LangSmith key.
- Tracing on without `SMART_TUTOR_LEARNER_HASH_KEY` → startup refuses (`RuntimeError` naming `SMART_TUTOR_LEARNER_HASH_KEY`). A sampling rate outside 0–1 → startup refuses (pydantic `ValidationError`).
- `ask` span: a true root (no parent); trace id = `run_id.int`, span id = `run_id.int & 0xFFFF_FFFF_FFFF_FFFF`. Its metadata at start: `deployment`, `chat_model`, `embedding_model`, `thread_id` (when present), `limited`, `learner_hash`, plus the inputs; at the end: the answer and `decline`, `chunks`, or the error code.
- `ingest` span: a root span in project `<phoenix_project>-ingestion`, with `content_id` and `learner_hash` (plus the run metadata).
- Export failures are logged and never fail a request or a document's processing. No private SDK internals (`_`-prefixed names of opentelemetry, openinference, or langsmith) in `src/`.
- No token, user id, or email in any span attribute or event (ADR 0007).
- `smart_tutor` no longer imports `langsmith`; only `backend/evals` does. `lint-imports` enforces it.
- Native-cloud Helm charts (`deploy/helm/`) are not touched. The learner-hash secret keeps its name `<prefix>/langsmith/learner-hash-key` (native-cloud shares it).
- Tests never send traces (ADR 0017): the root conftest blanks `SMART_TUTOR_PHOENIX_URL` for the session and fails a test that leaves LangChain instrumented.
- Ratings to Phoenix are #290, not this slice. Here the API's LangSmith feedback adapter is removed (no LangSmith run exists for new turns any more); ratings are saved with the turn only, as on-premise already does, until #290.
- Write code that reads like the surrounding code: comment density, naming, docstrings that state the rule and cite the PRD/ADR.
- Commands run from `backend/` unless stated. Checks: `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Infra: `cd infra && uv run pytest`.

## Review Focus

- A client that disconnects mid-stream (`aclose()` on `answer_events`): the `ask` span must still end and be exported, and the context detach must not raise. Pinned in Task 3 (`test_a_closed_stream_still_ends_the_ask_span`).
- A sampled-out ask (`trace_sampling_rate` 0): no `ask` span and no LangGraph or model child spans, so children follow the root and none is orphaned. Pinned in Task 3 (`test_a_sampled_out_ask_exports_no_span_at_all`).
- A developer's old `.env` with `LANGSMITH_TRACING=true`: the Compose agent and worker must not trace into LangSmith. Pinned in Task 5 (Compose sets `LANGSMITH_TRACING: "false"`; a Compose test asserts it).
- The on-premise worker sits behind Squid (`HTTP(S)_PROXY`): its OTLP export to `http://phoenix:6006` must bypass the proxy. Pinned in Task 6 (`NO_PROXY: phoenix` asserted in `test_host.py`).
- A `.env` loaded into a test run that points at a real Phoenix: no test may send to it. Pinned in Task 4 (`test_tests_never_trace.py`, with a positive control).

---

## File map

| File | Change | Responsibility |
|---|---|---|
| `backend/pyproject.toml`, `backend/uv.lock` | modify | OTel/OpenInference deps (already added in the worktree, uncommitted), `langsmith` → `eval` extra, import-linter contract |
| `backend/src/smart_tutor/shared/config.py` | modify | Phoenix and sampling settings |
| `backend/src/smart_tutor/shared/adapters/tracing.py` | rewrite | Provider setup, run-id ids, exporter, learner hash, `PhoenixRunTracing` |
| `backend/src/smart_tutor/shared/adapters/ask_tracing.py` | create | `PhoenixAskTracing` |
| `backend/src/smart_tutor/shared/ports/ask_tracing.py` | create | `AskRun`, `AskTrace`, `AskTracing`, `NoAskTracing` |
| `backend/src/smart_tutor/apps/agent/tracing.py` | delete | replaced by the port and the adapter |
| `backend/src/smart_tutor/apps/agent/server.py` | modify | wiring |
| `backend/src/smart_tutor/apps/worker/main.py` | modify | wiring |
| `backend/src/smart_tutor/apps/api/services.py` | modify | `NoAnswerFeedback()` |
| `backend/src/smart_tutor/tutoring/adapters/langsmith_feedback.py` | delete | |
| docstrings: `apps/api/routes/threads.py`, `shared/domain/ids.py`, `apps/jobs/__init__.py`, `apps/jobs/retention.py`, `tutoring/ports/answer_feedback.py`, `tutoring/README.md`, `backend/AGENTS.md` | modify | LangSmith → Phoenix wording |
| `web/src/api/` | regenerate | the `run_id` field description changes |
| `backend/tests/conftest.py`, `backend/tests/test_tests_never_trace.py` | modify | Phoenix guards |
| `backend/tests/fakes/tracing.py`, `backend/tests/fakes/__init__.py` | modify | `recorded_traces()`; drop `FeedbackClient`, `InlineExecutor` |
| `backend/tests/unit/shared/test_tracing.py` | rewrite | |
| `backend/tests/unit/apps/agent/test_ask_trace.py`, `test_no_token_in_traces.py`, `test_server.py` | rewrite/modify | |
| `backend/tests/unit/tutoring/test_langsmith_feedback.py` | delete | |
| `.env.example`, `compose.yaml`, `compose.ci.yaml`, `README.md`, `AGENTS.md` | modify | local |
| `deploy/on-premise/{deploy.sh,compose.yaml,check-egress.py,check-worker.sh}`, `infra/tests/{test_host.py,test_check_egress.py}`, `docs/runbooks/on-premise-deploy.md`, `docs/runbooks/on-premise-monitoring.md` | modify | on-premise |
| `deploy/pilot/smoke_test.py`, `infra/tests/test_smoke_test.py` | modify | Phoenix trace check |
| `sdd/prd.md`, `CONTEXT.md` | modify | v2.56 |

---

### Task 1: Settings and the Phoenix tracer provider

**Files:**
- Modify: `backend/pyproject.toml` (deps already added by `uv add`, uncommitted in the worktree; verify they are present), `backend/uv.lock`
- Modify: `backend/src/smart_tutor/shared/config.py`
- Rewrite: `backend/src/smart_tutor/shared/adapters/tracing.py` (this task writes the setup half; Task 2 adds `PhoenixRunTracing` to the same file. Until then keep the old `LangSmithRunTracing`, `ingestion_project()`, and `never_raising` so the worker still imports; Task 2 removes them.)
- Modify: `backend/tests/fakes/tracing.py`, `backend/tests/fakes/__init__.py`
- Modify: `backend/tests/conftest.py`
- Rewrite: `backend/tests/unit/shared/test_tracing.py` (keep the hasher tests; replace the LangSmith ones as Task 2 lands. In this task, delete only the tests for `learner_hasher`/`start_tracing` that relied on `ls_utils.tracing_is_enabled`, and the sampling-rate LangSmith tests.)

**Interfaces:**
- Produces (in `smart_tutor.shared.adapters.tracing`):
  - `KEY_SETTING = "SMART_TUTOR_LEARNER_HASH_KEY"`
  - `class LearnerHasher` (unchanged: `__init__(key: str)`, `__call__(user_id: UserId) -> str`)
  - `tracing_enabled(settings: Settings) -> bool`
  - `learner_hasher(settings: Settings) -> LearnerHasher | None`
  - `run_metadata(settings: Settings) -> dict[str, str]` (unchanged)
  - `ingestion_project(settings: Settings) -> str` → `f"{settings.phoenix_project}-ingestion"` (new signature; Task 2 switches the worker to it)
  - `root_span_id(run_id: uuid.UUID) -> int`
  - `root_ids(run_id: uuid.UUID) -> AbstractContextManager[None]`: spans started inside take `run_id` as trace id and `root_span_id(run_id)` as span id
  - `class RunIds(IdGenerator)`
  - `otlp_exporter(settings: Settings, timeout: float = EXPORT_TIMEOUT_SECONDS) -> OTLPSpanExporter`
  - `@dataclass(frozen=True) class PhoenixTraces: provider: TracerProvider; hasher: LearnerHasher; metadata: dict[str, str]`, with `tracer() -> opentelemetry.trace.Tracer` and `shutdown() -> None`
  - `phoenix_traces(project: str, sampling_rate: float, processor: SpanProcessor, hasher: LearnerHasher, metadata: Mapping[str, str]) -> PhoenixTraces` (builds the provider and instruments LangChain)
  - `start_tracing(settings: Settings, project: str) -> PhoenixTraces | None`
  - `span_attributes(inputs: Mapping[str, object] | None, metadata: Mapping[str, object]) -> dict[str, str]` (OpenInference CHAIN kind, `input.value` JSON, `metadata` JSON)
- Produces (in `fakes`): `recorded_traces(sampling_rate: float = 1.0, exporter: SpanExporter | None = None, metadata: Mapping[str, str] = META, hasher: LearnerHasher = LearnerHasher("k")) -> ContextManager[tuple[PhoenixTraces, InMemorySpanExporter]]`, and `META = {"deployment": "local", "chat_model": "chat-x", "embedding_model": "embed-y"}`.

- [ ] **Step 1: Settings.** In `shared/config.py`, replace the `learner_hash_key` comment and add the Phoenix settings after it:

```python
    # HMAC key for the learner hash in traces (PRD §10.4). A secret: <mode prefix>/langsmith/learner-hash-key in Secrets
    # Manager when deployed (the name predates Phoenix); required only while tracing is on.
    learner_hash_key: SecretStr = SecretStr("")
    # Runtime traces (PRD §10.4, ADR 0017): the environment's own Phoenix. Spans go to <phoenix_url>/v1/traces; empty
    # leaves the process untraced. http://localhost:10404 on the host, http://phoenix:6006 inside Compose.
    phoenix_url: str = ""
    # Phoenix system key, sent as `authorization: Bearer`: <prefix>/phoenix/api-key when deployed. The local Phoenix
    # has no sign-in, so none locally; a deployed process without it runs untraced.
    phoenix_api_key: SecretStr = SecretStr("")
    # The agent's project; the worker traces into <phoenix_project>-ingestion.
    phoenix_project: str = "smart-tutor-local"
    # Share of traces kept, 0–1 (the SSM parameter trace-sampling-rate when deployed). Outside 0–1 stops startup.
    trace_sampling_rate: float = Field(default=1.0, ge=0, le=1)
```

- [ ] **Step 2: The fake.** In `tests/fakes/tracing.py`, add (keep `RecordingClient` and `FakeRunTracing`; `FeedbackClient` and `InlineExecutor` go in Task 4):

```python
META = {"deployment": "local", "chat_model": "chat-x", "embedding_model": "embed-y"}


@contextmanager
def recorded_traces(
    sampling_rate: float = 1.0,
    exporter: SpanExporter | None = None,
    metadata: Mapping[str, str] = META,
    hasher: LearnerHasher | None = None,
) -> Iterator[tuple[PhoenixTraces, InMemorySpanExporter]]:
    """Phoenix tracing as the agent and worker set it up, but each span is kept in memory (or given to `exporter`) the
    moment it ends, instead of being sent. LangChain is instrumented only inside the block."""
    memory = InMemorySpanExporter()
    traces = phoenix_traces(
        "smart-tutor-test", sampling_rate, SimpleSpanProcessor(exporter or memory), hasher or LearnerHasher("k"), metadata
    )
    try:
        yield traces, memory
    finally:
        traces.shutdown()
```

Export `recorded_traces` and `META` (as `TRACE_META`, to avoid clashing with test-local `META` names) from `fakes/__init__.py`. Imports: `InMemorySpanExporter` from `opentelemetry.sdk.trace.export.in_memory_span_exporter`, `SimpleSpanProcessor`, `SpanExporter` from `opentelemetry.sdk.trace.export`.

- [ ] **Step 3: Write the failing tests** in `tests/unit/shared/test_tracing.py` (keep the four `LearnerHasher` tests and `test_run_metadata_names_the_deployment_and_models`):

```python
"""Phoenix tracing setup (PRD §10.4, ADR 0017): where spans go, with which key, how many, and the learner only as an
HMAC of their user id."""

import http.server
import threading
import uuid
from collections.abc import Iterator

import pytest
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from pydantic import ValidationError

from fakes import recorded_traces
from smart_tutor.shared.adapters.tracing import (
    LearnerHasher,
    ingestion_project,
    learner_hasher,
    otlp_exporter,
    phoenix_traces,
    root_ids,
    root_span_id,
    start_tracing,
    tracing_enabled,
)
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId

URL = "http://127.0.0.1:9"  # nothing listens


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
```

- [ ] **Step 4: Run them, expecting failures.** `uv run pytest tests/unit/shared/test_tracing.py -q` → ImportError on the new names.

- [ ] **Step 5: Implement the setup half of `shared/adapters/tracing.py`** (module docstring, then these definitions; keep `LearnerHasher` and `run_metadata` as they are):

```python
"""Runtime traces into the environment's own Phoenix (PRD §10.4, ADR 0017), through OpenTelemetry: a batched OTLP/HTTP
exporter, a parent-based trace-id ratio sampler, and OpenInference's LangChain instrumentation for the LangGraph and
model spans under our own root spans. Who a run is for appears only as a keyed hash of the learner's user id. Tokens,
user ids, and emails never reach a span (ADR 0007). Exporting runs on the SDK's own thread: a failed export is logged
by the SDK and dropped, and never fails the work it traces (#229)."""

EXPORT_TIMEOUT_SECONDS = 10.0
_LOW_64_BITS = 0xFFFF_FFFF_FFFF_FFFF
_root_run: ContextVar[uuid.UUID | None] = ContextVar("root_run", default=None)


def root_span_id(run_id: uuid.UUID) -> int:
    """An ask's root span id: the low 64 bits of its run id, so the API can address the span from the stored run id."""
    return run_id.int & _LOW_64_BITS


@contextmanager
def root_ids(run_id: uuid.UUID) -> Iterator[None]:
    """Spans started inside take `run_id` as their trace id and `root_span_id(run_id)` as their span id."""
    token = _root_run.set(run_id)
    try:
        yield
    finally:
        _root_run.reset(token)


class RunIds(IdGenerator):
    """Random ids, except inside `root_ids`."""

    def __init__(self) -> None:
        self._random = RandomIdGenerator()

    def generate_trace_id(self) -> int:
        run_id = _root_run.get()
        return run_id.int if run_id else self._random.generate_trace_id()

    def generate_span_id(self) -> int:
        run_id = _root_run.get()
        return (root_span_id(run_id) if run_id else 0) or self._random.generate_span_id()


def tracing_enabled(settings: Settings) -> bool:
    """Traced with a Phoenix URL; a deployed process also needs its key (the local Phoenix has no sign-in)."""
    if not settings.phoenix_url:
        return False
    return settings.deployment == "local" or bool(settings.phoenix_api_key.get_secret_value())


def learner_hasher(settings: Settings) -> LearnerHasher | None:
    """The configured hasher; None when no key is set and tracing is off. Refuses to start without a key while
    tracing is on, so a span never goes out without its learner hash."""
    key = settings.learner_hash_key.get_secret_value()
    if key:
        return LearnerHasher(key)
    if tracing_enabled(settings):
        raise RuntimeError(f"{KEY_SETTING} is not set, but tracing is on")
    return None


def otlp_exporter(settings: Settings, timeout: float = EXPORT_TIMEOUT_SECONDS) -> OTLPSpanExporter:
    key = settings.phoenix_api_key.get_secret_value()
    return OTLPSpanExporter(
        endpoint=settings.phoenix_url.rstrip("/") + "/v1/traces",  # the bare base URL answers 405
        headers={"authorization": f"Bearer {key}"} if key else None,
        timeout=timeout,
    )


@dataclass(frozen=True)
class PhoenixTraces:
    """Where this process's spans go, and what every root span says about the run."""

    provider: TracerProvider
    hasher: LearnerHasher
    metadata: dict[str, str]

    def tracer(self) -> Tracer:
        return self.provider.get_tracer("smart_tutor")

    def shutdown(self) -> None:
        """Send what is left and stop instrumenting LangChain (process exit)."""
        LangChainInstrumentor().uninstrument()
        self.provider.shutdown()


def phoenix_traces(
    project: str, sampling_rate: float, processor: SpanProcessor, hasher: LearnerHasher, metadata: Mapping[str, str]
) -> PhoenixTraces:
    provider = TracerProvider(
        resource=Resource({ResourceAttributes.PROJECT_NAME: project}),
        sampler=ParentBased(TraceIdRatioBased(sampling_rate)),
        id_generator=RunIds(),
    )
    provider.add_span_processor(processor)
    LangChainInstrumentor().instrument(tracer_provider=provider)
    return PhoenixTraces(provider, hasher, dict(metadata))


def start_tracing(settings: Settings, project: str) -> PhoenixTraces | None:
    """Startup for a process that traces: refuses tracing without a learner-hash key (see `learner_hasher`); None
    leaves the process untraced."""
    hasher = learner_hasher(settings)
    if not tracing_enabled(settings):
        if settings.phoenix_url:
            logger.warning("SMART_TUTOR_PHOENIX_API_KEY is not set; running untraced")
        else:
            logger.info("SMART_TUTOR_PHOENIX_URL is not set; running untraced")
        return None
    assert hasher is not None  # learner_hasher refuses tracing without a key
    exporter = otlp_exporter(settings)
    traces = phoenix_traces(
        project, settings.trace_sampling_rate, BatchSpanProcessor(exporter), hasher, run_metadata(settings)
    )
    logger.info("tracing into Phoenix project %s at %s", project, settings.phoenix_url)
    return traces


def span_attributes(inputs: Mapping[str, object] | None, metadata: Mapping[str, object]) -> dict[str, str]:
    """A root span's OpenInference attributes: a CHAIN, its inputs, and its metadata (Phoenix shows each key as
    `metadata.<key>`)."""
    attributes = {
        SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.CHAIN.value,
        SpanAttributes.METADATA: json.dumps(metadata),
    }
    if inputs is not None:
        attributes[SpanAttributes.INPUT_VALUE] = json.dumps(inputs)
        attributes[SpanAttributes.INPUT_MIME_TYPE] = OpenInferenceMimeTypeValues.JSON.value
    return attributes
```

Imports: `json`, `uuid`, `ContextVar`, `dataclass`, `Mapping`, `Iterator`, `contextmanager`; `from openinference.instrumentation.langchain import LangChainInstrumentor`; `from openinference.semconv.resource import ResourceAttributes`; `from openinference.semconv.trace import OpenInferenceMimeTypeValues, OpenInferenceSpanKindValues, SpanAttributes`; `from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter`; `from opentelemetry.sdk.resources import Resource`; `from opentelemetry.sdk.trace import SpanProcessor, TracerProvider`; `from opentelemetry.sdk.trace.export import BatchSpanProcessor`; `from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator`; `from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased`; `from opentelemetry.trace import Tracer`. If mypy reports missing stubs for `openinference.*`, add a `[[tool.mypy.overrides]]` with `ignore_missing_imports = true` for that module only.

- [ ] **Step 6: The root conftest guards.** In `tests/conftest.py`, extend the docstring ("…and no test reaches a Phoenix: `SMART_TUTOR_PHOENIX_URL` is blank for the session, so every `Settings()` is untraced, and a test that leaves LangChain instrumented fails.") and add:

```python
@pytest.fixture(autouse=True, scope="session")
def _phoenix_off() -> Iterator[None]:
    # The environment beats `.env` files in pydantic-settings, so a blank value wins over a developer's URL.
    patch = pytest.MonkeyPatch()
    patch.setenv("SMART_TUTOR_PHOENIX_URL", "")
    yield
    patch.undo()


@pytest.fixture(autouse=True)
def _no_instrumentation_left() -> Iterator[None]:
    yield
    instrumentor = LangChainInstrumentor()
    if instrumentor.is_instrumented_by_opentelemetry:
        instrumentor.uninstrument()
        pytest.fail("this test left LangChain instrumented; trace inside fakes.recorded_traces()")
```

- [ ] **Step 6b: Bridge the callers until Tasks 2–3.** The agent (`apps/agent/server.py:37,144`) and worker (`apps/worker/main.py:35-39,79`) call the old `start_tracing(settings)` and `ingestion_project()`. Rename the old LangSmith versions to `start_langsmith_tracing(settings)` and `langsmith_ingestion_project()` (bodies unchanged, except that `start_langsmith_tracing` calls the new `learner_hasher`) and point those two call sites at them; Tasks 2 and 3 delete them. In `tests/unit/apps/agent/test_server.py`, change `test_startup_refuses_tracing_without_a_learner_hash_key` to drop the `ls_utils` monkeypatch and pass `phoenix_url="http://127.0.0.1:9"` in its `Settings` (the new trigger for the refusal).

- [ ] **Step 7: Run** `uv run pytest tests/unit/shared/test_tracing.py -q` → PASS; then the whole suite `uv run pytest -q` (the worker and agent still use the old LangSmith pieces, which stay until Tasks 2–3) → PASS. `uv run ruff check . && uv run ruff format --check . && uv run mypy` → clean.

- [ ] **Step 8: Commit** (`git add backend/pyproject.toml backend/uv.lock backend/src/smart_tutor/shared backend/tests`):
`Set up OpenTelemetry tracing into Phoenix (#289)` — body: why (ADR 0017: LangSmith's cap; Phoenix per environment), what (settings, provider with run-id ids, bearer key, ratio sampler, test guards).

---

### Task 2: The worker's `ingest` span

**Files:**
- Modify: `backend/src/smart_tutor/shared/adapters/tracing.py` (add `PhoenixRunTracing`, a LangSmith-free `never_raising`; delete `LangSmithRunTracing` and `langsmith_ingestion_project()`. `start_langsmith_tracing` stays until Task 3, because the agent still calls it)
- Modify: `backend/src/smart_tutor/apps/worker/main.py`
- Test: `backend/tests/unit/shared/test_tracing.py`

**Interfaces:**
- Consumes: `PhoenixTraces`, `span_attributes`, `ingestion_project(settings)`, `start_tracing(settings, project)`, `fakes.recorded_traces`.
- Produces: `class PhoenixRunTracing(RunTracing): __init__(self, traces: PhoenixTraces)`; `never_raising[T](cm: AbstractContextManager[T], fallback: T) -> Iterator[T]` (same contract as today, without LangSmith's context restore).

- [ ] **Step 1: Failing tests** (append to `test_tracing.py`; remove the old LangSmith run-tracing tests, `_FailingClient`, `_UpdateFailsClient`, `fresh_langsmith_settings` and its tests; keep the three `never_raising` tests with `_broken`):

```python
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
    metadata = json.loads(root.attributes["metadata"])
    assert metadata == {"deployment": "local", "content_id": "c-1", "learner_hash": LearnerHasher("k")(UserId("user-123"))}
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


class _FailingExporter(SpanExporter):
    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        raise ConnectionError("Phoenix is down")

    def shutdown(self) -> None:
        pass


def test_a_failing_exporter_never_fails_the_ingest() -> None:
    with recorded_traces(exporter=_FailingExporter()) as (traces, _):
        assert ingest(PhoenixRunTracing(traces)) == "A summary."


def test_a_collector_that_is_down_never_fails_the_ingest() -> None:
    settings = Settings(phoenix_url=URL)  # nothing listens
    traces = phoenix_traces("p", 1.0, BatchSpanProcessor(otlp_exporter(settings, timeout=1)), LearnerHasher("k"), {})
    try:
        assert ingest(PhoenixRunTracing(traces)) == "A summary."
    finally:
        traces.shutdown()  # the failed export is logged, not raised
```

- [ ] **Step 2: Run** → ImportError on `PhoenixRunTracing`.

- [ ] **Step 3: Implement** in `tracing.py`:

```python
@contextmanager
def never_raising[T](cm: AbstractContextManager[T], fallback: T) -> Iterator[T]:
    """Runs the block inside `cm`, a trace, but a trace that can't start or end is logged and skipped: tracing never
    fails the work it traces (#229). The block's own errors still propagate."""
    try:
        value = cm.__enter__()
    except Exception:
        logger.warning("tracing could not start; running untraced", exc_info=True)
        yield fallback
        return
    try:
        yield value
    except BaseException as error:
        _end(cm, type(error), error)
        raise
    _end(cm, None, None)


def _end(cm: AbstractContextManager[object], exc_type: type[BaseException] | None, error: BaseException | None) -> None:
    try:
        cm.__exit__(exc_type, error, error.__traceback__ if error else None)
    except Exception:
        logger.warning("tracing could not end", exc_info=True)


class PhoenixRunTracing(RunTracing):
    """Each run is a root span (its own trace) in this process's project; the model calls inside nest beneath it."""

    def __init__(self, traces: PhoenixTraces) -> None:
        self._traces = traces

    @contextmanager
    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> Iterator[None]:
        attributes = span_attributes(
            None, {**self._traces.metadata, **metadata, "learner_hash": self._traces.hasher(user_id)}
        )
        # An empty context: a root span, whatever span is current.
        span = self._traces.tracer().start_as_current_span(name, context=Context(), attributes=attributes)
        with never_raising(span, None):
            yield
```

`start_as_current_span` records an exception escaping the block and sets the ERROR status (its defaults `record_exception=True`, `set_status_on_exception=True`). Exceptions are recorded as span events with their message; the work's own errors carry no token (ADR 0007). `Context` is `opentelemetry.context.Context`.

- [ ] **Step 4: Worker wiring** in `apps/worker/main.py`: docstring "…traced as `ingest` into `<phoenix_project>-ingestion` in Phoenix, with the content id and learner hash."; imports `PhoenixRunTracing, ingestion_project, start_tracing` and `NoRunTracing` from `smart_tutor.shared.ports.run_tracing`; in `main()`:

```python
    traces = start_tracing(settings, ingestion_project(settings))  # refuses tracing without a learner-hash key
    tracing = PhoenixRunTracing(traces) if traces else NoRunTracing()
```

and after the loop, `if traces: traces.shutdown()  # send what is left`. Check `tests/unit/apps/worker/test_worker.py` still passes.

- [ ] **Step 5: Run** `uv run pytest -q` → PASS; ruff, mypy clean. (`langsmith` imports left in `tracing.py` serve only `start_langsmith_tracing`.)

- [ ] **Step 6: Commit** `Trace the worker's ingest into Phoenix (#289)`.

---

### Task 3: The agent's `ask` span behind a port

**Files:**
- Create: `backend/src/smart_tutor/shared/ports/ask_tracing.py`
- Create: `backend/src/smart_tutor/shared/adapters/ask_tracing.py`
- Delete: `backend/src/smart_tutor/apps/agent/tracing.py`
- Modify: `backend/src/smart_tutor/apps/agent/server.py`
- Rewrite: `backend/tests/unit/apps/agent/test_ask_trace.py`, `backend/tests/unit/apps/agent/test_no_token_in_traces.py`
- Modify: `backend/tests/unit/apps/agent/test_server.py` (lines ~16, 215–264)

**Interfaces:**
- Consumes: `PhoenixTraces`, `root_ids`, `root_span_id`, `span_attributes`, `start_tracing`, `fakes.recorded_traces`.
- Produces:
  - `shared/ports/ask_tracing.py`: `@dataclass(frozen=True) class AskRun(run_id: uuid.UUID, thread_id: str | None, user_id: UserId, question: str, document_ids: list[str] | None)`; `class AskTrace(ABC)` with `finish(answer: str, decline: str | None, chunks: int) -> None` and `fail(code: str) -> None`; `class AskTracing(ABC)` with `trace(run: AskRun) -> AbstractContextManager[AskTrace]`; `class NoAskTrace(AskTrace)` and `class NoAskTracing(AskTracing)` (do nothing).
  - `shared/adapters/ask_tracing.py`: `class PhoenixAskTracing(AskTracing): __init__(self, traces: PhoenixTraces)`; `NO_DECLINE = "none"`.
  - `server.py`: `answer_events(graph, body, token, run: AskRun, tracing: AskTracing)`; `create_app(..., tracing: AskTracing | None = None)`.

- [ ] **Step 1: The port** (`shared/ports/ask_tracing.py`):

```python
"""Each ask is one trace named `ask` (PRD §10.4): where and with which models it ran, for which thread, whether the
search was limited to the conversation's documents, and, once done, the decline code and how many chunks the model was
given. The learner appears only as a keyed hash; the token stays in runtime context (ADR 0007)."""

import uuid
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass

from smart_tutor.shared.domain.ids import UserId


@dataclass(frozen=True)
class AskRun:
    run_id: uuid.UUID  # the trace's id; the API keeps it with the turn
    thread_id: str | None
    user_id: UserId  # hashed before it reaches the trace
    question: str
    document_ids: list[str] | None


class AskTrace(ABC):
    @abstractmethod
    def finish(self, answer: str, decline: str | None, chunks: int) -> None:
        """What the ask ended with: a decline gives the model no chunks."""

    @abstractmethod
    def fail(self, code: str) -> None:
        """The ask ended with an error event; the learner saw `code`."""


class AskTracing(ABC):
    @abstractmethod
    def trace(self, run: AskRun) -> AbstractContextManager[AskTrace]:
        """The graph's runs inside nest under the ask; leaving the block ends the trace, finished or not. Tracing never
        fails the ask (#229)."""


class NoAskTrace(AskTrace):
    def finish(self, answer: str, decline: str | None, chunks: int) -> None:
        pass

    def fail(self, code: str) -> None:
        pass


class NoAskTracing(AskTracing):
    def trace(self, run: AskRun) -> AbstractContextManager[AskTrace]:
        return nullcontext(NoAskTrace())
```

- [ ] **Step 2: Failing tests.** Rewrite `test_ask_trace.py`:

```python
"""PRD §10.4: each ask is one `ask` trace whose id is the turn's run id, with run metadata; the learner only as a
keyed hash."""

import json
import uuid
from typing import Any

from langchain_core.messages import AIMessage
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.trace import StatusCode

from fakes import TRACE_META, FakeRetriever, fake_chat_model, recorded_traces
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.server import AskRequest, answer_events
from smart_tutor.shared.adapters.ask_tracing import PhoenixAskTracing
from smart_tutor.shared.adapters.tracing import LearnerHasher, root_span_id
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.ports.ask_tracing import AskRun
from smart_tutor.tutoring.domain.errors import RetrievalError
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

RUN_ID = uuid.UUID("11111111-2222-4333-8444-555555555555")
THREAD_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
USER = UserId("user-under-test-123")
CHUNKS = [
    RetrievedChunk("c1", "d1", "a.pdf", 3, "Attention weighs tokens.", 0.9),
    RetrievedChunk("c2", "d2", "b.pdf", 1, "Other text.", 0.8),
]


async def traced(
    body: AskRequest,
    chunks: list[RetrievedChunk] = CHUNKS,
    close_after: int | None = None,
    error: Exception | None = None,
    sampling_rate: float = 1.0,
) -> tuple[list[ReadableSpan], list[str]]:
    graph = build_graph(
        lambda token: FakeRetriever(chunks, error=error), fake_chat_model(AIMessage("It weighs tokens [1]."))
    )
    run = AskRun(RUN_ID, body.thread_id and str(body.thread_id), USER, body.question, body.document_ids)
    got: list[str] = []
    with recorded_traces(sampling_rate=sampling_rate) as (traces, spans):
        events = answer_events(graph, body, "tok", run, PhoenixAskTracing(traces))
        async for event in events:
            got.append(event)
            if close_after is not None and len(got) >= close_after:
                await events.aclose()
                break
    return list(spans.get_finished_spans()), got


def ask_span(spans: list[ReadableSpan]) -> tuple[ReadableSpan, dict[str, Any]]:
    [span] = [s for s in spans if s.name == "ask"]
    return span, json.loads(span.attributes["metadata"])


async def test_an_answer_traces_as_one_root_ask_span_whose_trace_id_is_the_run_id() -> None:
    spans, _ = await traced(AskRequest(question="What is attention?", thread_id=uuid.UUID(THREAD_ID)))
    span, meta = ask_span(spans)
    assert span.parent is None
    assert span.context.trace_id == RUN_ID.int and span.context.span_id == root_span_id(RUN_ID)
    assert json.loads(span.attributes["input.value"])["question"] == "What is attention?"
    assert span.attributes["session.id"] == THREAD_ID
    assert meta["thread_id"] == THREAD_ID and meta["learner_hash"] == LearnerHasher("k")(USER)
    assert {k: meta[k] for k in TRACE_META} == TRACE_META
    assert meta["limited"] is False and meta["decline"] == "none" and meta["chunks"] == 2
    assert json.loads(span.attributes["output.value"])["answer"] == "It weighs tokens [1]."
    assert span.status.status_code is StatusCode.OK


async def test_langgraph_search_and_model_spans_nest_under_the_ask() -> None:
    spans, _ = await traced(AskRequest(question="What is attention?"))
    span, _ = ask_span(spans)
    others = [s for s in spans if s is not span]
    names = {s.name for s in others}
    assert {"LangGraph", "search", "answer"} <= names
    assert any(s.attributes.get("openinference.span.kind") == "LLM" for s in others)
    assert all(s.context.trace_id == RUN_ID.int and s.parent is not None for s in others)


async def test_a_decline_traces_with_its_code_and_no_chunks_given_to_the_model() -> None:
    low = [RetrievedChunk("c1", "d1", "a.pdf", 3, "Unrelated.", 0.01)]
    spans, _ = await traced(AskRequest(question="Q?", document_ids=["d1"]), chunks=low)
    _, meta = ask_span(spans)
    assert meta["limited"] is True and meta["decline"] == "limited" and meta["chunks"] == 0


async def test_a_no_documents_decline_traces_its_code() -> None:
    spans, _ = await traced(AskRequest(question="Q?"), chunks=[])
    assert ask_span(spans)[1]["decline"] == "no_documents"


async def test_without_a_thread_id_the_ask_still_traces() -> None:
    spans, _ = await traced(AskRequest(question="Q?"))
    span, meta = ask_span(spans)
    assert "thread_id" not in meta and "session.id" not in span.attributes


async def test_a_closed_stream_still_ends_the_ask_span() -> None:
    spans, got = await traced(AskRequest(question="What is attention?"), close_after=1)
    assert len(got) == 1
    span, _ = ask_span(spans)  # exported, so it ended
    assert span.context.trace_id == RUN_ID.int


async def test_a_failed_ask_ends_the_span_with_the_error_code() -> None:
    spans, got = await traced(AskRequest(question="Q?"), error=RetrievalError("down"))
    assert got[-1].startswith("event: error") and "unavailable" in got[-1]
    span, meta = ask_span(spans)
    assert span.status.status_code is StatusCode.ERROR and span.status.description == "unavailable"
    assert meta["decline"] == "none" and meta["chunks"] == 0


async def test_a_sampled_out_ask_exports_no_span_at_all() -> None:
    spans, got = await traced(AskRequest(question="What is attention?"), sampling_rate=0.0)
    assert got[-1].startswith("event: done") and spans == []  # children follow their root


async def test_a_failing_exporter_never_fails_the_ask() -> None:
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("It weighs tokens [1].")))
    run = AskRun(RUN_ID, None, USER, "What is attention?", None)
    with recorded_traces(exporter=_FailingExporter()) as (traces, _):
        tracing = PhoenixAskTracing(traces)
        got = [e async for e in answer_events(graph, AskRequest(question="What is attention?"), "tok", run, tracing)]
    assert any(e.startswith("event: delta") for e in got) and got[-1].startswith("event: done")


async def test_a_collector_that_is_down_never_fails_the_ask() -> None:
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("It weighs tokens [1].")))
    run = AskRun(RUN_ID, None, USER, "What is attention?", None)
    exporter = otlp_exporter(Settings(phoenix_url="http://127.0.0.1:9"), timeout=1)  # nothing listens
    traces = phoenix_traces("p", 1.0, BatchSpanProcessor(exporter), LearnerHasher("k"), {})
    try:
        tracing = PhoenixAskTracing(traces)
        got = [e async for e in answer_events(graph, AskRequest(question="What is attention?"), "tok", run, tracing)]
    finally:
        traces.shutdown()
    assert got[-1].startswith("event: done")
```

(`_FailingExporter` as in Task 2, defined in this file too; extra imports `Sequence`, `SpanExporter`, `SpanExportResult`, `BatchSpanProcessor`, `otlp_exporter`, `phoenix_traces`, `Settings`.) If the instrumentor names the LangGraph root span differently from `LangGraph`, assert on the names it actually emits (print `names` once) and keep `search` and `answer`.

Rewrite `test_no_token_in_traces.py` with the same tests and positive controls, over spans instead of LangSmith payloads:

```python
def dumped(spans: Sequence[ReadableSpan]) -> str:
    """Every attribute and event of every span, with its resource."""
    return json.dumps([json.loads(s.to_json()) for s in spans])


async def traced_run(state: dict[str, Any], retriever: FakeRetriever | None = None) -> tuple[str, str]:
    """Run the graph, instrumented, with the token in context; return (dumped spans, dumped output state)."""
    retriever = retriever or FakeRetriever(CHUNKS)
    graph = build_graph(lambda token: retriever, fake_chat_model(AIMessage("It weighs tokens [1].")))
    with recorded_traces() as (_, spans):
        out = await graph.ainvoke(state, context=AgentContext(access_token=TOKEN))
    assert spans.get_finished_spans(), "nothing was traced, so the check below would pass vacuously"
    return dumped(spans.get_finished_spans()), json.dumps(out, default=str)


async def ask_spans(question: str) -> str:
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("It weighs tokens [1].")))
    body = AskRequest(question=question)
    run = AskRun(uuid.uuid4(), None, UserId(USER_ID), body.question, None)
    with recorded_traces() as (traces, spans):
        async for _ in answer_events(graph, body, TOKEN, run, PhoenixAskTracing(traces)):
            pass
    assert spans.get_finished_spans()
    return dumped(spans.get_finished_spans())
```

Keep all six existing test functions (`test_the_token_never_reaches_traces_or_state`, `test_positive_control_a_token_in_the_question_is_caught`, `test_history_reaches_traces_without_the_token`, `test_the_context_repr_hides_the_token`, `test_the_ask_trace_holds_no_token_user_id_or_email`, `test_positive_control_a_user_id_in_the_question_is_caught`) with their assertions unchanged; update the module docstring ("…so Phoenix never receives it. The real OpenInference instrumentation exports to an in-memory exporter…").

In `test_server.py`: import `AskRun, AskTrace, AskTracing, NoAskTrace` from `smart_tutor.shared.ports.ask_tracing`; `_RecordingTracing(AskTracing)` keeps `self.runs` and yields `NoAskTrace()` (no `super().__init__`, no `type: ignore`); replace `test_startup_refuses_tracing_without_a_learner_hash_key` with:

```python
def test_startup_refuses_tracing_without_a_learner_hash_key() -> None:
    settings = Settings(keycloak_client_secret="s", learner_hash_key="", phoenix_url="http://127.0.0.1:9")
    with pytest.raises(RuntimeError, match="SMART_TUTOR_LEARNER_HASH_KEY"), TestClient(create_app(settings)):
        pass


def test_without_a_phoenix_url_the_agent_starts_untraced(monkeypatch: pytest.MonkeyPatch) -> None:
    ...  # see Step 4: lifespan with phoenix_url="" leaves app.state.tracing a NoAskTracing
```

For the second test, only assert what is reachable without Keycloak: build `create_app(Settings(keycloak_client_secret="s"), graph=graph)` with a `graph`, and patch `smart_tutor.apps.agent.server.keycloak_verifier` to return a `FakeTokenVerifier()`; then `with TestClient(app): assert isinstance(app.state.tracing, NoAskTracing)`.

- [ ] **Step 3: Run** → ImportError (`smart_tutor.shared.adapters.ask_tracing`).

- [ ] **Step 4: Implement** `shared/adapters/ask_tracing.py`:

```python
"""The ask's root span in Phoenix (PRD §10.4): its trace id is the turn's run id and its span id the run id's low 64
bits, so the API can address it from the stored run id. LangGraph and model spans nest beneath it."""

import json
import logging
from collections.abc import Iterator
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
    def _safely(step: Any) -> None:
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
            try:
                context.detach(token)
            except Exception:
                logger.warning("could not leave the ask trace's context", exc_info=True)
```

Use the `SpanAttributes` / `OpenInferenceMimeTypeValues` constants rather than literal `"output.value"`, `"session.id"` strings if you prefer; keep one style per file.

- [ ] **Step 5: Server wiring.** In `server.py`: import `AskRun, AskTracing, NoAskTracing` from `smart_tutor.shared.ports.ask_tracing`, `PhoenixAskTracing` from `smart_tutor.shared.adapters.ask_tracing`, `start_tracing` from `smart_tutor.shared.adapters.tracing`. Delete `default_hasher`/`LearnerHasher`/`run_metadata` use. In `lifespan`:

```python
        traces = start_tracing(settings, settings.phoenix_project)  # tracing on without a learner-hash key: refuse
        if tracing is None:
            app.state.tracing = PhoenixAskTracing(traces) if traces else NoAskTracing()
        ...
        async with httpx.AsyncClient(timeout=5) as http:
            app.state.verifier = keycloak_verifier(settings, http)
            try:
                yield
            finally:
                if traces:
                    traces.shutdown()  # send what is left
```

and `app.state.tracing = tracing or NoAskTracing()` outside it. Update the module docstring line "each ask is traced as one `ask` run" → "each ask is one `ask` trace in Phoenix whose trace id is `run_id` (PRD §10.4)". Delete `apps/agent/tracing.py`, and `start_langsmith_tracing` with every `langsmith` import from `shared/adapters/tracing.py`. `grep -rn "apps.agent.tracing\|start_langsmith_tracing" backend` → nothing left (evals included); `grep -n langsmith backend/src/smart_tutor/shared/adapters/tracing.py` → only the secret name in a comment, if any.

- [ ] **Step 6: Run** `uv run pytest -q` → PASS (including `tests/isolation`, `tests/test_tests_never_trace.py`); ruff, mypy, `PYTHONUTF8=1 uv run lint-imports` clean.

- [ ] **Step 7: Commit** `Trace each ask into Phoenix as a root span whose id is the run id (#289)`.

---

### Task 4: LangSmith leaves the runtime

**Files:**
- Delete: `backend/src/smart_tutor/tutoring/adapters/langsmith_feedback.py`, `backend/tests/unit/tutoring/test_langsmith_feedback.py`
- Modify: `backend/src/smart_tutor/apps/api/services.py` (line 34 import, line 73 `feedback=NoAnswerFeedback()` from `smart_tutor.tutoring.application` if exported there, else check how the API imports tutoring types and follow it; `NoAnswerFeedback` lives in `tutoring/ports/answer_feedback.py`, so if `apps` may not import `tutoring.ports`, export it from `tutoring/application/__init__.py`)
- Modify: `backend/tests/fakes/tracing.py`, `backend/tests/fakes/__init__.py` (drop `FeedbackClient`, `InlineExecutor`)
- Modify docstrings: `apps/api/routes/threads.py` lines 9–11, 641, 709; `shared/domain/ids.py:11`; `apps/jobs/__init__.py:1`; `apps/jobs/retention.py:3`; `tutoring/ports/answer_feedback.py:1,17`; `tutoring/README.md` (the ratings sentences); `backend/AGENTS.md` (Tests: "No test traces")
- Modify: `backend/pyproject.toml` (move `"langsmith>=0.4"` from `dependencies` to the `eval` extra; add the import-linter contract), `backend/uv.lock`
- Modify: `backend/tests/test_tests_never_trace.py`
- Regenerate: `web/src/api/` (`make api-client`, or its one-line command from the Makefile)

**Interfaces:** Consumes `NoAnswerFeedback` (existing). Produces nothing new.

- [ ] **Step 1: Failing guard test.** Add to `tests/test_tests_never_trace.py` (keep the LangSmith tests: evals still use LangSmith):

```python
def test_a_phoenix_url_in_the_environment_does_not_reach_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("SMART_TUTOR_PHOENIX_URL=http://localhost:10404\n")
    monkeypatch.chdir(tmp_path)  # Settings reads ./.env
    assert Settings().phoenix_url == ""
    assert start_tracing(Settings(learner_hash_key="k"), "smart-tutor-local") is None


def test_positive_control_without_the_guard_a_dotenv_url_turns_tracing_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("SMART_TUTOR_PHOENIX_URL=http://localhost:10404\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SMART_TUTOR_PHOENIX_URL")
    assert Settings().phoenix_url == "http://localhost:10404"
```

Run: both pass already (the guard is Task 1's). This proves Task 1's guard against a `.env`. Then add the import rule and expect it to fail first.

- [ ] **Step 2: Import-linter contract** (pyproject, after Rule 4's contracts):

```toml
# ADR 0017: runtime traces go to Phoenix; only backend/evals (outside smart_tutor) uses LangSmith.
[[tool.importlinter.contracts]]
name = "Runtime code never imports LangSmith"
type = "forbidden"
source_modules = ["smart_tutor"]
forbidden_modules = ["langsmith"]
allow_indirect_imports = true  # langchain_core imports it itself
```

Run `PYTHONUTF8=1 uv run lint-imports` → FAILS on `smart_tutor.tutoring.adapters.langsmith_feedback -> langsmith`. If import-linter refuses the root package as a source, list every top-level subpackage of `smart_tutor` instead.

- [ ] **Step 3: Remove the feedback adapter**, wire `NoAnswerFeedback()` in `apps/api/services.py`, delete its test and the two fakes. Move `langsmith` to the `eval` extra: `uv remove langsmith && uv add --optional eval "langsmith>=0.4"`. Confirm `uv run python -c "import langsmith"` still works in the dev environment (it is a dependency of `langchain-core`).

- [ ] **Step 4: Docstrings.** Exact replacements:
  - `ids.py:11`: `RunId = NewType("RunId", str)  # an ask's trace id in Phoenix (UUID); minted by the API, kept with its turn`
  - `threads.py:641` field description: `"The ask's trace id in Phoenix, for attaching a rating (#227); null for turns kept before it was recorded."`
  - `threads.py:9–11` and `:709`: the rating "is saved with the turn"; drop "sent to LangSmith…". Add "(#290 sends it to Phoenix)".
  - `answer_feedback.py:1`: `"""Learner ratings sent on to where answers are traced (PRD §10.2): Phoenix, from #290."""`; `:17`: `"""Ratings are only saved with the turn."""`
  - `jobs/__init__.py:1`: `…retention (decline log; traces expire in Phoenix), (R3) reports.`; `retention.py:3`: `Traces are not deleted here: they expire through Phoenix's retention policy, at most 180 days (D25; …` (keep the rest of the sentence, replacing any further "LangSmith project" with "Phoenix instance").
  - `tutoring/README.md`: replace the `LangSmithAnswerFeedback …` sentence with "`NoAnswerFeedback` is wired until #290 sends ratings to Phoenix as span annotations."
  - `backend/AGENTS.md` Tests bullet: "No test traces, whatever environment is loaded (ADR 0017): `tests/conftest.py` blanks `SMART_TUTOR_PHOENIX_URL` for the session and fails a test that leaves LangChain instrumented; it also turns LangSmith tracing off (evals use LangSmith) and makes its default client a `RecordingClient`. A test that checks spans traces inside `fakes.recorded_traces()` (in-memory exporter)."

- [ ] **Step 5: Regenerate the API client** (from `backend/`): `uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Then `cd web && npm ci && npm run build`.

- [ ] **Step 6: Run** all backend checks (ruff, format, mypy, lint-imports, pytest) and `grep -rn "langsmith\|LangSmith" backend/src` → only the `learner_hash_key` comment's secret name `langsmith/learner-hash-key` may remain.

- [ ] **Step 7: Commit** `Take LangSmith out of the agent, worker, and API runtime (#289)`; body: why the feedback adapter goes now (no LangSmith run exists for new turns; ratings stay saved; #290 sends them to Phoenix).

---

### Task 5: Local development traces into the local Phoenix

**Files:** `.env.example`, `compose.yaml`, `compose.ci.yaml`, `README.md`, `AGENTS.md`, `infra/tests/test_workflows.py` (only if its compose.ci assertion is an exact set), possibly a new test in `infra/tests/` for root Compose (look for an existing test file that parses root `compose.yaml`: `grep -ln "compose.yaml" infra/tests`).

- [ ] **Step 1: Test first.** In the infra test file that already reads the root `compose.yaml` (or a new `infra/tests/test_local_compose.py` that loads it with `yaml.safe_load`), add:

```python
@pytest.mark.parametrize("service", ["agent", "worker"])
def test_app_services_trace_into_the_compose_phoenix_and_not_langsmith(service: str) -> None:
    env = local_compose()["services"][service]["environment"]
    assert env["SMART_TUTOR_PHOENIX_URL"] == "http://phoenix:6006"
    assert env["LANGSMITH_TRACING"] == "false"  # an old .env must not trace into LangSmith


def test_ci_app_services_run_untraced() -> None:  # CI starts no Phoenix
    for service in ("api", "agent", "mcp", "worker"):
        assert ci_compose()["services"][service]["environment"]["SMART_TUTOR_PHOENIX_URL"] == ""
```

Adapt the accessors to the file's existing helpers and to whether `environment` is a mapping or a list in each file. Run `cd infra && uv run pytest -q` → FAIL.

- [ ] **Step 2: `.env.example`** — replace lines 8–16 with:

```
# Runtime traces (ADR 0017): host runs send to the local Phoenix (docker compose up -d), http://localhost:10404, no
# key. Services in Compose send to http://phoenix:6006 (compose.yaml). Never the production Phoenix.
SMART_TUTOR_PHOENIX_URL=http://localhost:10404
SMART_TUTOR_PHOENIX_PROJECT=smart-tutor-local
# Share of traces kept, 0-1 (default 1, every ask); deployments take it from the SSM parameter trace-sampling-rate.
# SMART_TUTOR_TRACE_SAMPLING_RATE=1
# Learner hash in traces (PRD §10.4): HMAC key; any value locally, the secret <prefix>/langsmith/learner-hash-key
# when deployed.
SMART_TUTOR_LEARNER_HASH_KEY=local-learner-hash-key

# LangSmith: evals only (backend/evals), into their own project. The app no longer traces to LangSmith; remove
# LANGSMITH_TRACING from an older .env.
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=smart-tutor-local
```

Keep a `LANGSMITH_PROJECT=` line: `evals-smoke.yml` seds it to `smart-tutor-ci`.

- [ ] **Step 3: `compose.yaml`** — header lines 4–5: "LangSmith is real too (evals only)."; the phoenix comment (74–77): drop "Once #289 lands"; services in Compose send to `http://phoenix:6006/v1/traces`, processes on your machine to `http://localhost:10404/v1/traces`. In `agent` and `worker` `environment:` add:

```yaml
      SMART_TUTOR_PHOENIX_URL: http://phoenix:6006  # .env has the host's localhost:10404
      LANGSMITH_TRACING: "false"  # LangSmith is for evals only; an older .env may still turn it on
```

`compose.ci.yaml`: add `SMART_TUTOR_PHOENIX_URL=` (empty) for api, agent, mcp, worker so CI's app services run untraced (CI starts no Phoenix), in the file's style; update its header comment. If `test_workflows.py:837` asserts the passed set exactly, extend its expected set and say why in a comment.

- [ ] **Step 4: README and AGENTS.md.** README l.22: `cp .env.example .env          # fill in AWS_PROFILE (and LANGSMITH_API_KEY for evals)`; after l.31 or in "Run the app" Option B, add: "Local runs trace into the local Phoenix: open http://localhost:10404, project `smart-tutor-local` (asks) and `smart-tutor-local-ingestion` (uploads). An `.env` from before #289 may still have `LANGSMITH_TRACING=true`; remove it." AGENTS.md l.48: "Bedrock has no emulator and LangSmith is real (evals only): local runs call real us-east-1 models with your AWS credentials, and their traces go to the local Phoenix (`smart-tutor-local`, `smart-tutor-local-ingestion`)." Drop "until #289" and "once #289 lands" everywhere in both.

- [ ] **Step 5: Run** `cd infra && uv run pytest -q` → PASS; `docker compose config -q` and `docker compose -f compose.yaml -f compose.ci.yaml config -q` → no error.

- [ ] **Step 6: Commit** `Trace local runs into the local Phoenix (#289)`.

---

### Task 6: On-premise: the agent and worker send to Phoenix; LangSmith leaves the egress allowlist

**Files:** `deploy/on-premise/deploy.sh`, `deploy/on-premise/compose.yaml`, `deploy/on-premise/check-egress.py`, `deploy/on-premise/check-worker.sh`, `infra/tests/test_host.py`, `infra/tests/test_check_egress.py`, `docs/runbooks/on-premise-deploy.md`, `docs/runbooks/on-premise-monitoring.md`.

Context: `deploy.sh` renders a root-only env file (`/etc/smart-tutor/smart-tutor.env`) through a heredoc (l.73–102) with `secret()` (Secrets Manager) and `param()` (SSM); `compose.yaml` interpolates `${VAR}`. Phoenix is on the `default` and `worker` networks; the worker has `HTTP_PROXY`/`HTTPS_PROXY=http://egress-proxy:3128` and no `NO_PROXY`. Squid's config is inline in `egress-proxy`'s `SQUID_CONF` (l.268–304). The API's Phoenix settings are #290's.

- [ ] **Step 1: Tests first** in `infra/tests/test_host.py`:
  - Replace `test_agent_and_worker_trace_into_the_on_premise_project` with:

```python
@pytest.mark.parametrize("service", ["agent", "worker"])
def test_agent_and_worker_trace_into_the_on_premise_phoenix(service: str) -> None:
    env = compose()["services"][service]["environment"]
    assert env["SMART_TUTOR_PHOENIX_URL"] == "http://phoenix:6006"
    assert env["SMART_TUTOR_PHOENIX_API_KEY"] == "${PHOENIX_API_KEY}"  # empty: untraced
    assert env["SMART_TUTOR_PHOENIX_PROJECT"] == "smart-tutor-on-premise"
    assert env["SMART_TUTOR_TRACE_SAMPLING_RATE"] == "${TRACE_SAMPLING_RATE:?}"
    assert env["SMART_TUTOR_LEARNER_HASH_KEY"] == "${LEARNER_HASH_KEY:?}"
    assert not [k for k in env if k.startswith("LANGSMITH_")]


def test_the_worker_reaches_phoenix_without_the_egress_proxy() -> None:
    env = compose()["services"]["worker"]["environment"]
    assert "phoenix" in env["NO_PROXY"].split(",") and env["no_proxy"] == env["NO_PROXY"]
```

  - `test_services_that_make_no_model_calls_of_their_own_do_not_trace` (api, mcp): also assert no `SMART_TUTOR_PHOENIX_` keys (the API gets them in #290).
  - `test_egress_proxy_allows_only_the_workers_aws_endpoints_and_imds`: the rules lose `"http_access allow CONNECT langsmith tls"`.
  - Replace `test_egress_proxy_allows_langsmith_by_exact_name_on_443_only` with `test_egress_proxy_no_longer_allows_langsmith`: no `langsmith` acl and `"api.smith.langchain.com"` not in `SQUID_CONF`.
  - Replace `test_deploy_script_renders_the_tracing_settings_and_turns_tracing_off_without_the_api_key` with one asserting: `"learner_hash_key=$(secret langsmith/learner-hash-key)"`, `"trace_sampling_rate=$(param trace-sampling-rate)"`, the slice between `phoenix_api_key=` and `umask 077` contains `"secret phoenix/api-key 2>/dev/null"`, `"$prefix/phoenix/api-key"` and `>&2`; the env lines `PHOENIX_API_KEY=$phoenix_api_key`, `TRACE_SAMPLING_RATE=$trace_sampling_rate`, `LEARNER_HASH_KEY=$learner_hash_key`; and `"LANGSMITH" not in script`.

  In `test_check_egress.py`:
  - `test_leaks_reports_a_tunnel_to_an_allowed_host_on_another_port`: drop the LangSmith entry.
  - Replace `test_leaks_reports_a_proxy_that_lets_another_langchain_host_or_port_through` with `test_leaks_reports_a_proxy_that_lets_langsmith_through` (a CONNECT to `api.smith.langchain.com:443` answered 200 is a leak).
  - Replace `test_unreachable_reports_langsmith` and `test_unreachable_ignores_langsmith_while_tracing_is_off` with `test_unreachable_reports_phoenix` (Phoenix's `/healthz` refused, with `SMART_TUTOR_PHOENIX_URL` set → `["Phoenix: …"]`) and `test_unreachable_ignores_phoenix_while_untraced` (parametrized `SMART_TUTOR_PHOENIX_API_KEY` in `[None, ""]`).

  Run `cd infra && uv run pytest tests/test_host.py tests/test_check_egress.py -q` → FAIL.

- [ ] **Step 2: `deploy.sh`.** l.6 comment: "…including the Phoenix tracing settings…". Replace l.61–70 with:

```bash
# Traces go to the on-premise Phoenix, projects smart-tutor-on-premise and -ingestion (ADR 0017). The operator creates
# the system key's secret in Phoenix (docs/runbooks/on-premise-deploy.md); until then the services run untraced rather
# than failing the deploy.
phoenix_api_key=
if ! phoenix_api_key=$(secret phoenix/api-key 2>/dev/null) || [[ -z $phoenix_api_key ]]; then
  phoenix_api_key=
  echo "Warning: no Phoenix API key (is the secret $prefix/phoenix/api-key set?); deploying without tracing" >&2
fi
```

In the heredoc, replace `LANGSMITH_TRACING=…` and `LANGSMITH_API_KEY=…` with `PHOENIX_API_KEY=$phoenix_api_key`; keep `TRACE_SAMPLING_RATE` and `LEARNER_HASH_KEY`.

- [ ] **Step 3: `compose.yaml`.** Header l.7: the worker reaches "Phoenix directly and, through the egress proxy, its AWS endpoints (#153)". Phoenix comment l.44–46: "The agent and worker send OTLP/HTTP to http://phoenix:6006/v1/traces with the system key <prefix>/phoenix/api-key…". In `agent` (l.203–208) and `worker` (l.335–340), replace the LangSmith block with:

```yaml
      # Traces (PRD §10.4, ADR 0017): untraced until the Phoenix key's secret exists (deploy.sh).
      SMART_TUTOR_PHOENIX_URL: http://phoenix:6006
      SMART_TUTOR_PHOENIX_API_KEY: ${PHOENIX_API_KEY}
      SMART_TUTOR_PHOENIX_PROJECT: smart-tutor-on-premise  # the worker's ingest traces go to smart-tutor-on-premise-ingestion
      SMART_TUTOR_TRACE_SAMPLING_RATE: ${TRACE_SAMPLING_RATE:?}
      SMART_TUTOR_LEARNER_HASH_KEY: ${LEARNER_HASH_KEY:?}
```

(the `-ingestion` comment only on the worker). Worker, next to `HTTP_PROXY`: `NO_PROXY: phoenix` and `no_proxy: phoenix` (requests reads either; Phoenix is on the worker's internal network). Squid: drop the `# The worker's ingest traces (#229).` comment, `acl langsmith …`, and `http_access allow CONNECT langsmith tls`; l.268 comment → "CONNECT to its AWS endpoints, plain HTTP to the instance metadata service".

- [ ] **Step 4: `check-egress.py`.** Docstring: "…while S3, SQS, SSM, Bedrock, Phoenix (while tracing), and Postgres work." Delete `LANGSMITH_HOST`'s allowed-host role: in `leaks()`, replace the two LangSmith tunnels with `tunnels.append(("api.smith.langchain.com", 443))  # LangSmith left the allowlist (ADR 0017)`. Replace `_tracing()` with:

```python
def _tracing() -> bool:
    """The worker traces when it has a Phoenix URL and its key (deploy.sh leaves the key empty without the secret)."""
    return bool(os.environ.get("SMART_TUTOR_PHOENIX_URL")) and bool(os.environ.get("SMART_TUTOR_PHOENIX_API_KEY"))
```

and in `unreachable()` probe Phoenix directly, never through the proxy:

```python
    # Phoenix (the ingest traces), on the worker's internal network: any HTTP answer proves the route.
    if _tracing():
        url = os.environ["SMART_TUTOR_PHOENIX_URL"].rstrip("/") + "/healthz"
        direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            direct.open(url, timeout=TIMEOUT)
        except urllib.error.HTTPError:
            pass
        except OSError as error:
            problems.append(f"Phoenix: {error}")
```

`main()`'s message: `"Phoenix (tracing on), " if _tracing() else ""`. `check-worker.sh` l.31–34 comment: "The worker reaches Postgres and Phoenix directly and only its AWS endpoints through egress-proxy… an unreachable AWS endpoint, Phoenix while tracing, or the database only fails the check."

- [ ] **Step 5: Runbooks.** `on-premise-deploy.md`: l.15, l.25 ("A Phoenix system key for tracing (section 10)…"), l.155, l.254, l.260, l.483 → no LangSmith in egress, Phoenix reached directly. Rewrite §10 "Tracing (LangSmith) (#229)" as "Tracing (Phoenix) (#229, #289)": projects `smart-tutor-on-premise` and `smart-tutor-on-premise-ingestion`; the key `smart-tutor-on-premise/phoenix/api-key` (made in §11) and the warning text from deploy.sh; the learner-hash key; retention 180 days by `PHOENIX_DEFAULT_RETENTION_POLICY_DAYS`; sampling `SSM /smart-tutor-on-premise/trace-sampling-rate` (outside 0–1 stops the agent and worker from starting); egress (the worker reaches `phoenix:6006` on its internal network, `NO_PROXY`); the smoke run `PHOENIX_API_KEY=<key> SMOKE_TEST_USERNAME=… SMOKE_TEST_PASSWORD=… python3 deploy/pilot/smoke_test.py https://<domain> --end-to-end --trace-project smart-tutor-on-premise`, ending with `ask trace <run id> is in smart-tutor-on-premise`. Drop the LangSmith key from the kept/deleted secrets lists (l.349, l.361) only where it describes on-premise tracing. §11 l.435 and l.447: the agent and worker now send with the key. `on-premise-monitoring.md` l.111: "Check Bedrock usage in Phoenix traces (LLM spans' token counts)".

- [ ] **Step 6: Run** `cd infra && uv run pytest -q` → PASS; `bash -n deploy/on-premise/deploy.sh deploy/on-premise/check-worker.sh`; `docker compose -f deploy/on-premise/compose.yaml config -q` with dummy env (follow how test_host.py or the runbook validates it; skip if it needs secrets) .

- [ ] **Step 7: Commit** `Send the on-premise agent and worker traces to Phoenix and close LangSmith egress (#289)`.

---

### Task 7: The pilot smoke test finds the ask trace in Phoenix

**Files:** `deploy/pilot/smoke_test.py`, `infra/tests/test_smoke_test.py`.

Phoenix's REST API (verified against 20.16.0): `GET {phoenix}/v1/projects/{project}/spans?trace_id=<32 hex>&limit=100` with `authorization: Bearer <key>` returns `{"data": [span…], "next_cursor": …}`; a span is `{"name", "context": {"trace_id", "span_id"}, "span_kind", "parent_id" (null for a root), "status_code", "status_message", "attributes": {...}, "events": [...]}`; the `metadata` JSON attribute comes back flattened as `"metadata.<key>"` entries (booleans and numbers keep their JSON types). An unknown project answers 404. Phoenix is reachable from outside at `https://<domain>/phoenix` (Caddy). `send-test-span.py` in `deploy/on-premise/` shows the same pattern.

- [ ] **Step 1: Tests first.** In `test_smoke_test.py`, replace the LangSmith fake (`LANGSMITH_KEY`, `_ask_run`, `_langsmith`, `/ls/` routing, `langsmith_keys`) with a Phoenix fake at `/phoenix/v1/projects/{project}/spans`, checking `authorization: Bearer {PHOENIX_KEY}` (`PHOENIX_KEY = "phoenix-test-not-a-key"`), answering 404 for an unknown project and an empty `data` until `trace_after_polls`. The ask span fixture:

```python
def _ask_span(run_id: str, thread_id: str) -> dict[str, Any]:
    return {
        "name": "ask",
        "context": {"trace_id": uuid.UUID(run_id).hex, "span_id": f"{uuid.UUID(run_id).int & 0xFFFFFFFFFFFFFFFF:016x}"},
        "span_kind": "CHAIN",
        "parent_id": None,
        "status_code": "OK",
        "attributes": {
            "metadata.deployment": "on-premise", "metadata.chat_model": "m", "metadata.embedding_model": "e",
            "metadata.thread_id": thread_id, "metadata.learner_hash": "ab" * 32, "metadata.limited": False,
            "metadata.decline": "none", "metadata.chunks": 2,
        },
        "events": [],
    }
```

`run_with_trace` sets `PHOENIX_API_KEY` and `PHOENIX_URL=f"{pilot.base}/phoenix"`. Keep each existing test's intent, renamed: finds the trace (exit 0, key never printed, `ask trace <id> is in smart-tutor-on-premise`, ≥ 2 polls); with the token fails; with the username fails; **new:** with the learner's user id (the token's `sub`) fails; missing metadata names the keys; a span in another project fails → becomes "the root span's id is not the run id's low 64 bits" fails; never arrives → names the run and `trace-sampling-rate`; exists but has no root `ask` yet (only children) → "reached Phoenix but its ask span never arrived"; polls answering errors name the last status; `--trace-project` needs `PHOENIX_API_KEY` and `--end-to-end`. Make the fake token a JWT-shaped string whose payload has `"sub": "user-id-under-test"` if the fake pilot's token isn't one already. Run → FAIL.

- [ ] **Step 2: Implement.** Docstring l.7 and l.21–23: `PHOENIX_API_KEY=... SMOKE_TEST_USERNAME=... SMOKE_TEST_PASSWORD=... python3 deploy/pilot/smoke_test.py <url> --end-to-end --trace-project smart-tutor-on-premise`; "--trace-project then reads the ask's run id from the conversation's turns and waits for its trace in that Phoenix project (#289): a root span named `ask` whose trace id is the run id and whose span id is its low 64 bits, with the run metadata of PRD §10.4, and holding neither the access token, the username, nor the learner's user id. PHOENIX_URL defaults to `<url>/phoenix`. The key is never printed." Replace `QUERY_SELECT`, `DEFAULT_LANGSMITH_ENDPOINT`, `_langsmith` with `_phoenix(s, path, api_key)` (GET with `authorization: Bearer`). New `check_trace(s, run, project, phoenix_url, api_key, username)`:
  1. Read `run_id` from the last turn (unchanged).
  2. Poll `GET {phoenix}/v1/projects/{quote(project)}/spans?trace_id={uuid.UUID(run_id).hex}&limit=100`: 401/403 → "Phoenix refused the API key"; 404 → not yet (the project appears with its first span); 200 → `data`; stop when a span named `ask` with `parent_id` null is present; otherwise remember `seen` when `data` is non-empty and `last_other` for other statuses; `s.wait("the ask's trace")`. Deadline messages: "run {run_id} reached Phoenix but its ask span never arrived{last}" / "run {run_id} never reached Phoenix (is tracing on, with the key {prefix}/phoenix/api-key, and the sampling rate trace-sampling-rate 1?){last}".
  3. Root checks: `context.span_id == f"{uuid.UUID(run_id).int & 0xFFFF_FFFF_FFFF_FFFF:016x}"`; missing `metadata.<k>` for `k in TRACE_METADATA` → "the ask span lacks metadata …"; `metadata.thread_id == run.thread_id`.
  4. Leak scan over `json.dumps(data)`: the token; the username; the user id, read from the token's `sub` claim (base64url-decode the JWT's middle part; skip quietly if it isn't a JWT) → "the trace holds the learner's user id".
  `main()`: `--trace-project` help "…in this Phoenix project (needs PHOENIX_API_KEY)"; read `PHOENIX_API_KEY` (message names it) and `PHOENIX_URL` (default `args.url.rstrip("/") + "/phoenix"`).

- [ ] **Step 3: Run** `cd infra && uv run pytest tests/test_smoke_test.py -q` → PASS; full `cd infra && uv run pytest -q` → PASS.

- [ ] **Step 4: Commit** `Check the ask trace in Phoenix from the pilot smoke test (#289)`.

---

### Task 8: PRD v2.56 and the domain glossary

**Files:** `sdd/prd.md`, `CONTEXT.md`.

- [ ] **Step 1: PRD.** Status line l.5: `Draft v2.55` → `Draft v2.56`. New row right after it:

`| **Changes from v2.55** | Runtime traces in Phoenix (#289, §10.4, D25, Q34, ADR 0017): the agent's `ask` and the worker's `ingest` trace through OpenTelemetry into the environment's own Phoenix: production into `smart-tutor-on-premise` and `smart-tutor-on-premise-ingestion` on the on-premise host, local runs into `smart-tutor-local` and `smart-tutor-local-ingestion` in the local Compose Phoenix. An ask's trace id is the turn's run id. Production sends with the system key `<prefix>/phoenix/api-key` (untraced without it); traces expire through Phoenix's retention (180 days in production). The worker's egress allowlist no longer includes LangSmith. Native-cloud's Helm charts keep their LangSmith settings, unused, until native-cloud is picked up again. Ratings are saved with the turn but not sent anywhere until #290 sends them to Phoenix. LangSmith remains for evals. |`

Edits (keep each sentence's other content):
- v2.43 row (l.17): append "Superseded in v2.56: traces go to Phoenix and expire through its retention (ADR 0017)."
- D25 (l.174) rationale: "Phoenix's retention policy (`PHOENIX_DEFAULT_RETENTION_POLICY_DAYS`, 180 days in production) deletes traces; no job of ours does."
- §9.1 job table (l.367): "Traces expire through Phoenix's retention (D25)."
- l.305: "expire with Phoenix's trace retention (at most 180 days, D25)."
- §9.10 (l.524): egress only to AWS endpoints and PostgreSQL and Phoenix on the host's internal network; the proxy allows the documents bucket, SQS, SSM, Bedrock runtime, and the instance metadata service by exact name.
- §9.12 local (l.547): "Bedrock and LangSmith (evals only) are real; local traces go to the local Phoenix."
- Stack table (l.574): `| Tracing and evaluation | Arize Phoenix, self-hosted (runtime traces); LangSmith (evals, datasets) |`
- §10.4 (l.668): after "Deployed services trace into their mode's project", insert "in the environment's own self-hosted Phoenix (ADR 0017)"; after "never the user id, email, or token" add "An ask's trace id is its run id."
- §11 NFR (l.679): "(the production Phoenix's retention policy)".
- Q34 (l.717): "…through Phoenix's retention policy…".
- Appendix A item 6 (l.814): "Phoenix API key. *(On-premise)* a Phoenix system key in `<prefix>/phoenix/api-key`. *(Native-cloud)* LangSmith service key, until native-cloud is picked up again (ADR 0017)."
- Leave §10.2 and §10.3 item 7 (ratings) to #290.

- [ ] **Step 2: CONTEXT.md** l.53: a rating is "saved with the turn; #290 sends it to Phoenix as a `learner_rating` span annotation" instead of "sent to LangSmith as `learner_rating` feedback".

- [ ] **Step 3: Check** `grep -n "LangSmith" sdd/prd.md`: every remaining hit is about evals, history rows, or native-cloud.

- [ ] **Step 4: Commit** `Say in the PRD that runtime traces go to Phoenix (v2.56, #289)`.

---

## Final verification (controller, after all tasks)

1. All checks: backend (ruff, format, mypy, lint-imports, pytest), `cd web && npm run build`, `cd infra && uv run pytest`.
2. Live local check: local Phoenix up (`docker compose up -d phoenix`); run `make mcp`, `make agent`, `make api`, `make worker` equivalents with `uv run --env-file ../.env` and `SMART_TUTOR_PHOENIX_URL=http://localhost:10404`; sign in as `learner@example.com`, upload a PDF, ask a question. Then `GET http://localhost:10404/v1/projects/smart-tutor-local/spans?trace_id=<run_id hex>`: one root `ask` with LangGraph, `search`, and LLM children; and an `ingest` root in `smart-tutor-local-ingestion`.
3. The production criterion ("a pilot smoke run finds its trace in `smart-tutor-on-premise`") needs a deploy plus the operator's Phoenix key: list it in the PR as a post-merge check.

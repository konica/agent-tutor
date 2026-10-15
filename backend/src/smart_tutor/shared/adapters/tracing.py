"""Runtime traces into Langfuse (PRD §10.4, ADR 0023) through OpenTelemetry: one batched OTLP/HTTP exporter, a
parent-based trace-id ratio sampler, and OpenInference's LangChain instrumentation for the LangGraph and model spans
under our own root spans. Who a run is for appears only as a keyed hash of the learner's user id, which every span of
the run names as its `user.id` (with the thread as its `session.id`), so Langfuse can filter any observation by learner
and conversation. Tokens, user ids, and emails never reach a span (ADR 0007). Exporting runs on the SDK's own thread: a
failed export is logged by the SDK and dropped, and never fails the work it traces (#229); a host that is off (nights)
only logs and drops."""

import base64
import hashlib
import hmac
import json
import logging
import os
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from openinference.instrumentation import using_attributes
from openinference.instrumentation.langchain import LangChainInstrumentor
from openinference.semconv.trace import OpenInferenceMimeTypeValues, OpenInferenceSpanKindValues, SpanAttributes
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.id_generator import IdGenerator, RandomIdGenerator
from opentelemetry.sdk.trace.sampling import Decision, ParentBased, Sampler, SamplingResult
from opentelemetry.trace import Link, SpanKind, Tracer, get_current_span
from opentelemetry.trace.span import TraceState
from opentelemetry.util.types import Attributes

from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import UserId
from smart_tutor.shared.ports.run_tracing import RunTracing

KEY_SETTING = "SMART_TUTOR_LEARNER_HASH_KEY"
EXPORT_TIMEOUT_SECONDS = 10.0
LANGFUSE_TRACES_PATH = "/api/public/otel/v1/traces"
LANGFUSE_ENVIRONMENT = "langfuse.environment"
USER_ID = SpanAttributes.USER_ID
SESSION_ID = SpanAttributes.SESSION_ID
LANGFUSE_METADATA_PREFIX = "langfuse.trace.metadata."
LANGFUSE_INPUT = "langfuse.observation.input"
LANGFUSE_OUTPUT = "langfuse.observation.output"
_LOW_64_BITS = 0xFFFF_FFFF_FFFF_FFFF
# langchain-core ships a cloud tracing client and sends every run to it while any of these is on; ADR 0023 traces to
# Langfuse only.
LANGSMITH_SWITCHES = ("LANGSMITH_TRACING_V2", "LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2")
_root_run: ContextVar[uuid.UUID | None] = ContextVar("root_run", default=None)

logger = logging.getLogger(__name__)


def root_span_id(run_id: uuid.UUID) -> int:
    """An ask's root span id: the low 64 bits of its run id, so the API can address the span from the stored run id."""
    return run_id.int & _LOW_64_BITS


@contextmanager
def root_ids(run_id: uuid.UUID) -> Iterator[None]:
    """The next root span started inside takes `run_id` as its trace id and `root_span_id(run_id)` as its span id."""
    token = _root_run.set(run_id)
    try:
        yield
    finally:
        _root_run.reset(token)


class RunIds(IdGenerator):
    """Random ids, except the root span started inside `root_ids`, which takes the run's ids once."""

    def __init__(self) -> None:
        self._random = RandomIdGenerator()

    def generate_trace_id(self) -> int:
        run_id = _root_run.get()
        return run_id.int if run_id else self._random.generate_trace_id()

    def generate_span_id(self) -> int:
        run_id = _root_run.get()
        if run_id is None:
            return self._random.generate_span_id()
        _root_run.set(None)  # one-shot: later spans get random ids; root_ids restores the previous value on exit
        return root_span_id(run_id) or self._random.generate_span_id()


class RunIdRatio(Sampler):
    """Keeps a share of traces by hashing the whole 128-bit trace id. The SDK's TraceIdRatioBased reads only the low 64
    bits, and a uuid4 run id's low bits always start with the variant bits `10`, which would keep none at rates up to
    0.5 and skew the rest."""

    def __init__(self, rate: float) -> None:
        self._rate = rate
        self._bound = round(rate * 2**64)

    def should_sample(
        self,
        parent_context: Context | None,
        trace_id: int,
        name: str,
        kind: SpanKind | None = None,
        attributes: Attributes = None,
        links: Sequence[Link] | None = None,
        trace_state: TraceState | None = None,
    ) -> SamplingResult:
        digest = hashlib.blake2b(trace_id.to_bytes(16, "big"), digest_size=8).digest()
        keep = int.from_bytes(digest, "big") < self._bound
        parent = get_current_span(parent_context).get_span_context()
        return SamplingResult(
            Decision.RECORD_AND_SAMPLE if keep else Decision.DROP,
            attributes=attributes,  # the SDK takes a span's start attributes from the result, so pass them on
            trace_state=parent.trace_state if parent.is_valid else None,
        )

    def get_description(self) -> str:
        return f"RunIdRatio{{{self._rate}}}"


class LearnerHasher:
    """HMAC-SHA256 of a user id: stable per learner and key, different between learners, changed with the key."""

    def __init__(self, key: str) -> None:
        if not key:
            raise ValueError(f"{KEY_SETTING} is empty")
        self._key = key.encode()

    def __call__(self, user_id: UserId) -> str:
        return hmac.new(self._key, user_id.encode(), hashlib.sha256).hexdigest()


def tracing_enabled(settings: Settings) -> bool:
    """Traced into Langfuse with its URL and the project's key pair (ADR 0023); otherwise untraced."""
    return bool(
        settings.langfuse_url
        and settings.langfuse_public_key.get_secret_value()
        and settings.langfuse_secret_key.get_secret_value()
    )


def learner_hasher(settings: Settings) -> LearnerHasher | None:
    """The configured hasher; None when no key is set and tracing is off. Refuses to start without a key while
    tracing is on, so a span never goes out without its learner hash."""
    key = settings.learner_hash_key.get_secret_value()
    if key:
        return LearnerHasher(key)
    if tracing_enabled(settings):
        raise RuntimeError(f"{KEY_SETTING} is not set, but tracing is on")
    return None


def run_metadata(settings: Settings) -> dict[str, str]:
    """What every traced run says about where it ran and with which models."""
    return {
        "deployment": settings.deployment,
        "chat_model": settings.models.agent.model_id,
        "embedding_model": settings.models.embedding.model_id,
    }


def langfuse_exporter(settings: Settings, timeout: float = EXPORT_TIMEOUT_SECONDS) -> OTLPSpanExporter:
    pair = f"{settings.langfuse_public_key.get_secret_value()}:{settings.langfuse_secret_key.get_secret_value()}"
    return OTLPSpanExporter(
        endpoint=settings.langfuse_url.rstrip("/") + LANGFUSE_TRACES_PATH,
        headers={
            "authorization": f"Basic {base64.b64encode(pair.encode()).decode()}",
            # Without the version header Langfuse may take up to 10 minutes to show a trace (ADR 0023).
            "x-langfuse-ingestion-version": "4",
        },
        timeout=timeout,
    )


@dataclass(frozen=True)
class OtelTraces:
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


def otel_traces(
    environment: str,
    sampling_rate: float,
    processors: Sequence[SpanProcessor],
    hasher: LearnerHasher,
    metadata: Mapping[str, str],
) -> OtelTraces:
    provider = TracerProvider(
        # Langfuse's project comes from the keys; it reads the environment from here.
        resource=Resource({LANGFUSE_ENVIRONMENT: environment}),
        sampler=ParentBased(RunIdRatio(sampling_rate)),
        id_generator=RunIds(),
    )
    for processor in processors:
        provider.add_span_processor(processor)
    LangChainInstrumentor().instrument(tracer_provider=provider)
    return OtelTraces(provider, hasher, dict(metadata))


def stop_langsmith_tracing() -> None:
    """Runtime traces go to Langfuse only: langchain-core's own cloud tracing stays off in this process even when the
    environment (a developer's shell) turns it on. Call before the first model call: it caches what it reads."""
    for name in LANGSMITH_SWITCHES:
        os.environ[name] = "false"


def start_tracing(settings: Settings) -> OtelTraces | None:
    """Startup for a process that traces: turns langchain-core's cloud tracing off, then refuses tracing without a
    learner-hash key (see `learner_hasher`); None leaves the process untraced."""
    stop_langsmith_tracing()
    hasher = learner_hasher(settings)
    if not tracing_enabled(settings):
        # A deployed process given the URL was meant to trace: its keys are missing.
        missing_keys = settings.deployment != "local" and bool(settings.langfuse_url)
        logger.log(
            logging.WARNING if missing_keys else logging.INFO,
            "SMART_TUTOR_LANGFUSE_URL or its keys are not set; running untraced",
        )
        return None
    assert hasher is not None  # learner_hasher refuses tracing without a key
    processors = [BatchSpanProcessor(langfuse_exporter(settings))]
    traces = otel_traces(settings.deployment, settings.trace_sampling_rate, processors, hasher, run_metadata(settings))
    logger.info("tracing into Langfuse at %s", settings.langfuse_url)
    return traces


def span_attributes(inputs: Mapping[str, object] | None, metadata: Mapping[str, object]) -> dict[str, str]:
    """A root span's attributes: OpenInference's CHAIN kind; each metadata key as `langfuse.trace.metadata.<key>`
    (text; a None value is left out); and the inputs as `langfuse.observation.input` and `input.value`."""
    attributes = {SpanAttributes.OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.CHAIN.value}
    attributes |= {LANGFUSE_METADATA_PREFIX + key: _text(value) for key, value in metadata.items() if value is not None}
    if inputs is not None:
        attributes[SpanAttributes.INPUT_VALUE] = attributes[LANGFUSE_INPUT] = json.dumps(inputs)
        attributes[SpanAttributes.INPUT_MIME_TYPE] = OpenInferenceMimeTypeValues.JSON.value
    return attributes


def _text(value: object) -> str:
    """A metadata value as Langfuse filters it: text as it is, booleans as `true`/`false`, integers in decimal, and
    anything else (a list, a mapping, a float) as JSON."""
    if isinstance(value, str):
        return value
    if isinstance(value, bool | int):
        return json.dumps(value)
    return json.dumps(value, default=str)


def learner_attributes(user_hash: str, session_id: str | None) -> dict[str, str]:
    """A root span's learner and thread, set at its start: a root starts from an empty context, so it doesn't inherit
    them from `run_context`. A thread is present when its id is not None, as in the ask's metadata."""
    return {USER_ID: user_hash} | ({SESSION_ID: session_id} if session_id else {})


@contextmanager
def run_context(user_hash: str, session_id: str | None) -> Iterator[None]:
    """The run's learner hash and thread on every span started inside, LangChain's included: OpenInference copies
    them from the context. Langfuse v4 filters per observation, so the root alone isn't enough (ADR 0023)."""
    with using_attributes(user_id=user_hash, session_id=session_id or ""):  # an empty session id sets none
        yield


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


class OtelRunTracing(RunTracing):
    """Each run is a root span (its own trace) in the environment's project; the model calls inside nest beneath it, and
    every span names the learner hash as its user. A run here has no thread, so no session."""

    def __init__(self, traces: OtelTraces) -> None:
        self._traces = traces

    @contextmanager
    def run(self, name: str, user_id: UserId, metadata: Mapping[str, str]) -> Iterator[None]:
        learner = self._traces.hasher(user_id)
        with never_raising(self._root(name, learner, metadata), None):
            yield

    @contextmanager
    def _root(self, name: str, learner: str, metadata: Mapping[str, str]) -> Iterator[None]:
        attributes = span_attributes(None, {**self._traces.metadata, **metadata, "learner_hash": learner})
        attributes |= learner_attributes(learner, None)
        with run_context(learner, None):
            # An empty context: a root span, whatever span is current. `use_span` makes it current on top of the run
            # context; start_as_current_span would attach a context built from the empty one and lose the learner.
            span = self._traces.tracer().start_span(name, context=Context(), attributes=attributes)
            with trace.use_span(span, end_on_exit=True):
                yield

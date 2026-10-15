# Ask and Ingestion Runs Traced in Langfuse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every traced `ask` (agent) and `ingest` (worker) run is exported to the environment's Langfuse project over OTLP, locally and on-premise, with the learner hash as the user and the thread as the session on every span (#316).

**Architecture:** Keep the OpenTelemetry + OpenInference pipeline (one `TracerProvider` per process, `RunIds`, `RunIdRatio`, `never_raising`). Add a second `BatchSpanProcessor` whose exporter posts to `<langfuse-url>/api/public/otel/v1/traces` with Basic auth and `x-langfuse-ingestion-version: 4`. The Phoenix exporter stays beside it until #322 retires Phoenix: the API still rates Phoenix spans (#318 moves ratings) and the pilot smoke test still reads Phoenix. Root spans gain Langfuse attributes; children get `user.id`/`session.id` through OpenInference's `using_attributes`. On-premise, the URL comes from CDK context through SSM, the keys from operator-made secrets, and the worker reaches the host through its Squid proxy by exact name.

**Tech Stack:** Python 3.13, OpenTelemetry SDK 1.45, `openinference-instrumentation` 0.1.71 / `-langchain` 0.1.79, pydantic-settings, AWS CDK (Python), Docker Compose + Squid, bash.

**Spec:** `sdd/adr/0023-how-smart-tutor-uses-langfuse.md` §1, §3, §5 (and ADR 0017's tracing rules it carries over); ticket #316; PRD §9.1, §9.10, §10.4.

## Global Constraints

- Endpoint `<SMART_TUTOR_LANGFUSE_URL>/api/public/otel/v1/traces`; headers `authorization: Basic base64(public:secret)` and `x-langfuse-ingestion-version: 4`.
- Settings `SMART_TUTOR_LANGFUSE_URL`, `SMART_TUTOR_LANGFUSE_PUBLIC_KEY`, `SMART_TUTOR_LANGFUSE_SECRET_KEY`. Langfuse export is on only with all three set; without them the process exports nowhere new (runs untraced if Phoenix is off too).
- Resource attribute `langfuse.environment` = `settings.deployment` (`local`, `on-premise`). (`ci` belongs to #320.)
- `user.id` = learner hash and `session.id` = thread id on **every** span of a run (root and LangChain children); run metadata as `langfuse.trace.metadata.<key>` on the root; root input/output also as `langfuse.observation.input` / `langfuse.observation.output`.
- Trace id stays the run id; one project per environment: no `-ingestion` project in Langfuse (Phoenix keeps its `-ingestion` project until #322).
- On-premise: SSM `/<prefix>/langfuse-url` from CDK context `smart-tutor:langfuse-url` (`https://sec-dog.duckdns.org`); secrets `<prefix>/langfuse/public-key` and `<prefix>/langfuse/secret-key` made by the operator (optional: missing → untraced in Langfuse, deploy warns); new CDK-generated `<prefix>/langfuse/learner-hash-key` (64 chars, no punctuation), which becomes the app's `SMART_TUTOR_LEARNER_HASH_KEY`. The old `<prefix>/phoenix/learner-hash-key` stays until #322.
- Worker egress: the Langfuse host's exact name is added to Squid (ADR 0014), CONNECT on 443 only.
- Tracing never fails a request or a document's processing; no test sends a trace anywhere; tokens, user ids, and emails never reach a span (ADR 0007).
- The Langfuse SDK is not a runtime dependency.
- Native-cloud Helm charts are out of scope (ADR 0023 §7).
- Python style: `backend/AGENTS.md` (read it). Comments and docstrings in the file's existing voice; line length 120.

## Review Focus

- Both exporters on at once: one span must reach both processors, and Phoenix-only or Langfuse-only configs must each still trace — pinned in Task 1.
- A thread-less ask (evals; `thread_id is None`) must not set an empty `session.id` — pinned in Task 2.
- LangChain child spans created on another asyncio task must still carry `user.id`/`session.id` — pinned in Task 2 by asserting on every span from a real graph run.
- Langfuse host off at night (18:00–07:00): the on-premise deploy's egress check must not fail; a Squid refusal (403) must — pinned in Task 3.
- A developer's `.env` with Langfuse keys must not make tests trace — pinned in Task 1 (conftest blanks the URL; positive control).

---

### Task 1: Langfuse exporter beside Phoenix, with settings and the test guard

**Files:**
- Modify: `backend/src/smart_tutor/shared/config.py` (settings near `phoenix_url`, ~L79–91)
- Modify: `backend/src/smart_tutor/shared/adapters/tracing.py`
- Modify: `backend/src/smart_tutor/shared/adapters/ask_tracing.py`, `backend/src/smart_tutor/apps/agent/server.py`, `backend/src/smart_tutor/apps/worker/main.py`, `backend/src/smart_tutor/tutoring/adapters/phoenix_feedback.py` (renames only)
- Modify: `backend/tests/conftest.py`, `backend/tests/fakes/tracing.py`, `backend/tests/fakes/__init__.py` (exports), every test importing renamed names (`git grep -l "PhoenixTraces\|phoenix_traces\|PhoenixRunTracing\|PhoenixAskTracing\|tracing_enabled" backend`)
- Test: `backend/tests/unit/shared/test_tracing.py`, `backend/tests/test_tests_never_trace.py`, `backend/tests/unit/tutoring/test_phoenix_feedback.py`

**Interfaces:**
- Produces (later tasks rely on these exact names):
  - `Settings.langfuse_url: str = ""`, `Settings.langfuse_public_key: SecretStr = SecretStr("")`, `Settings.langfuse_secret_key: SecretStr = SecretStr("")`
  - `tracing.LANGFUSE_TRACES_PATH = "/api/public/otel/v1/traces"`
  - `tracing.langfuse_enabled(settings) -> bool` (URL and both keys non-empty)
  - `tracing.phoenix_enabled(settings) -> bool` (today's `tracing_enabled` body, renamed; `phoenix_feedback.answer_feedback` uses it)
  - `tracing.tracing_enabled(settings) -> bool` = `phoenix_enabled or langfuse_enabled` (gates the learner-hash key)
  - `tracing.langfuse_exporter(settings, timeout=EXPORT_TIMEOUT_SECONDS) -> OTLPSpanExporter`
  - `tracing.phoenix_exporter(settings, timeout=...)` (today's `otlp_exporter`, renamed)
  - `tracing.OtelTraces` (renamed `PhoenixTraces`; same fields `provider`, `hasher`, `metadata`)
  - `tracing.otel_traces(project: str, environment: str, sampling_rate: float, processors: Sequence[SpanProcessor], hasher: LearnerHasher, metadata: Mapping[str, str]) -> OtelTraces`
  - `tracing.OtelRunTracing` (renamed `PhoenixRunTracing`), `ask_tracing.OtelAskTracing` (renamed `PhoenixAskTracing`)
  - `tracing.start_tracing(settings, project) -> OtelTraces | None` (same signature; `project` is the Phoenix project)
  - `fakes.recorded_traces(...)` unchanged signature, yields `(OtelTraces, InMemorySpanExporter)`; its provider's resource has `langfuse.environment = "local"`.

- [ ] **Step 1: Write the failing tests** in `backend/tests/unit/shared/test_tracing.py` (adapt existing imports to the new names; reuse the file's `collector` fixture and `_Collector`):

```python
LANGFUSE = {"langfuse_public_key": "pk-lf-test", "langfuse_secret_key": "sk-lf-test"}


def test_langfuse_needs_its_url_and_both_keys() -> None:
    assert langfuse_enabled(Settings(langfuse_url=URL, **LANGFUSE))
    assert not langfuse_enabled(Settings(langfuse_url="", **LANGFUSE))
    assert not langfuse_enabled(Settings(langfuse_url=URL, langfuse_public_key="pk-lf-test"))
    assert not langfuse_enabled(Settings(langfuse_url=URL, langfuse_secret_key="sk-lf-test"))


def test_langfuse_alone_turns_tracing_on() -> None:
    settings = Settings(deployment="on-premise", phoenix_url="", langfuse_url=URL, **LANGFUSE)
    assert tracing_enabled(settings) and not phoenix_enabled(settings)


def test_langfuse_without_a_learner_hash_key_refuses_to_start() -> None:
    with pytest.raises(RuntimeError, match="SMART_TUTOR_LEARNER_HASH_KEY"):
        start_tracing(Settings(langfuse_url=URL, learner_hash_key="", **LANGFUSE), "p")


def _send_one_span_to_langfuse(settings: Settings) -> None:
    traces = otel_traces("p", "local", 1.0, [SimpleSpanProcessor(langfuse_exporter(settings))], LearnerHasher("k"), {})
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
    with recorded_traces() as (_, spans):
        ...  # start and end one span through the yielded traces' tracer
    [span] = spans.get_finished_spans()
    assert span.resource.attributes["langfuse.environment"] == "local"


def test_with_phoenix_and_langfuse_on_each_span_reaches_both() -> None:
    phoenix, langfuse = InMemorySpanExporter(), InMemorySpanExporter()
    traces = otel_traces(
        "p", "local", 1.0, [SimpleSpanProcessor(phoenix), SimpleSpanProcessor(langfuse)], LearnerHasher("k"), {}
    )
    try:
        traces.tracer().start_span("ask").end()
    finally:
        traces.shutdown()
    assert [s.name for s in phoenix.get_finished_spans()] == ["ask"]
    assert [s.name for s in langfuse.get_finished_spans()] == ["ask"]


def test_start_tracing_exports_to_each_configured_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    # Phoenix only, Langfuse only, both: count the processors start_tracing adds (wrap otel_traces with a spy).
    ...
```

Fill in the `...` bodies concretely (the second: `monkeypatch.setattr(tracing_module, "otel_traces", spy)` where `spy` records `len(processors)` and returns a real `otel_traces(...)`; call `start_tracing` for the three settings — Phoenix-only `Settings(phoenix_url=URL, learner_hash_key="k")` (local), Langfuse-only `Settings(phoenix_url="", langfuse_url=URL, learner_hash_key="k", **LANGFUSE)`, both — expecting 1, 1, 2; shut each down). Also add, beside the existing "collector that is down" test, the same test through `langfuse_exporter` (an ingest still returns `"A summary."`).

In `backend/tests/test_tests_never_trace.py` add:

```python
def test_a_langfuse_url_in_the_environment_does_not_reach_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "SMART_TUTOR_LANGFUSE_URL=https://langfuse.example\n"
        "SMART_TUTOR_LANGFUSE_PUBLIC_KEY=pk-lf-x\nSMART_TUTOR_LANGFUSE_SECRET_KEY=sk-lf-x\n"
    )
    monkeypatch.chdir(tmp_path)
    assert Settings().langfuse_url == ""
    assert start_tracing(Settings(learner_hash_key="k"), "smart-tutor-local") is None


def test_positive_control_without_the_guard_a_dotenv_langfuse_url_turns_tracing_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("SMART_TUTOR_LANGFUSE_URL=https://langfuse.example\n")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SMART_TUTOR_LANGFUSE_URL")
    assert Settings().langfuse_url == "https://langfuse.example"
```

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && uv run pytest tests/unit/shared/test_tracing.py tests/test_tests_never_trace.py -q`
Expected: ImportError / AttributeError on the new names.

- [ ] **Step 3: Implement**

`config.py`, after the Phoenix settings (keep their comment style):

```python
    # Runtime traces in Langfuse (PRD §10.4, ADR 0023): spans go to <langfuse_url>/api/public/otel/v1/traces with the
    # environment's project keys; the keys pick the project. Empty URL or keys: no Langfuse traces. Locally each
    # developer's own pair in smart-tutor-local; on-premise <prefix>/langfuse/public-key and secret-key.
    langfuse_url: str = ""
    langfuse_public_key: SecretStr = SecretStr("")
    langfuse_secret_key: SecretStr = SecretStr("")
```

Update the `learner_hash_key` comment: the deployed secret is now `<prefix>/langfuse/learner-hash-key`.

`tracing.py`:

```python
LANGFUSE_TRACES_PATH = "/api/public/otel/v1/traces"
LANGFUSE_ENVIRONMENT = "langfuse.environment"


def phoenix_enabled(settings: Settings) -> bool:
    """Traced into Phoenix with its URL; a deployed process also needs its key (the local Phoenix has no sign-in)."""
    if not settings.phoenix_url:
        return False
    return settings.deployment == "local" or bool(settings.phoenix_api_key.get_secret_value())


def langfuse_enabled(settings: Settings) -> bool:
    """Traced into Langfuse with its URL and the project's key pair (ADR 0023)."""
    return bool(
        settings.langfuse_url
        and settings.langfuse_public_key.get_secret_value()
        and settings.langfuse_secret_key.get_secret_value()
    )


def tracing_enabled(settings: Settings) -> bool:
    """Traced into either; Phoenix keeps a copy of every trace until #322 retires it."""
    return phoenix_enabled(settings) or langfuse_enabled(settings)


def langfuse_exporter(settings: Settings, timeout: float = EXPORT_TIMEOUT_SECONDS) -> OTLPSpanExporter:
    pair = f"{settings.langfuse_public_key.get_secret_value()}:{settings.langfuse_secret_key.get_secret_value()}"
    return OTLPSpanExporter(
        endpoint=settings.langfuse_url.rstrip("/") + LANGFUSE_TRACES_PATH,
        # Without the version header Langfuse may take up to 10 minutes to show a trace (ADR 0023).
        headers={"authorization": f"Basic {base64.b64encode(pair.encode()).decode()}", "x-langfuse-ingestion-version": "4"},
        timeout=timeout,
    )
```

Rename `otlp_exporter` → `phoenix_exporter`, `PhoenixTraces` → `OtelTraces`, `PhoenixRunTracing` → `OtelRunTracing`, `phoenix_traces` → `otel_traces` with the new signature:

```python
def otel_traces(
    project: str,
    environment: str,
    sampling_rate: float,
    processors: Sequence[SpanProcessor],
    hasher: LearnerHasher,
    metadata: Mapping[str, str],
) -> OtelTraces:
    provider = TracerProvider(
        # The project names Phoenix's project; Langfuse's comes from the key, and it reads the environment from here.
        resource=Resource({ResourceAttributes.PROJECT_NAME: project, LANGFUSE_ENVIRONMENT: environment}),
        sampler=ParentBased(RunIdRatio(sampling_rate)),
        id_generator=RunIds(),
    )
    for processor in processors:
        provider.add_span_processor(processor)
    LangChainInstrumentor().instrument(tracer_provider=provider)
    return OtelTraces(provider, hasher, dict(metadata))
```

`start_tracing`: build `processors` — `BatchSpanProcessor(phoenix_exporter(settings))` if `phoenix_enabled`, `BatchSpanProcessor(langfuse_exporter(settings))` if `langfuse_enabled`; untraced (return None) when the list is empty, keeping today's log lines for Phoenix and adding `logger.info("SMART_TUTOR_LANGFUSE_URL or its keys are not set; not tracing into Langfuse")` when Langfuse is off. Log where it traces: `"tracing into %s"` with e.g. `"Phoenix project smart-tutor-local at http://..., Langfuse at https://..."` (never the keys). Pass `settings.deployment` as `environment`. Update the module docstring: Langfuse (ADR 0023) and, until #322, a copy in Phoenix (ADR 0017); exports are on the SDK's thread, so a host that is off (nights) only logs and drops. `stop_langsmith_tracing` docstring: "Runtime traces go to Langfuse and Phoenix only".

`phoenix_feedback.answer_feedback`: use `phoenix_enabled` (ratings stay on Phoenix until #318).

`tests/conftest.py`: the session fixture that blanks `SMART_TUTOR_PHOENIX_URL` also blanks `SMART_TUTOR_LANGFUSE_URL`, `SMART_TUTOR_LANGFUSE_PUBLIC_KEY`, and `SMART_TUTOR_LANGFUSE_SECRET_KEY`; update its docstring ("No test reaches a Phoenix or Langfuse either"). Update `backend/AGENTS.md`'s test-guard bullet to name both URLs.

`fakes/tracing.py`: `recorded_traces` calls `otel_traces("smart-tutor-test", "local", sampling_rate, [SimpleSpanProcessor(exporter or memory)], ...)`; docstrings say "tracing" not "Phoenix tracing"; `FailingExporter` "as a tracing host that is down would".

Rename every caller (agent server, worker main, tests). Keep behavior otherwise identical.

- [ ] **Step 4: Run the backend checks**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add -A backend
git commit -m "Export runtime traces to Langfuse beside Phoenix (#316)" -m "<why: ADR 0023 §1; Phoenix keeps a copy until #322 because ratings (#318) and the smoke test still read it>"
```

---

### Task 2: Langfuse attributes on the run's spans

**Files:**
- Modify: `backend/src/smart_tutor/shared/adapters/tracing.py` (`span_attributes`, `OtelRunTracing.run`)
- Modify: `backend/src/smart_tutor/shared/adapters/ask_tracing.py`
- Test: `backend/tests/unit/shared/test_tracing.py`, `backend/tests/unit/apps/agent/test_ask_trace.py`, `backend/tests/unit/apps/agent/test_no_token_in_traces.py`

**Interfaces:**
- Consumes: `OtelTraces`, `OtelRunTracing`, `OtelAskTracing`, `recorded_traces` from Task 1.
- Produces: `tracing.span_attributes(inputs, metadata) -> dict[str, str]` now also sets `langfuse.trace.metadata.<key>` (str values; bools as `"true"`/`"false"`, ints as decimal strings) and, with inputs, `langfuse.observation.input` (same JSON as `input.value`). `tracing.run_context(user_hash: str, session_id: str | None) -> Iterator[None]` (context manager wrapping OpenInference's `using_attributes`, passing `session_id` only when not None).

Attribute names (constants in `tracing.py`): `USER_ID = SpanAttributes.USER_ID` (`"user.id"`), `SESSION_ID = SpanAttributes.SESSION_ID` (`"session.id"`), `LANGFUSE_METADATA_PREFIX = "langfuse.trace.metadata."`, `LANGFUSE_INPUT = "langfuse.observation.input"`, `LANGFUSE_OUTPUT = "langfuse.observation.output"`.

- [ ] **Step 1: Write the failing tests**

In `test_tracing.py` (ingest):

```python
def test_every_ingest_span_names_the_learner_hash_as_its_user() -> None:
    with recorded_traces() as (traces, spans):
        ingest(OtelRunTracing(traces))
    finished = spans.get_finished_spans()
    assert len(finished) > 1  # the root and the model call
    learner = LearnerHasher("k")(UserId("user-123"))
    assert all(s.attributes is not None and s.attributes["user.id"] == learner for s in finished)
    assert all(s.attributes is not None and "session.id" not in s.attributes for s in finished)


def test_ingest_metadata_is_langfuse_trace_metadata() -> None:
    with recorded_traces(metadata={"deployment": "local"}) as (traces, spans):
        ingest(OtelRunTracing(traces))
    [root] = [s for s in spans.get_finished_spans() if s.name == "ingest"]
    assert root.attributes is not None
    assert root.attributes["langfuse.trace.metadata.deployment"] == "local"
    assert root.attributes["langfuse.trace.metadata.content_id"] == "c-1"
    assert root.attributes["langfuse.trace.metadata.learner_hash"] == LearnerHasher("k")(UserId("user-123"))
```

In `test_ask_trace.py` (use the file's `traced(...)` helper, `RUN_ID`, `THREAD_ID`, `USER`; read it first to match how it returns spans):

```python
async def test_every_ask_span_carries_the_learner_hash_and_the_thread() -> None:
    # every span: the ask root, LangGraph nodes, and the model call
    ...
    assert all(s.attributes["user.id"] == LearnerHasher("k")(USER) for s in spans)
    assert all(s.attributes["session.id"] == THREAD_ID for s in spans)


async def test_an_ask_without_a_thread_sets_no_session() -> None:
    ...  # body without thread_id
    assert all("session.id" not in s.attributes for s in spans)


async def test_the_ask_root_has_langfuse_metadata_input_and_output() -> None:
    ...
    assert root.attributes["langfuse.trace.metadata.limited"] == "false"
    assert root.attributes["langfuse.trace.metadata.decline"] == "none"
    assert root.attributes["langfuse.trace.metadata.chunks"] == "2"
    assert root.attributes["langfuse.trace.metadata.thread_id"] == THREAD_ID
    assert root.attributes["langfuse.trace.metadata.chat_model"] == TRACE_META["chat_model"]
    assert json.loads(root.attributes["langfuse.observation.input"])["question"] == <the question>
    assert json.loads(root.attributes["langfuse.observation.output"])["answer"] == "It weighs tokens [1]."
    assert root.context.trace_id == RUN_ID.int  # still the run id
```

Write the `...` parts concretely from the file's existing tests (they already run an ask and pick out the root).

In `test_no_token_in_traces.py`, extend the privacy check to the Langfuse attributes and to user ids and emails: run a traced ask through `OtelAskTracing` (the file already has an end-to-end variant; reuse it) whose `AskRun.user_id` is `"user-id-under-test-42"` and whose question is plain, and assert `TOKEN`, `"user-id-under-test-42"`, and an email `"learner@example.com"` (put the email in the principal/claims the test builds, if it builds one; otherwise only the user id) are absent from `dumped(spans)`; positive control: the same run with the user id in the question → found. Keep the existing tests.

- [ ] **Step 2: Run them and see them fail**

Run: `cd backend && uv run pytest tests/unit/shared/test_tracing.py tests/unit/apps/agent -q`
Expected: KeyError on `user.id` / `langfuse.trace.metadata.*`.

- [ ] **Step 3: Implement**

`span_attributes`: keep the OpenInference attributes (Phoenix reads `metadata` JSON), add per-key `langfuse.trace.metadata.<key>` with `_text(value)` (`json.dumps` for bool → `"true"`, `str()` otherwise) and `langfuse.observation.input` = the same JSON as `input.value`. In `ask_tracing._end`, also set `langfuse.observation.output` with the output JSON.

`run_context`:

```python
@contextmanager
def run_context(user_hash: str, session_id: str | None) -> Iterator[None]:
    """The run's learner hash and thread on every span started inside, LangChain's included: OpenInference copies
    them from the context. Langfuse v4 filters per observation, so the root alone isn't enough (ADR 0023)."""
    attributes = {"user_id": user_hash} | ({"session_id": session_id} if session_id else {})
    with using_attributes(**attributes):
        yield
```

Set `user.id` (and `session.id` when there is a thread) on the root spans' start attributes too (the root is started with an empty `Context()`, so it doesn't inherit them).

`OtelRunTracing.run`: compute the hash once; inside `run_context(hash, None)`, start the root with `context=Context()` and make it current with `trace.use_span(span, end_on_exit=True)` (record_exception and set_status_on_exception default to True, matching `start_as_current_span`), all under `never_raising` as now. Note that `start_as_current_span(..., context=Context())` would attach a context built from the empty `Context()` and drop the `using_attributes` values, so it must not be used here.

`OtelAskTracing.trace`: today it attaches `trace.set_span_in_context(span)` with one `context.attach`. Keep a single attach, but build it on top of a context that holds the run attributes: 

```python
with run_context(metadata["learner_hash"], run.thread_id):
    base = context.get_current()
token = context.attach(trace.set_span_in_context(span, base))
```

so the generator still detaches exactly one token (see the existing comment about abandoned streams). Remove the now-duplicate `attributes["session.id"] = ...` line's Phoenix-only comment: it serves both (Phoenix and Langfuse group a conversation's asks as a session).

Update the docstrings of both modules (Langfuse first; "Phoenix" only where it is Phoenix-specific).

- [ ] **Step 4: Run the backend checks** (same command as Task 1). Expected: all pass.

- [ ] **Step 5: Commit** — `git commit -m "Name the learner hash and thread on every span for Langfuse (#316)"` with a why body.

---

### Task 3: On-premise settings, secrets, and worker egress to Langfuse

**Files:**
- Modify: `infra/cdk.json` (add `"smart-tutor:langfuse-url": "https://sec-dog.duckdns.org"`)
- Modify: `infra/smart_tutor_infra/app_stacks.py` (`_on_premise` passes the context to `ConfigStack`)
- Modify: `infra/smart_tutor_infra/stacks/config.py`
- Modify: `deploy/on-premise/deploy.sh`, `deploy/on-premise/compose.yaml`, `deploy/on-premise/check-egress.py`, `deploy/on-premise/check-worker.sh` (comment)
- Test: `infra/tests/test_config_stack.py`, `infra/tests/test_deployment_modes.py`, `infra/tests/test_host.py`, `infra/tests/test_check_egress.py`

**Interfaces:**
- Consumes: env names `SMART_TUTOR_LANGFUSE_URL`, `SMART_TUTOR_LANGFUSE_PUBLIC_KEY`, `SMART_TUTOR_LANGFUSE_SECRET_KEY`, `SMART_TUTOR_LEARNER_HASH_KEY` (Task 1).
- Produces: SSM `/<prefix>/langfuse-url`; secrets `<prefix>/langfuse/learner-hash-key` (generated), `<prefix>/langfuse/public-key`, `<prefix>/langfuse/secret-key` (operator); env-file keys `LANGFUSE_URL`, `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`; Squid acl `langfuse`.

- [ ] **Step 1: Write the failing tests** (read each test file first and follow its helpers):
  - `test_config_stack.py`: the generated-secret set gains `smart-tutor/langfuse/learner-hash-key` (the phoenix one stays); a test like `test_learner_hash_key_is_a_long_generated_string_per_mode` for the Langfuse key (64, no punctuation); with context `smart-tutor:langfuse-url` = `https://langfuse.example`, an SSM parameter `/<prefix>/langfuse-url` with that value; without the context (native-cloud), no `langfuse-url` parameter.
  - `test_deployment_modes.py`: the on-premise secret set gains `smart-tutor-on-premise/langfuse/learner-hash-key`, and on-premise has `/smart-tutor-on-premise/langfuse-url` from `cdk.json`.
  - `test_host.py`:
    - agent and worker env: `SMART_TUTOR_LANGFUSE_URL == "${LANGFUSE_URL:?}"`, `SMART_TUTOR_LANGFUSE_PUBLIC_KEY == "${LANGFUSE_PUBLIC_KEY}"`, `SMART_TUTOR_LANGFUSE_SECRET_KEY == "${LANGFUSE_SECRET_KEY}"`; Phoenix variables unchanged; the MCP server and API get no `SMART_TUTOR_LANGFUSE_` variable (the API gets them in #318).
    - Squid: `acls["langfuse"] == ["${LANGFUSE_HOST:?}"]` with `-n`, and `http_access allow CONNECT langfuse tls` before `deny all`; the `aws` acl unchanged.
    - `deploy.sh`: contains `learner_hash_key=$(secret langfuse/learner-hash-key)`, `langfuse_url=$(param langfuse-url)`, reads `langfuse/public-key` and `langfuse/secret-key` with `2>/dev/null`, warns on stderr naming `$prefix/langfuse/public-key` when either is missing and leaves both empty, renders `LANGFUSE_URL=`, `LANGFUSE_HOST=`, `LANGFUSE_PUBLIC_KEY=`, `LANGFUSE_SECRET_KEY=`; no longer `secret phoenix/learner-hash-key`. Add a test that runs the script's host-derivation line (or a small bash function `host_of`) in `bash -c` for `https://sec-dog.duckdns.org`, `https://sec-dog.duckdns.org/`, `https://h.example:8443/x` → `sec-dog.duckdns.org`, `sec-dog.duckdns.org`, `h.example` (skip when `bash` is missing, as other tests in the file do if they do).
  - `test_check_egress.py` (read its fakes for `_tunnel_status`):
    - with Langfuse configured (`SMART_TUTOR_LANGFUSE_URL=https://lf.example`, both keys), a proxy answering 403 to `CONNECT lf.example:443` → `unreachable()` contains `"Langfuse: the egress proxy refuses lf.example"`;
    - 200 → no Langfuse problem;
    - 502/503 (Squid can't reach an allowed host: Langfuse is off at night) → no problem, and a notice is printed (stdout) that Langfuse didn't answer;
    - without the keys, no CONNECT to the Langfuse host is attempted.

- [ ] **Step 2: Run them and see them fail** — `cd infra && uv run pytest -q` (expect the new tests to fail).

- [ ] **Step 3: Implement**
  - `ConfigStack.__init__(..., langfuse_url: str | None = None)`: when set, `ssm.StringParameter(self, "Param-langfuse-url", parameter_name=f"{names.ssm_path}/langfuse-url", string_value=langfuse_url)`. New secret `LangfuseLearnerHashKeySecret` named `{secret_prefix}/langfuse/learner-hash-key`, description "HMAC key for the learner hash in Langfuse traces", same generator as the Phoenix one. Update comments: the app reads the Langfuse key; the Phoenix one stays until #322; Langfuse's project keys are `<prefix>/langfuse/public-key` and `secret-key`, made by the operator (runbook).
  - `_on_premise`: `ConfigStack(..., langfuse_url=app.node.try_get_context("smart-tutor:langfuse-url") or None)` with a comment: the shared Langfuse host's DuckDNS name (ADR 0023), never a reference to the `Langfuse-Host` stack.
  - `deploy.sh`: `learner_hash_key=$(secret langfuse/learner-hash-key)`; `langfuse_url=$(param langfuse-url)`; `langfuse_host` = the URL's host name (bash parameter expansion: strip scheme, then everything from the first `/` or `:`); public and secret keys read like the Phoenix API key (empty and a warning naming both secrets when either is missing: `Warning: no Langfuse keys (are the secrets $prefix/langfuse/public-key and secret-key set?); deploying without Langfuse traces`). Render `LANGFUSE_URL`, `LANGFUSE_HOST`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` into the env file. Update the header comment.
  - `compose.yaml`: agent and worker env gain the three `SMART_TUTOR_LANGFUSE_*` variables (comment: ADR 0023, untraced in Langfuse until the operator's keys exist); Squid: `acl langfuse dstdomain -n ${LANGFUSE_HOST:?}` with a comment (the shared Langfuse host, exact name, ADR 0014/0023) and `http_access allow CONNECT langfuse tls`. Update the header comment about the worker's ways out. The worker's `NO_PROXY` stays `phoenix`: Langfuse goes through the proxy.
  - `check-egress.py`: `_langfuse()` (URL and both keys set); in `unreachable()`, when on, `status = _tunnel_status(host, 443)`; 403 → problem `f"Langfuse: the egress proxy refuses {host}"`; 200 → fine; anything else → `print(f"Notice: Langfuse at {host} didn't answer through the proxy ({status}); it is off 18:00-07:00", file=sys.stdout)` and no problem (tracing is non-critical, ADR 0023 §3). Docstring and final message name Langfuse when on.
  - `check-worker.sh`: comment says Langfuse goes through the proxy.

- [ ] **Step 4: Run** `cd infra && uv run pytest -q` → all pass. Run `bash -n deploy/on-premise/deploy.sh`.

- [ ] **Step 5: Commit** — `git commit -m "Render the Langfuse settings on-premise and let the worker reach Langfuse (#316)"` with a why body (ADR 0023 §5, ADR 0014).

---

### Task 4: Local config, runbooks, and the PRD

**Files:**
- Modify: `.env.example`, `compose.ci.yaml`, `infra/tests/test_workflows.py`
- Modify: `docs/runbooks/on-premise-deploy.md` (§ worker egress, teardown table, §10 tracing, troubleshooting), `docs/runbooks/langfuse-host.md`, `README.md`, `AGENTS.md`, `sdd/prd.md`

**Interfaces:**
- Consumes: the names from Tasks 1–3.

- [ ] **Step 1: Failing test** in `infra/tests/test_workflows.py`, beside `test_ci_app_services_run_untraced`: the CI override also blanks `SMART_TUTOR_LANGFUSE_URL=` for api, agent, mcp, worker (#320 gives CI its own project). Run `cd infra && uv run pytest tests/test_workflows.py -q` → fails.

- [ ] **Step 2: Implement**
  - `compose.ci.yaml`: add `- SMART_TUTOR_LANGFUSE_URL=` to `x-ci-env`, update its comment.
  - `.env.example`: a Langfuse block above the Phoenix one: `SMART_TUTOR_LANGFUSE_URL=https://sec-dog.duckdns.org`, empty `SMART_TUTOR_LANGFUSE_PUBLIC_KEY=` / `SMART_TUTOR_LANGFUSE_SECRET_KEY=`, with comments: make your own key pair in project `smart-tutor-local` (organization Smart Tutor; ask the Langfuse admin for an invite), never production's; without keys no Langfuse traces; the host is off 18:00–07:00 Asia/Ho_Chi_Minh and local runs are untraced then (export errors are logged and dropped). Learner-hash key comment: the secret is `<prefix>/langfuse/learner-hash-key` when deployed. Phoenix comment: keeps a copy until #322.
  - `docs/runbooks/langfuse-host.md`: a section "Smart Tutor's organization and projects (ADR 0023)": as the admin, create organization **Smart Tutor**; projects `smart-tutor-on-premise`, `smart-tutor-local`, `smart-tutor-evals`; invite Smart Tutor's people to that organization only; per-project keys under *Settings → API Keys*. Where traces show: *Tracing → Traces*, filter by name `ask`/`ingest`, environment, user (learner hash), session (thread).
  - `docs/runbooks/on-premise-deploy.md`: §10 becomes "Tracing (Langfuse, and Phoenix until #322)": what is traced (one project, `ask` and `ingest` by trace name, environment `on-premise`, learner hash as user, thread as session, metadata keys); **Turn it on**: in project `smart-tutor-on-premise` create a key pair, then `aws secretsmanager create-secret --name smart-tutor-on-premise/langfuse/public-key --secret-string pk-lf-...` and the same for `secret-key`, redeploy; until then the deploy warns and Langfuse gets nothing; **URL**: `infra/cdk.json` `smart-tutor:langfuse-url` → SSM `/smart-tutor-on-premise/langfuse-url`, redeploy the Config stack to change it; **Learner-hash key**: now `smart-tutor-on-premise/langfuse/learner-hash-key` (from #316; Phoenix traces after that deploy use it too, so older Phoenix traces don't group with newer ones); **Egress**: the worker reaches the Langfuse host through `egress-proxy` by exact name (acl `langfuse`); the deploy check fails if Squid refuses it and only notes it when the host is off; **Where to find traces** (link the Langfuse runbook). Keep the Phoenix paragraphs (ratings, smoke test) marked as until #318/#322. Update the worker-egress paragraph (~L258), the teardown table rows (add the two operator secrets as "Kept, created by hand" and the generated key), the prerequisites line (~L25), and the egress check line (~L159).
  - `README.md` and `AGENTS.md` local-dev lines: local runs trace into Langfuse project `smart-tutor-local` when `.env` has your key pair, and into the local Phoenix until #322.
  - `sdd/prd.md`: §9.1 worker row and §9.10 "Malicious PDFs": egress also to the Langfuse host by exact name through the proxy (on-premise); §10.4: replace "Until #316 ships, traces go to the environment's Phoenix (ADR 0017)." with "Until Phoenix is retired (#322), each trace also goes to the environment's Phoenix (ADR 0017), where ratings still land until #318."; §9.12 local line likewise. Bump the version in the status line and add a changelog entry if the PRD keeps one (follow its pattern), and update the PRD version in `AGENTS.md`'s table.

- [ ] **Step 3: Run** `cd infra && uv run pytest -q` and `cd backend && uv run pytest -q` → pass.

- [ ] **Step 4: Commit** — `git commit -m "Document Langfuse tracing keys and where traces show (#316)"` with a why body.

---

## Verification after all tasks

- All checks from `AGENTS.md` for backend and infra (no `web/` or Helm change).
- If `.env` in the main checkout has Langfuse keys and the host answers `https://sec-dog.duckdns.org/api/public/health`, run the agent on the host and ask one question, then confirm an `ask` trace with child spans in `smart-tutor-local`. Otherwise list this, the on-premise chat, and the upload check as manual steps in the PR.

---

## Follow-up after PR #333 review (2026-10-14): Langfuse only

The product owner decided: **switch off Phoenix**, so runtime traces go to Langfuse only. One learner-hash key is fine; `langfuse.environment` = deployment is fine; native-cloud's unused secret stays; fix the deferred review minors. Phoenix the *service* (Compose, the on-premise container, the Caddy route, its secrets, `send-test-span.py`) stays until #322 removes it. Ratings stop going to Phoenix (they are still saved with the turn); #318 sends them to Langfuse. The pilot smoke test's `--trace-project` check reads Phoenix and moves to Langfuse in #318.

Pydantic-settings rejects unknown `SMART_TUTOR_*` keys in a `.env` file read from the working directory (environment variables are ignored), so removing the Phoenix settings is safe for Compose `env_file` and `uv run --env-file`; docs tell developers to delete `SMART_TUTOR_PHOENIX_*` from their `.env`.

### Task 5: Backend traces and ratings without Phoenix

**Files:** `backend/src/smart_tutor/shared/config.py`, `shared/adapters/tracing.py`, `shared/adapters/ask_tracing.py`, `apps/agent/server.py`, `apps/worker/main.py`, `apps/api/services.py`, `apps/api/main.py`, `apps/api/routes/threads.py`, `tutoring/README.md`; delete `tutoring/adapters/phoenix_feedback.py`, `tests/unit/tutoring/test_phoenix_feedback.py`, `tests/fakes/phoenix.py` (and its exports in `tests/fakes/__init__.py`); tests in `tests/unit/shared/test_tracing.py`, `tests/unit/apps/agent/*`, `tests/test_tests_never_trace.py`, `tests/conftest.py`; `backend/AGENTS.md`; regenerate `web/src/api/` (the Makefile's `api-client` one-liner).

- Settings: remove `phoenix_url`, `phoenix_api_key`, `phoenix_project`.
- `tracing.py`: remove `phoenix_enabled`, `phoenix_exporter`, `ingestion_project`, the Phoenix project resource attribute, and the OpenInference `metadata` JSON attribute (Langfuse reads `langfuse.trace.metadata.*`; keep `input.value`/`output.value` and the span kind). `tracing_enabled(settings)` is true with the URL and both Langfuse keys (one public name: fold `langfuse_enabled` into it). `start_tracing(settings) -> OtelTraces | None` (no project argument); `otel_traces(environment, sampling_rate, processors, hasher, metadata)`. Log lines: untraced → `"SMART_TUTOR_LANGFUSE_URL or its keys are not set; running untraced"` (info locally; warning when deployed with a URL but without keys); traced → `"tracing into Langfuse at %s"`. `stop_langsmith_tracing` docstring: runtime traces go to Langfuse only. `root_span_id`/`RunIds` stay.
- Ratings: the API wires `NoAnswerFeedback()` (comment: ratings are saved with the turn; #318 sends them to Langfuse as `learner_rating` scores). Delete the Phoenix adapter, its tests and fake. Update `api/main.py`'s shutdown docstring and the rating route's docstrings; the `trace_id` field description becomes "The ask's trace id (its run id), for attaching a rating (#227); null for turns kept before it was recorded." Regenerate the web API client (CI fails when stale) and run `cd web && npm ci && npm run build`.
- Test guard: conftest blanks only the Langfuse URL and keys; `test_tests_never_trace.py` keeps the Langfuse guard and positive control and drops the Phoenix ones.
- Deferred minors: (a) `OtelAskTracing.trace` ends the root span when anything after `start_span` fails (no unended span), with a test that makes the context step raise and asserts the ask still runs untraced and the span ended; (b) `learner_attributes` and the ask metadata agree on "a thread is present" (`is not None` in both); (c) `_text` JSON-encodes every non-`str` value except bools/ints, which keep today's text (`"true"`/`"false"`, decimal) — with a test for a list value; (d) the `start_tracing` processor-count test captures processors robustly (e.g. bind the spy's call with `inspect.signature(otel_traces)`), not `args[3]`.
- Tests: Langfuse-only processor count (0 or 1), untraced without keys, every ask/ingest/privacy test on Langfuse attributes only.
- Checks: full backend check; `cd web && npm ci && npm run build`. Commit: `Trace into Langfuse only and stop rating Phoenix spans (#316)`.

### Task 6: App deploy and config without Phoenix

**Files:** `compose.yaml`, `compose.ci.yaml`, `.env.example`, `deploy/on-premise/compose.yaml`, `deploy/on-premise/deploy.sh`, `deploy/on-premise/check-egress.py`, `deploy/on-premise/check-worker.sh`, `infra/tests/test_host.py`, `infra/tests/test_check_egress.py`, `infra/tests/test_workflows.py`.

- Local `compose.yaml`: api/agent/worker lose `SMART_TUTOR_PHOENIX_URL` and the api's `depends_on: phoenix`; the `phoenix` service stays (comment: unused since #316, #322 removes it). `compose.ci.yaml`: drop the `SMART_TUTOR_PHOENIX_URL=` line and its comment. `.env.example`: drop `SMART_TUTOR_PHOENIX_URL`/`PROJECT` and the Phoenix comment block; say to delete any `SMART_TUTOR_PHOENIX_*` left in an old `.env`.
- On-premise `compose.yaml`: api/agent/worker lose `SMART_TUTOR_PHOENIX_URL/_API_KEY/_PROJECT`; the worker's `NO_PROXY`/`no_proxy: phoenix` go; the `phoenix` service leaves the `worker` network (`networks: [default]`), so the worker reaches only Postgres and the egress proxy. Comments updated.
- `deploy.sh`: stop reading `phoenix/api-key` and rendering `PHOENIX_API_KEY` (the Phoenix service's own secrets stay until #322).
- `check-egress.py`: drop the Phoenix probe and `_tracing()`; add `phoenix:6006` to the direct connections that must fail. Docstring and success message no longer name Phoenix. `check-worker.sh` comment likewise.
- Deferred minor: `host_of` in `deploy.sh` also strips userinfo (`https://u:p@h.example/x` → `h.example`), with a test case.
- Tests: update every infra assertion about the app's Phoenix wiring (worker network members, NO_PROXY, api/agent/worker env, deploy.sh `PHOENIX_API_KEY` lines, the CI override, compose app services); keep the Phoenix *service* tests (#322 removes them).
- Checks: `cd infra && uv run pytest -q`; `bash -n deploy/on-premise/deploy.sh`. Commit: `Stop wiring the app to Phoenix on-premise and locally (#316)`.

### Task 7: Docs for Langfuse-only tracing

**Files:** `README.md`, `AGENTS.md`, `docs/runbooks/on-premise-deploy.md`, `docs/runbooks/on-premise-monitoring.md`, `docs/runbooks/langfuse-host.md`, `sdd/prd.md`.

- Everywhere: runtime traces go to Langfuse only; Phoenix still runs (local Compose, on-premise) but receives nothing, and #322 removes it; ratings are saved with the turn and reach Langfuse with #318; the smoke test's `--trace-project` check waits for #318.
- README: the Phoenix row and lines and the `make up` comment; tell developers to drop `SMART_TUTOR_PHOENIX_*` from `.env`. AGENTS.md local-dev lines.
- On-premise runbook §10 ("Tracing (Langfuse)"): drop the Phoenix copy, ratings-to-Phoenix, and Phoenix-key steps; mark §11 Phoenix "unused since #316, removed by #322"; egress-check and worker-egress paragraphs (the worker no longer reaches Phoenix); teardown row for `phoenix/api-key` (no longer read). Monitoring runbook: Bedrock usage in Langfuse traces.
- Deferred minor: in `langfuse-host.md`, move the Smart Tutor organization section in with the other admin sections (before patching/restore/teardown), renumbering.
- PRD v2.70 (v2.69 was merged with PR #333, so the change got its own v2.70 row rather than rewording the "Changes from v2.68" row) (Langfuse only; Phoenix receives nothing until #322 removes it; ratings reach Langfuse with #318) and §9.1, §9.10, §9.12, §10.4, Appendix A (no Phoenix key).
- Checks: `cd infra && uv run pytest -q`. Commit: `Document Langfuse-only tracing (#316)`.

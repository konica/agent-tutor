# Learner ratings reach Phoenix — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A learner's 👍 / 👎 on a turn reaches the environment's Phoenix as a `learner_rating` `HUMAN` span annotation on the turn's `ask` root span, locally and on production (#290).

**Architecture:** A Phoenix adapter for the `AnswerFeedback` port (`tutoring/adapters/phoenix_feedback.py`) talks to Phoenix's REST API with `httpx` on one background thread, in rating order. The API builds it from the same Phoenix settings the agent traces with; the on-premise Compose file gives the API those settings. The ask's root span id is `root_span_id(run_id)` (slice 3, `shared/adapters/tracing.py`).

**Tech Stack:** Python 3.12, httpx (`MockTransport` for the fake Phoenix), FastAPI, Arize Phoenix 20.16 REST API, Docker Compose, pytest.

**Spec:** ticket #290 (parent #286), ADR 0017 "Ratings", PRD §10.2, §10.3 item 7.

## What Phoenix 20.16 actually does (probed against the local Phoenix, 2026-10-13)

- `POST /v1/span_annotations?sync=true` with `{"data": [{span_id, name, annotator_kind, identifier, result: {label, score}}]}` upserts by `(name, span, identifier)`: a second POST with the same identifier replaces the first.
- `DELETE /v1/projects/{project}/span_annotations?name=…&identifier=…&annotator_kind=HUMAN&delete_all=true` removes exactly those annotations (204, also when none match). It cannot filter by span id, so **the identifier is the run id** — that keeps one rating per span and lets a clear address it. An unknown project answers 404.
- **A rating that reaches Phoenix before its span is lost:** `sync=true` answers `404 Spans with IDs … do not exist.`; `sync=false` answers 200 and silently drops it, even 0 s before the span arrives. The agent's batch exporter sends the `ask` span up to ~5 s after the answer ends, so a quick 👍 would be lost. The adapter therefore posts with `sync=true` and retries a 404 after waits of 1, 2, 4, 8, 16 s (31 s). A span still missing after that was not traced (sampling rate < 1, or the agent untraced): logged as a warning, not an error.

## Global Constraints

- Annotation: name `learner_rating`, `annotator_kind` `HUMAN`, `identifier` = run id (str), `result` = `{"label": "up"|"down", "score": 1|0}`, nothing else (no `metadata`, no explanation). No user id, email, name, or token anywhere in a request to Phoenix; the only credential is the Phoenix system key as `authorization: Bearer`.
- Sent off the request, one background thread, in the order rated. A failure is logged with the run id and error class (and HTTP status) only; the rating stays saved.
- Ratings are sent only while `tracing_enabled(settings)` (Phoenix URL set; a deployed process also needs the key), into the agent's project `settings.phoenix_project`.
- Clearing: the product has no un-press (PRD v2.46: "Not built: … un-pressing a rating"). The port gets `clear(run_id)` and the adapter deletes the annotation, so un-pressing needs no adapter work later; no route or UI calls it in this slice.
- Dropped: LangSmith's "a 👎 extends the trace's retention" (every production trace lives 180 days).
- Backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Infra: `cd infra && uv run pytest`. Commit subjects imperative, ending `(#290)`, body says why, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A 👍 within a second of the answer (span not yet exported) must still land — test: span appears after two 404s.
2. A rating for a turn that was never traced must not log an error or retry forever — test: 404 on every try gives a warning after the last wait.
3. 👍 then 👎 then clear in quick succession must end with no annotation, never a stale one — test: ordering with a late span.
4. Phoenix down (connection refused) must not fail the rating route — test via the conversation service path already exists (`FakeAnswerFeedback(error=…)`); add an adapter test that a `ConnectError` is logged.
5. A Phoenix project not created yet (no traces) when clearing → 404 must be treated as nothing to clear — test.

---

### Task 1: Phoenix adapter for `AnswerFeedback`, with a fake Phoenix

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/ports/answer_feedback.py`
- Create: `backend/src/smart_tutor/tutoring/adapters/phoenix_feedback.py`
- Create: `backend/tests/fakes/phoenix.py`
- Modify: `backend/tests/fakes/__init__.py` (export `FakePhoenix`, `InlineExecutor`)
- Modify: `backend/tests/fakes/tutoring.py` (`FakeAnswerFeedback.clear`)
- Test: `backend/tests/unit/tutoring/test_phoenix_feedback.py`

**Interfaces:**
- Produces: `AnswerFeedback.clear(run_id: RunId) -> None` (abstract); `NoAnswerFeedback.clear` no-op; `FakeAnswerFeedback.cleared: list[RunId]`.
- Produces: `PhoenixAnswerFeedback(client: httpx.Client, project: str, executor: Executor | None = None, waits: Sequence[float] = SPAN_WAITS, sleep: Callable[[float], None] = time.sleep)` with `.send(run_id, rating)`, `.clear(run_id)`, `.close()`; module constants `ANNOTATION_NAME = "learner_rating"`, `SPAN_WAITS = (1.0, 2.0, 4.0, 8.0, 16.0)`; factory `answer_feedback(settings: Settings) -> AnswerFeedback`.
- Produces: `fakes.FakePhoenix(spans=(), late=None, down=False)` with `.transport` (an `httpx.MockTransport`), `.client(key="test-key") -> httpx.Client`, `.annotations: dict[tuple[str, str, str], dict]` keyed `(span_id, name, identifier)`, `.requests: list[httpx.Request]`, `.projects: set[str]`; `fakes.InlineExecutor`.
- Consumes: `root_span_id(run_id: uuid.UUID) -> int` and `tracing_enabled(settings) -> bool` from `smart_tutor.shared.adapters.tracing`.

- [ ] **Step 1: Add `clear` to the port and the fakes**

`answer_feedback.py`:

```python
"""Learner ratings sent on to where answers are traced (PRD §10.2): Phoenix span annotations (ADR 0017)."""

from abc import ABC, abstractmethod

from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.domain.turn import Rating


class AnswerFeedback(ABC):
    @abstractmethod
    def send(self, run_id: RunId, rating: Rating) -> None:
        """Attach the learner's rating to the answer's run, replacing an earlier one. Must not block on the network;
        never given who rated."""

    @abstractmethod
    def clear(self, run_id: RunId) -> None:
        """Remove the run's rating (a learner un-rating a turn; not offered yet, PRD §10.2). Must not block on the
        network."""


class NoAnswerFeedback(AnswerFeedback):
    """Ratings are only saved with the turn."""

    def send(self, run_id: RunId, rating: Rating) -> None:
        return None

    def clear(self, run_id: RunId) -> None:
        return None
```

`FakeAnswerFeedback` gains `self.cleared: list[RunId] = []` and:

```python
    def clear(self, run_id: RunId) -> None:
        if self._error is not None:
            raise self._error
        self.cleared.append(run_id)
```

- [ ] **Step 2: Write the fake Phoenix** (`tests/fakes/phoenix.py`)

```python
"""A Phoenix REST API in memory for the rating adapter (Phoenix 20.16's span-annotation endpoints, as probed for #290):
POST /v1/span_annotations?sync=true upserts by (span, name, identifier) and answers 404 for a span it doesn't have yet;
DELETE /v1/projects/{project}/span_annotations deletes by name, identifier, and kind, needs delete_all (or a time
window), and answers 404 for an unknown project."""

import json
from collections.abc import Callable, Iterable
from concurrent.futures import Executor, Future
from typing import Any

import httpx


class InlineExecutor(Executor):
    """Runs each submitted call at once on the caller's thread, so a test sees its effect when send returns."""

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> "Future[Any]":
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as e:  # noqa: BLE001 - handed to the future, as a real executor does
            future.set_exception(e)
        return future


class FakePhoenix:
    def __init__(
        self,
        spans: Iterable[str] = (),
        late: dict[str, int] | None = None,
        down: bool = False,
        projects: Iterable[str] = ("smart-tutor-test",),
    ) -> None:
        self.spans = set(spans)  # span ids (16 hex digits) Phoenix has
        self.late = dict(late or {})  # span id -> how many more annotation POSTs find it missing before it arrives
        self.down = down
        self.projects = set(projects)
        self.annotations: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def client(self, key: str = "test-key") -> httpx.Client:
        return httpx.Client(
            base_url="http://phoenix.test", transport=self.transport, headers={"authorization": f"Bearer {key}"}
        )

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        path = request.url.path
        if request.method == "POST" and path == "/v1/span_annotations":
            return self._annotate(request)
        if request.method == "DELETE" and path.startswith("/v1/projects/") and path.endswith("/span_annotations"):
            return self._delete(request, path.removeprefix("/v1/projects/").removesuffix("/span_annotations"))
        return httpx.Response(405)

    def _annotate(self, request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("sync") == "true", "an async insert is dropped when the span isn't there yet"
        data = json.loads(request.content)["data"]
        missing = [a["span_id"] for a in data if not self._has(a["span_id"])]
        if missing:
            return httpx.Response(404, text=f"Spans with IDs {', '.join(missing)} do not exist.")
        for a in data:
            self.annotations[(a["span_id"], a["name"], a.get("identifier", ""))] = a
        return httpx.Response(200, json={"data": [{"id": str(i)} for i, _ in enumerate(data)]})

    def _has(self, span_id: str) -> bool:
        if self.late.get(span_id, 0) > 0:
            self.late[span_id] -= 1
            if self.late[span_id] == 0:
                self.spans.add(span_id)
            return False
        return span_id in self.spans

    def _delete(self, request: httpx.Request, project: str) -> httpx.Response:
        params = request.url.params
        if params.get("delete_all") != "true" and not (params.get("start_time") and params.get("end_time")):
            return httpx.Response(422, text="bound the delete or set delete_all")
        if project not in self.projects:
            return httpx.Response(404, text=f"Project with name {project} not found")
        for key, a in list(self.annotations.items()):
            if all(
                params.get(field) in (None, a.get(field))
                for field in ("name", "identifier", "annotator_kind")
            ):
                del self.annotations[key]
        return httpx.Response(204)
```

Note `_has`: with `late={span: 2}` the first two POSTs get 404 and the span exists from the third on. Export both names from `fakes/__init__.py` (import line and `__all__`).

- [ ] **Step 3: Write the failing adapter tests** (`tests/unit/tutoring/test_phoenix_feedback.py`)

```python
import json
import logging
import threading
import uuid

import httpx
import pytest
from pydantic import SecretStr

from fakes import FakePhoenix, InlineExecutor
from smart_tutor.shared.adapters.tracing import root_span_id
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.adapters.phoenix_feedback import PhoenixAnswerFeedback, answer_feedback
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import NoAnswerFeedback

RUN = RunId(str(uuid.uuid4()))
SPAN = f"{root_span_id(uuid.UUID(RUN)):016x}"
PROJECT = "smart-tutor-test"


def feedback(phoenix: FakePhoenix, waits: tuple[float, ...] = (1.0, 2.0)) -> tuple[PhoenixAnswerFeedback, list[float]]:
    slept: list[float] = []
    sender = PhoenixAnswerFeedback(
        phoenix.client(), PROJECT, executor=InlineExecutor(), waits=waits, sleep=slept.append
    )
    return sender, slept


def ratings(phoenix: FakePhoenix) -> list[tuple[str, str, str, str, float]]:
    return [
        (span, name, a["identifier"], a["result"]["label"], a["result"]["score"])
        for (span, name, _), a in phoenix.annotations.items()
    ]


def test_a_rating_is_a_human_annotation_on_the_asks_root_span() -> None:
    phoenix = FakePhoenix(spans=[SPAN])
    feedback(phoenix)[0].send(RUN, Rating.UP)
    assert ratings(phoenix) == [(SPAN, "learner_rating", RUN, "up", 1)]
    [a] = phoenix.annotations.values()
    assert a["annotator_kind"] == "HUMAN"


def test_a_not_helpful_rating_scores_zero() -> None:
    phoenix = FakePhoenix(spans=[SPAN])
    feedback(phoenix)[0].send(RUN, Rating.DOWN)
    assert ratings(phoenix) == [(SPAN, "learner_rating", RUN, "down", 0)]


def test_a_new_rating_replaces_the_earlier_one() -> None:
    phoenix = FakePhoenix(spans=[SPAN])
    sender, _ = feedback(phoenix)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    assert ratings(phoenix) == [(SPAN, "learner_rating", RUN, "down", 0)]


def test_clearing_deletes_only_this_runs_rating() -> None:
    other = RunId(str(uuid.uuid4()))
    other_span = f"{root_span_id(uuid.UUID(other)):016x}"
    phoenix = FakePhoenix(spans=[SPAN, other_span])
    sender, _ = feedback(phoenix)
    sender.send(RUN, Rating.UP)
    sender.send(other, Rating.DOWN)
    sender.clear(RUN)
    assert ratings(phoenix) == [(other_span, "learner_rating", other, "down", 0)]
    [delete] = [r for r in phoenix.requests if r.method == "DELETE"]
    assert delete.url.path == f"/v1/projects/{PROJECT}/span_annotations"
    assert dict(delete.url.params) == {
        "name": "learner_rating",
        "identifier": RUN,
        "annotator_kind": "HUMAN",
        "delete_all": "true",
    }


def test_clearing_before_the_project_has_any_trace_is_nothing_to_do(caplog: pytest.LogCaptureFixture) -> None:
    phoenix = FakePhoenix(projects=())
    feedback(phoenix)[0].clear(RUN)
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_rating_before_the_span_is_exported_waits_for_it() -> None:
    phoenix = FakePhoenix(late={SPAN: 2})
    sender, slept = feedback(phoenix, waits=(1.0, 2.0, 4.0))
    sender.send(RUN, Rating.UP)
    assert ratings(phoenix) == [(SPAN, "learner_rating", RUN, "up", 1)]
    assert slept == [1.0, 2.0]


def test_a_run_that_was_never_traced_is_a_warning_after_the_last_wait(caplog: pytest.LogCaptureFixture) -> None:
    phoenix = FakePhoenix()
    sender, slept = feedback(phoenix, waits=(1.0, 2.0))
    sender.send(RUN, Rating.UP)
    assert slept == [1.0, 2.0] and phoenix.annotations == {}
    [record] = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert record.levelno == logging.WARNING and RUN in record.getMessage()


def test_ratings_and_a_clear_apply_in_the_order_given_even_while_the_span_is_late() -> None:
    phoenix = FakePhoenix(late={SPAN: 1})
    sender, _ = feedback(phoenix)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    sender.clear(RUN)
    assert phoenix.annotations == {}
    assert [r.method for r in phoenix.requests] == ["POST", "POST", "POST", "DELETE"]


def test_an_unreachable_phoenix_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    sender, slept = feedback(FakePhoenix(down=True))
    sender.send(RUN, Rating.UP)
    sender.clear(RUN)
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2 and all(RUN in m and "ConnectError" in m for m in errors)
    assert slept == []  # only a missing span is waited for


def test_a_refused_key_is_logged_with_its_status(caplog: pytest.LogCaptureFixture) -> None:
    refusing = httpx.Client(base_url="http://phoenix.test", transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    PhoenixAnswerFeedback(refusing, PROJECT, executor=InlineExecutor(), sleep=lambda s: None).send(RUN, Rating.UP)
    [message] = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert "401" in message


def test_the_annotation_carries_nothing_but_the_rating() -> None:
    phoenix = FakePhoenix(spans=[SPAN])
    feedback(phoenix)[0].send(RUN, Rating.DOWN)
    [post] = phoenix.requests
    assert json.loads(post.content) == {
        "data": [
            {
                "span_id": SPAN,
                "name": "learner_rating",
                "annotator_kind": "HUMAN",
                "identifier": RUN,
                "result": {"label": "down", "score": 0},
            }
        ]
    }
    assert dict(post.url.params) == {"sync": "true"}


def test_the_send_runs_off_the_callers_thread() -> None:
    release = threading.Event()
    phoenix = FakePhoenix(spans=[SPAN])

    def held(request: httpx.Request) -> httpx.Response:
        release.wait(timeout=10)
        return phoenix.transport.handle_request(request)

    client = httpx.Client(base_url="http://phoenix.test", transport=httpx.MockTransport(held))
    sender = PhoenixAnswerFeedback(client, PROJECT)
    sender.send(RUN, Rating.UP)
    assert phoenix.annotations == {}  # send returned while the request is still held back
    release.set()
    sender.close()
    assert len(phoenix.annotations) == 1


def test_answer_feedback_sends_to_the_agents_project_with_the_key() -> None:
    settings = Settings(
        phoenix_url="http://phoenix:6006", phoenix_api_key=SecretStr("k-123"), phoenix_project="smart-tutor-on-premise",
        deployment="on-premise",
    )
    sender = answer_feedback(settings)
    assert isinstance(sender, PhoenixAnswerFeedback)
    assert sender.project == "smart-tutor-on-premise"
    assert sender.client.base_url == httpx.URL("http://phoenix:6006")
    assert sender.client.headers["authorization"] == "Bearer k-123"
    sender.close()


def test_the_local_phoenix_needs_no_key() -> None:
    sender = answer_feedback(
        Settings(phoenix_url="http://localhost:10404", phoenix_api_key=SecretStr(""), deployment="local")
    )
    assert isinstance(sender, PhoenixAnswerFeedback) and "authorization" not in sender.client.headers
    sender.close()


@pytest.mark.parametrize(
    "settings",
    [
        Settings(phoenix_url=""),
        Settings(phoenix_url="http://phoenix:6006", phoenix_api_key=SecretStr(""), deployment="on-premise"),
    ],
    ids=["no-url", "deployed-without-key"],
)
def test_answer_feedback_is_off_while_tracing_is_off(settings: Settings) -> None:
    assert isinstance(answer_feedback(settings), NoAnswerFeedback)
```

- [ ] **Step 4: Run and see them fail**

Run: `cd backend && uv run pytest tests/unit/tutoring/test_phoenix_feedback.py -q`
Expected: collection error, `No module named 'smart_tutor.tutoring.adapters.phoenix_feedback'`.

- [ ] **Step 5: Write the adapter** (`tutoring/adapters/phoenix_feedback.py`)

```python
"""Learner ratings as Phoenix span annotations on the ask's root span (PRD §10.2, ADR 0017), so LLM judges can be
calibrated against them. `learner_rating` is a HUMAN annotation (label up or down, score 1 or 0) whose identifier is
the run id: Phoenix upserts by name, span, and identifier, so a new rating replaces the last, and a clear deletes it by
identifier. Sent off the request on one background thread, in the order rated: a slow or unreachable Phoenix never
delays or fails the rating, which is already saved with the turn. A failure is logged. The annotation says only the
rating: no user id, email, name, or token (PRD §10.4)."""

import logging
import time
import urllib.parse
import uuid
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, Future, ThreadPoolExecutor

import httpx

from smart_tutor.shared.adapters.tracing import root_span_id, tracing_enabled
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import AnswerFeedback, NoAnswerFeedback

logger = logging.getLogger(__name__)

ANNOTATION_NAME = "learner_rating"
# Phoenix drops an annotation whose span it doesn't have yet, and the agent exports the ask span a few seconds after the
# answer ends: a 404 is retried after these waits (31 s in all). Still missing then, the ask was not traced.
SPAN_WAITS = (1.0, 2.0, 4.0, 8.0, 16.0)
REQUEST_TIMEOUT_SECONDS = 10.0


class _SpanNotTraced(Exception):
    pass


class PhoenixAnswerFeedback(AnswerFeedback):
    def __init__(
        self,
        client: httpx.Client,
        project: str,
        executor: Executor | None = None,
        waits: Sequence[float] = SPAN_WAITS,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.project = project
        # One worker: requests go in the order the learner rated, so the last rating is the one left.
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="answer-feedback")
        self._waits = tuple(waits)
        self._sleep = sleep

    def send(self, run_id: RunId, rating: Rating) -> None:
        self._submit(self._annotate, run_id, rating)

    def clear(self, run_id: RunId) -> None:
        self._submit(self._delete, run_id)

    def close(self) -> None:
        """Wait for the requests still queued (process shutdown)."""
        self._executor.shutdown(wait=True)

    def _submit(self, call: Callable[..., None], run_id: RunId, *args: object) -> None:
        self._executor.submit(call, run_id, *args).add_done_callback(lambda done: _log_failure(done, run_id))

    def _annotate(self, run_id: RunId, rating: Rating) -> None:
        body = {
            "data": [
                {
                    "span_id": f"{root_span_id(uuid.UUID(run_id)):016x}",
                    "name": ANNOTATION_NAME,
                    "annotator_kind": "HUMAN",
                    "identifier": str(run_id),
                    "result": {"label": rating.value, "score": 1 if rating is Rating.UP else 0},
                }
            ]
        }
        for wait in (*self._waits, None):
            response = self.client.post("/v1/span_annotations", params={"sync": "true"}, json=body)
            if response.status_code != 404:
                response.raise_for_status()
                return
            if wait is None:
                raise _SpanNotTraced
            self._sleep(wait)

    def _delete(self, run_id: RunId) -> None:
        response = self.client.delete(
            f"/v1/projects/{urllib.parse.quote(self.project, safe='')}/span_annotations",
            params={"name": ANNOTATION_NAME, "identifier": str(run_id), "annotator_kind": "HUMAN", "delete_all": "true"},
        )
        if response.status_code != 404:  # 404: the project has no trace yet, so nothing to clear
            response.raise_for_status()


def _log_failure(done: "Future[None]", run_id: RunId) -> None:
    error = done.exception()
    if error is None:
        return
    if isinstance(error, _SpanNotTraced):
        logger.warning("the rating of run %s was not sent: Phoenix has no ask span for it (not traced?)", run_id)
    elif isinstance(error, httpx.HTTPStatusError):
        logger.error("sending the rating of run %s to Phoenix failed (%s)", run_id, error.response.status_code)
    else:
        logger.error("sending the rating of run %s to Phoenix failed (%s)", run_id, type(error).__name__)


def answer_feedback(settings: Settings) -> AnswerFeedback:
    """Phoenix annotations into the agent's project while tracing is on (same URL and key as its traces); else none."""
    if not tracing_enabled(settings):
        return NoAnswerFeedback()
    key = settings.phoenix_api_key.get_secret_value()
    client = httpx.Client(
        base_url=settings.phoenix_url.rstrip("/"),
        headers={"authorization": f"Bearer {key}"} if key else None,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return PhoenixAnswerFeedback(client, settings.phoenix_project)
```

If the status-code log test fails because `type(error).__name__` was expected elsewhere, keep the test as written: status for HTTP errors, class name otherwise.

- [ ] **Step 6: Run the adapter tests and the full checks**

Run: `cd backend && uv run pytest tests/unit/tutoring -q && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: all pass. (`FakeAnswerFeedback` now implements `clear`, so no abstract-class error elsewhere.)

- [ ] **Step 7: Commit**

```bash
git add backend/src/smart_tutor/tutoring backend/tests/fakes backend/tests/unit/tutoring/test_phoenix_feedback.py
git commit -m "Send learner ratings to Phoenix as span annotations (#290)" -m "<why: ADR 0017 ratings; sync POST retried on 404 because Phoenix drops an annotation that arrives before its span; identifier = run id so a clear can address it>"
```

---

### Task 2: The API sends ratings to Phoenix, with no token in the payload

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/services.py` (wire `answer_feedback(settings)`)
- Modify: `backend/tests/fakes/api.py` (`feedback: AnswerFeedback | None`)
- Modify: `backend/tests/unit/apps/agent/test_no_token_in_traces.py` (annotation payload privacy, with a positive control)
- Modify: `compose.yaml` (`api`: `SMART_TUTOR_PHOENIX_URL: http://phoenix:6006`)
- Modify: `backend/src/smart_tutor/tutoring/README.md` (replace "`NoAnswerFeedback` is wired until #290 …" with the Phoenix adapter sentence)

**Interfaces:**
- Consumes: `answer_feedback(settings: Settings) -> AnswerFeedback`, `PhoenixAnswerFeedback`, `FakePhoenix`, `InlineExecutor` from Task 1.

- [ ] **Step 1: Write the failing privacy test** — append to `test_no_token_in_traces.py`, and update its module docstring's first line to "…so Phoenix never receives it, in spans or in rating annotations."

```python
def rated_requests(question: str) -> str:
    """Ask through the API as Ada with TOKEN, rate the turn 👎, and return every request the API made to Phoenix."""
    verifier = FakeTokenVerifier()
    verifier.add(TOKEN, Principal(UserId(USER_ID), EMAIL, frozenset({"learner"})))
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, USER_ID, "Attention weighs tokens.")
    seen: list[httpx.Request] = []

    def agent(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, content=AGENT_SSE, headers={"content-type": "text/event-stream"})

    phoenix = FakePhoenix()
    sender = PhoenixAnswerFeedback(phoenix.client(), "smart-tutor-test", executor=InlineExecutor(), sleep=lambda s: None)
    services = api_services(library, threads=threads, agent=fake_agent(agent), feedback=sender)
    client = TestClient(create_app(Settings(), verifier=verifier, services=services))
    auth = {"Authorization": f"Bearer {TOKEN}"}
    client.post("/threads", json={"question": question}, headers=auth)
    run_id = json.loads(seen[0].content)["run_id"]
    phoenix.spans.add(f"{root_span_id(uuid.UUID(run_id)):016x}")
    [thread] = threads.threads.values()
    rated = client.put(f"/threads/{thread.thread_id}/turns/{run_id}/rating", json={"rating": "down"}, headers=auth)
    assert rated.status_code == 200 and phoenix.annotations, "nothing was annotated, so the check would pass vacuously"
    return json.dumps(
        [{"url": str(r.url), "headers": dict(r.headers), "body": r.content.decode()} for r in phoenix.requests]
    )


def test_the_rating_annotation_holds_no_token_user_id_or_email() -> None:
    sent = rated_requests("What is attention?")
    # Positive control: the dump holds the request bodies (the annotation) and headers (the Phoenix key), so a secret
    # in either would be caught.
    assert "learner_rating" in sent and "Bearer test-key" in sent
    for secret in (TOKEN, USER_ID, EMAIL):
        assert secret not in sent


```

Use `AGENT_SSE = b'event: delta\ndata: {"text": "It weighs tokens [1]."}\n\nevent: done\ndata: {}\n\n'`. Imports to add: `httpx`, `TestClient` from `fastapi.testclient`, `FakePhoenix`, `FakeTokenVerifier`, `InMemoryLibrary`, `InMemoryThreads`, `InlineExecutor`, `api_services`, `fake_agent`, `ingest_ready` from `fakes`; `create_app` from `smart_tutor.apps.api.main`; `Settings`; `Principal` from `smart_tutor.shared.domain.principal`; `root_span_id` from `smart_tutor.shared.adapters.tracing`; `PhoenixAnswerFeedback` from `smart_tutor.tutoring.adapters.phoenix_feedback`.

- [ ] **Step 2: Run it**

Run: `cd backend && uv run pytest tests/unit/apps/agent/test_no_token_in_traces.py -q`
Expected: PASS — it is a guard on the route → adapter path, which Task 1 already provides. `uv run mypy` fails on `feedback=sender` until `fakes/api.py` types `feedback` as `AnswerFeedback | None` (import it from `smart_tutor.tutoring.application`); change that hint.

- [ ] **Step 3: Wire the API**

`services.py`: replace `from smart_tutor.tutoring.application import ConversationService, NoAnswerFeedback` with `from smart_tutor.tutoring.application import ConversationService` and add `from smart_tutor.tutoring.adapters.phoenix_feedback import answer_feedback`; pass `feedback=answer_feedback(settings)`. (`apps` may import a module's adapters: it is the composition root.)

`compose.yaml` `api.environment`, after `SMART_TUTOR_AGENT_URL`:

```yaml
      SMART_TUTOR_PHOENIX_URL: http://phoenix:6006  # ratings as annotations on the agent's traces (#290); .env has localhost:10404
```

and add `phoenix: {condition: service_started}` to the api's `depends_on`. (`compose.ci.yaml` already blanks the URL for `api`.)

- [ ] **Step 4: Run the backend checks**

Run: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest -q`
Expected: all pass, including `tests/isolation/test_threads.py` (another learner's turn: 404, nothing sent).

- [ ] **Step 5: Verify against the local Phoenix** (the Compose Phoenix on :10404 is running)

Start the agent, MCP, and API on the host (`make mcp`, `make agent`, `make api` — or their one-line commands from the Makefile, with `uv run --env-file ../.env`), sign in to the web app as `learner@example.com`, ask a question, click 👍 then 👎. Then:

```bash
curl -s "http://localhost:10404/v1/projects/smart-tutor-local/span_annotations?span_ids=<16-hex span id>" 
```

Expected: one `learner_rating` annotation, label `down`, score 0, identifier the run id. If the web stack isn't available, drive it with a short script: build `answer_feedback(Settings(phoenix_url="http://localhost:10404"))`, send a span with `root_ids(run_id)` through `start_tracing`, then `send` up, `send` down, `clear`, `close`, checking the GET after each.

- [ ] **Step 6: Commit**

```bash
git add backend compose.yaml
git commit -m "Wire the Phoenix rating adapter into the API (#290)" -m "<why>"
```

---

### Task 3: Production ratings: on-premise API settings and the smoke test

**Files:**
- Modify: `deploy/on-premise/compose.yaml` (`api` environment)
- Modify: `deploy/on-premise/deploy.sh` (comment above the Phoenix key: the API uses it too)
- Modify: `infra/tests/test_host.py` (API gets the Phoenix settings; `mcp` still doesn't)
- Modify: `deploy/pilot/smoke_test.py` (`check_rating` after `check_trace`)
- Modify: `infra/tests/test_smoke_test.py`
- Modify: `docs/runbooks/on-premise-deploy.md`, `docs/runbooks/pilot-deploy.md` (ratings in Phoenix; the smoke test checks one)

**Interfaces:**
- Consumes: annotation shape from Task 1 (name `learner_rating`, identifier = run id, label/score).

- [ ] **Step 1: Write the failing infra tests** in `infra/tests/test_host.py`

Replace `test_services_that_make_no_model_calls_of_their_own_do_not_trace` with:

```python
def test_the_mcp_server_does_not_trace(compose: dict[str, Any]) -> None:
    env = compose["services"]["mcp"]["environment"]
    assert not [k for k in env if k.startswith("LANGSMITH_")]
    assert not [k for k in env if k.startswith("SMART_TUTOR_PHOENIX_")]


def test_the_api_sends_ratings_to_the_on_premise_phoenix(compose: dict[str, Any]) -> None:
    api = compose["services"]["api"]
    env = api["environment"]
    assert env["SMART_TUTOR_DEPLOYMENT"] == "on-premise"  # without the key it sends nothing (not unauthenticated)
    assert env["SMART_TUTOR_PHOENIX_URL"] == "http://phoenix:6006"
    assert env["SMART_TUTOR_PHOENIX_API_KEY"] == "${PHOENIX_API_KEY}"
    assert env["SMART_TUTOR_PHOENIX_PROJECT"] == compose["services"]["agent"]["environment"]["SMART_TUTOR_PHOENIX_PROJECT"]
    assert not [k for k in env if k.startswith("LANGSMITH_")]
```

Run: `cd infra && uv run pytest tests/test_host.py -q` → the new API test fails (`KeyError`).

- [ ] **Step 2: Give the API the settings** — `deploy/on-premise/compose.yaml`, `api.environment` after `SMART_TUTOR_ENVIRONMENT: prod`:

```yaml
      SMART_TUTOR_DEPLOYMENT: on-premise
      # Ratings go to Phoenix as annotations on the agent's ask traces (#290); none until the key's secret exists.
      SMART_TUTOR_PHOENIX_URL: http://phoenix:6006
      SMART_TUTOR_PHOENIX_API_KEY: ${PHOENIX_API_KEY}
      SMART_TUTOR_PHOENIX_PROJECT: smart-tutor-on-premise
```

`api` is on the `default` network with `phoenix`, so no network change. In `deploy.sh`, change the comment above `phoenix_api_key=` so it says the agent, worker, **and API** use the key (traces and ratings) and run untraced / send no ratings without it. Re-run the infra tests → pass, including `test_deploy_script_renders_the_tracing_settings_and_leaves_the_key_empty_without_its_secret`.

- [ ] **Step 3: Smoke test checks the rating** — read `infra/tests/test_smoke_test.py` first and follow how it tests `check_trace` (fake HTTP server / patched `_Session`). Add to `smoke_test.py`:

```python
def check_rating(s: _Session, run: _Run, project: str, phoenix_url: str, api_key: str) -> str:
    """Rate the ask 👎 and wait for its learner_rating annotation on the ask span in Phoenix."""
    r = s.api("PUT", f"/api/threads/{run.thread_id}/turns/{run.run_id}/rating", {"rating": "down"})
    if r.status != 200:
        raise SmokeTestError(f"rating: PUT the turn's rating gave {r.status}, expected 200")
    span_id = f"{uuid.UUID(run.run_id).int & 0xFFFF_FFFF_FFFF_FFFF:016x}"
    path = (
        f"/v1/projects/{urllib.parse.quote(project, safe='')}/span_annotations"
        f"?span_ids={span_id}&include_annotation_names=learner_rating"
    )
    try:
        while True:
            r = _phoenix(s, path, api_key, phoenix_url)
            if r.status in (401, 403):
                raise SmokeTestError("rating: Phoenix refused the API key")
            found = _json(r, "rating") if r.status == 200 else {}
            data = found.get("data") if isinstance(found, dict) else None
            mine = [a for a in data or [] if isinstance(a, dict) and a.get("identifier") == run.run_id]
            if mine:
                break
            s.wait("the rating's annotation")
    except SmokeTestError as e:
        if "the deadline passed" not in str(e):
            raise
        raise SmokeTestError(
            f"rating: run {run.run_id}'s rating never reached Phoenix (does the API have the Phoenix settings?)"
        ) from None
    result = mine[0].get("result") if isinstance(mine[0].get("result"), dict) else {}
    if mine[0].get("annotator_kind") != "HUMAN" or result.get("label") != "down" or result.get("score") != 0:
        raise SmokeTestError(f"rating: the annotation is not a HUMAN 'down' with score 0: {mine[0]!r}")
    return f"rating of {run.run_id} is in {project}"
```

`check_trace` must store the run id on `run` (add `run_id: str | None = None` to `_Run` and set `run.run_id = run_id` in `check_trace`). In `run_end_to_end`, after `print(check_trace(...))`, call `print(check_rating(s, run, *trace))`. Adapt names to what `_Run`, `_json`, and `s.wait` really are in the file. Tests in `infra/tests/test_smoke_test.py`: the annotation found (passes, PUT body `{"rating": "down"}` sent with the learner's bearer, Phoenix GET with the API key only); never found before the deadline (fails with the "never reached Phoenix" message); wrong label (fails); 401 (fails "refused the API key").

- [ ] **Step 4: Runbooks** — in `docs/runbooks/on-premise-deploy.md`'s Phoenix section say ratings arrive as `learner_rating` annotations on the `ask` span (Annotations tab), from the API with the same key; without the key no ratings are sent. In `pilot-deploy.md` where `--trace-project` is described, add that it also rates the turn 👎 and requires the annotation. Keep the runbooks' existing tone; only touch the sentences about traces and ratings.

- [ ] **Step 5: Run checks and commit**

Run: `cd infra && uv run pytest -q` → pass.

```bash
git add deploy infra/tests docs/runbooks
git commit -m "Send production ratings to the on-premise Phoenix and check one in the smoke test (#290)" -m "<why>"
```

---

### Task 4: PRD and docs

**Files:**
- Modify: `sdd/prd.md` (status line → v2.57, new "Changes from v2.56" row, §10.2, §10.3 item 7)
- Modify: `CONTEXT.md` (Rating entry), `AGENTS.md` (PRD version in the sources table), `.env.example` (Phoenix comment: the API sends ratings with the same settings)

- [ ] **Step 1: PRD**

Status line: `Draft v2.57 (…unchanged…)`. New row above "Changes from v2.55":

`| **Changes from v2.56** | Ratings in Phoenix (#290, §10.2, §10.3 item 7, ADR 0017): the API sends each 👍 / 👎 to the environment's Phoenix as a `learner_rating` `HUMAN` span annotation on the turn's `ask` root span (span id from the stored run id; label `up` or `down`, score 1 or 0; identifier the run id, so a new rating replaces the last). It goes off the request on one background thread, in order; a rating that arrives before the ask span is exported is retried for about 30 s, a turn that was never traced is logged as a warning, and an outage is logged while the rating stays saved. The annotation carries no user id, email, or token. The on-premise API gets the Phoenix URL, key, and project, so production ratings are sent for the first time; without the key none are sent. The port can clear a rating (deletes the annotation), but the product still has no un-press. Dropped: "a 👎 extends the trace's retention" (every production trace lives 180 days). Growing datasets from 👎 turns needs an export from Phoenix, not built yet. |`

§10.2 first paragraph becomes:

`Under each kept answer or decline the learner rates it Helpful (👍) or Not helpful (👎): one rating per turn, a new one replaces it (`thread_turns.rating`; `PUT /threads/{id}/turns/{run_id}/rating`, operation `rate_turn`). The API saves it with the turn, then sends it to the environment's Phoenix as a `learner_rating` `HUMAN` span annotation on the ask's root span (label `up` or `down`, score 1 or 0), off the request and in order; a Phoenix outage is logged and never fails the rating. The annotation carries only the rating. Admins score a weekly sample in an annotation queue; revise a judge prompt when judge–human agreement drops below ~80%.`

§10.3 item 7: `**Grow from production:** 👎-rated, judge-flagged, and declined questions (scrubbed) become candidates. 👎 ratings live in Phoenix (§10.2) while datasets are in LangSmith: an export from Phoenix is needed and not built yet.`

Grep `sdd/prd.md` for other "#290" mentions (e.g. in §10.4 or appendices, "not sent anywhere until #290") and rewrite them in the present tense.

- [ ] **Step 2: CONTEXT.md, AGENTS.md, .env.example**

CONTEXT.md Rating: `Saved with the turn and sent to Phoenix as a `learner_rating` span annotation on the turn's ask span.` AGENTS.md sources table: `sdd/prd.md` (v2.57). `.env.example`: in the Phoenix block, note the API sends ratings to the same Phoenix and project. Keep wording short.

- [ ] **Step 3: Check and commit**

Run: `cd backend && uv run pytest -q tests/unit` and `cd infra && uv run pytest -q` (some tests read docs).

```bash
git add sdd/prd.md CONTEXT.md AGENTS.md .env.example
git commit -m "Say in the PRD that ratings go to Phoenix (v2.57, #290)" -m "<why>"
```

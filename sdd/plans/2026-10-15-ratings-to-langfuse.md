# Learner ratings reach Langfuse — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A learner's 👍 / 👎 on a turn reaches that ask's Langfuse trace as a `learner_rating` BOOLEAN score; rating again replaces it, clearing removes it; the pilot smoke test reads the trace and the rating from Langfuse instead of Phoenix (#318).

**Architecture:** A Langfuse adapter for the existing `AnswerFeedback` port (`tutoring/adapters/langfuse_feedback.py`) replaces the Phoenix one (`phoenix_feedback.py`, deleted). It talks to Langfuse's public REST API with `httpx` and Basic auth on one background thread, in rating order. The API builds it from the same Langfuse settings the agent traces with (`langfuse_enabled`); the on-premise Compose file gives the API those settings instead of Phoenix's. The smoke test's trace and rating checks read Langfuse's v2 observations and v3 scores APIs.

**Tech Stack:** Python 3.12, httpx (`MockTransport` for the fake Langfuse), FastAPI, Langfuse 4.47.0 public API (the version `platform/langfuse/deploy/compose.yaml` pins), Docker Compose, pytest; the smoke test is standard library only.

**Spec:** ticket #318 (parent #220), ADR 0023 §6 "Ratings", PRD §10.2, §10.4.

## What Langfuse 4.47.0 actually does (read from its source at tag v4.47.0, 2026-10-15)

The host runs 4.47.0 with the default `LANGFUSE_MIGRATION_V4_WRITE_MODE=events_only`. In that mode the legacy read routes answer **404** before auth: `GET /api/public/traces`, `GET /api/public/traces/{id}`, `GET /api/public/scores`, `GET /api/public/v2/scores` (and their `/{id}`). What works:

- `POST /api/public/scores` (Basic auth) body `{id, traceId, name, value, dataType, environment, configId?}` → **200 `{"id": …}`**, 400 on a schema error (BOOLEAN `value` must be 0 or 1). Processed **asynchronously**: queued with a 5 s delay (15 s around 00:00 UTC), then written. **The trace is never looked up**: a score for a trace that hasn't arrived (or never will) is stored. So the ticket's "retrying while the trace hasn't arrived" is dropped (ADR 0023 §6 asked #318 to confirm this).
- **Score configs are checked only with `configId`.** A score posted with `name` alone is never matched to a config. With `configId`, the worker validates data type and archived state after the 200 and silently drops a score that fails. `GET /api/public/score-configs?page=&limit=` (max 100; no name filter) → `{data: [{id, name, dataType, isArchived, …}], meta: {page, limit, totalItems, totalPages}}`. So the adapter looks the `learner_rating` config up by name once and sends its id.
- `GET /api/public/v3/scores?traceId=<hex>&name=learner_rating&limit=100[&cursor=…]` → `{data: [{id, name, value, dataType, environment, timestamp, …}], meta: {limit, cursor?}}`; `meta.cursor` only when more pages exist. The query is **strict**: an unknown parameter (e.g. `page`) is 400. A BOOLEAN score's `value` comes back as JSON `true`/`false`. `fields=details` adds `configId`. A score shows here only once ingested (~6–10 s after its POST).
- `DELETE /api/public/scores/{id}` → **always 202**, queued with no delay. **A delete that runs before the score is ingested removes nothing, and the score then appears and stays.** So before deleting a score this process posted moments ago, the adapter waits until the list shows it.
- `GET /api/public/v2/observations?traceId=<hex>&fields=core,basic,io,metadata&expandMetadata=<keys>&limit=1000` works in events_only. Each item: `id` (the OTel span id, 16 lowercase hex), `traceId`, `parentObservationId` (null for a root), `name`, `type`, `environment`, `userId`, `sessionId`, `input`, `output`, `metadata`. Our root span's `langfuse.trace.metadata.<key>` attributes come back as `metadata.<key>` on the root observation only. Metadata values are truncated unless their key is in `expandMetadata`.
- `GET /api/public/projects` with a project key → `{data: [{id, name, …}]}`: exactly the key's project.
- `x-langfuse-ingestion-version` matters only for OTLP, not scores.

## Global Constraints

- Score: name `learner_rating`, `dataType` `BOOLEAN`, `value` 1 for up and 0 for down, `traceId` = `uuid.UUID(run_id).hex`, `environment` = `settings.deployment` (`local`, `on-premise`), `id` a new `uuid4` string per rating, `configId` the project's `learner_rating` config when one exists. Nothing else: no comment, metadata, user id, email, name, or token. The only credential is the project key pair as HTTP Basic auth.
- Each rating posts a **new** score, then deletes the trace's other `learner_rating` scores; clearing deletes them all. Never reuse a score id (ADR 0023 §6).
- Off the request, one background thread, in the order rated. A failure is logged with the run id and the error class (and HTTP status) only; the rating stays saved and the request never fails. `close()` (API shutdown) stops a wait in progress and drops ratings not yet started.
- Ratings are sent only while `langfuse_enabled(settings)` (URL and both keys set); otherwise `NoAnswerFeedback`. Phoenix no longer receives ratings (traces still go to Phoenix until #322).
- The product has no un-press; `clear` stays port-only (no route).
- Backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Infra: `cd infra && uv run pytest`. Commit subjects imperative, ending `(#318)`, body says why, trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. 👍 then 👎 within a few seconds (the 👍 not yet ingested) must end with one score, the 👎, not two: test with a lagging fake, the adapter waits for the 👍 to show before deleting it.
2. A rating posted before its trace exists must be sent once, without waiting or a warning: test.
3. A score config missing, archived, or of another data type must not lose ratings: the score goes without `configId` and one warning is logged: tests.
4. More `learner_rating` scores on a trace than one page (e.g. left over from an earlier process) must all be deleted: test with a page size of 2 and three scores.
5. Langfuse down, or refusing the key, must be logged and never raised: tests (adapter) plus the existing conversation-service test of a failing `send`.

---

### Task 1: Langfuse adapter for `AnswerFeedback`, with a fake Langfuse; the API uses it

**Files:**
- Create: `backend/src/smart_tutor/tutoring/adapters/langfuse_feedback.py`
- Create: `backend/tests/fakes/langfuse.py` (fake Langfuse scores API)
- Create: `backend/tests/fakes/executor.py` (`InlineExecutor`, moved from `fakes/phoenix.py`)
- Create: `backend/tests/unit/tutoring/test_langfuse_feedback.py`
- Delete: `backend/src/smart_tutor/tutoring/adapters/phoenix_feedback.py`, `backend/tests/unit/tutoring/test_phoenix_feedback.py`, `backend/tests/fakes/phoenix.py`
- Modify: `backend/tests/fakes/__init__.py` (export `FakeLangfuse`, `InlineExecutor`; drop `FakePhoenix`)
- Modify: `backend/src/smart_tutor/apps/api/services.py:34` (import `answer_feedback` from `langfuse_feedback`)
- Modify: `backend/tests/unit/apps/agent/test_no_token_in_traces.py` (`rated_requests` uses `FakeLangfuse`)
- Modify: `backend/src/smart_tutor/tutoring/ports/answer_feedback.py` (module docstring: Langfuse scores, ADR 0023)
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py` (docstrings at ~L11–12 and ~L730–731, and the `run_id` field description at ~L663: "The ask's trace id in Langfuse, …"), then `make api-client` (or its one-line command from the `Makefile`) to regenerate `web/src/api/`
- Modify: `backend/src/smart_tutor/tutoring/README.md` (the ratings sentence: `LangfuseAnswerFeedback` sends a `learner_rating` BOOLEAN score on the turn's trace, #318)

**Interfaces:**
- Consumes: `AnswerFeedback`, `NoAnswerFeedback` (`tutoring/ports/answer_feedback.py`); `langfuse_enabled(settings)` (`shared/adapters/tracing.py`); `Settings.langfuse_url`, `langfuse_public_key`, `langfuse_secret_key`, `deployment`; `Rating` (`tutoring/domain/turn.py`); `RunId`.
- Produces: `LangfuseAnswerFeedback(client, environment, executor=None, waits=SHOW_WAITS, sleep=None)`, `answer_feedback(settings) -> AnswerFeedback`, `SCORE_NAME = "learner_rating"`; test fakes `FakeLangfuse`, `InlineExecutor`.

- [ ] **Step 1: Move `InlineExecutor`.** Create `backend/tests/fakes/executor.py` with the `InlineExecutor` class exactly as it is in `fakes/phoenix.py` (with its imports). Keep `fakes/phoenix.py` for now; Step 7 deletes it.

- [ ] **Step 2: Write the fake Langfuse** `backend/tests/fakes/langfuse.py`:

```python
"""Langfuse 4.47's score endpoints in memory, for the rating adapter (as read from its source for #318, events_only
mode): POST /api/public/scores answers 200 with the id and queues the score, which shows in GET /api/public/v3/scores
only after `lag` more list calls; it never checks the trace. DELETE /api/public/scores/{id} answers 202 and removes
only a score that already shows: a delete that arrives first is lost, as in Langfuse. The v3 list is strict (an unknown
parameter is 400) and pages by cursor. GET /api/public/score-configs pages by page/limit. Every call needs the key
pair as Basic auth."""

import base64
import json
import uuid
from collections.abc import Iterable
from typing import Any

import httpx

PUBLIC_KEY = "pk-lf-test"
SECRET_KEY = "sk-lf-test"
V3_PARAMS = {"traceId", "name", "limit", "cursor", "fields", "id", "environment", "dataType"}


class FakeLangfuse:
    def __init__(
        self,
        configs: Iterable[dict[str, Any]] = (),
        lag: int = 0,
        down: bool = False,
        page_size: int = 100,
    ) -> None:
        self.configs = list(configs)  # {id, name, dataType, isArchived}
        self.lag = lag  # list calls a new score stays hidden for
        self.down = down
        self.page_size = page_size  # the v3 list's page size, whatever limit asks (to test paging)
        self.scores: dict[str, dict[str, Any]] = {}  # id -> score as listed (shown or not)
        self.hidden: dict[str, int] = {}  # id -> list calls left before it shows
        self.requests: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def client(self) -> httpx.Client:
        return httpx.Client(base_url="http://langfuse.test", transport=self.transport, auth=(PUBLIC_KEY, SECRET_KEY))

    def config(self, name: str = "learner_rating", data_type: str = "BOOLEAN", archived: bool = False) -> str:
        config_id = str(uuid.uuid4())
        self.configs.append({"id": config_id, "name": name, "dataType": data_type, "isArchived": archived})
        return config_id

    def seed(self, trace_id: str, value: bool = True, name: str = "learner_rating") -> str:
        """A score that already shows, e.g. posted by an earlier API process."""
        score_id = str(uuid.uuid4())
        self.scores[score_id] = _listed(score_id, trace_id, name, value, "local")
        return score_id

    def shown(self, trace_id: str, name: str = "learner_rating") -> list[dict[str, Any]]:
        """The scores a reader sees now, oldest first; doesn't advance the lag."""
        return [
            s for i, s in self.scores.items() if i not in self.hidden and s["traceId"] == trace_id and s["name"] == name
        ]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        expected = "Basic " + base64.b64encode(f"{PUBLIC_KEY}:{SECRET_KEY}".encode()).decode()
        if request.headers.get("authorization") != expected:
            return httpx.Response(401, json={"message": "Invalid credentials"})
        path, method = request.url.path, request.method
        if method == "POST" and path == "/api/public/scores":
            return self._post(json.loads(request.content))
        if method == "DELETE" and path.startswith("/api/public/scores/"):
            score_id = path.removeprefix("/api/public/scores/")
            if score_id not in self.hidden:  # a delete before ingestion is lost
                self.scores.pop(score_id, None)
            return httpx.Response(202, json={"message": "Score deletion queued successfully"})
        if method == "GET" and path == "/api/public/v3/scores":
            return self._list(request.url.params)
        if method == "GET" and path == "/api/public/score-configs":
            return self._configs(request.url.params)
        return httpx.Response(404, json={"message": "not found"})

    def _post(self, body: dict[str, Any]) -> httpx.Response:
        if body.get("dataType") != "BOOLEAN" or body.get("value") not in (0, 1) or not body.get("traceId"):
            return httpx.Response(400, json={"message": "invalid score"})
        score_id = body.get("id") or str(uuid.uuid4())
        score = _listed(score_id, body["traceId"], body["name"], body["value"] == 1, body.get("environment", "default"))
        score["configId"] = body.get("configId")
        self.scores[score_id] = score
        if self.lag:
            self.hidden[score_id] = self.lag
        return httpx.Response(200, json={"id": score_id})

    def _list(self, params: httpx.QueryParams) -> httpx.Response:
        if set(params) - V3_PARAMS or int(params.get("limit", "50")) > 100:
            return httpx.Response(400, json={"message": "invalid query"})
        for score_id in list(self.hidden):  # each list call brings queued scores one step closer to showing
            self.hidden[score_id] -= 1
            if self.hidden[score_id] <= 0:
                del self.hidden[score_id]
        matches = [
            s
            for i, s in self.scores.items()
            if i not in self.hidden
            and s["traceId"] == params.get("traceId", s["traceId"])
            and s["name"] == params.get("name", s["name"])
        ]
        start = int(params.get("cursor", "0"))
        page = matches[start : start + self.page_size]
        meta: dict[str, Any] = {"limit": int(params.get("limit", "50"))}
        if start + self.page_size < len(matches):
            meta["cursor"] = str(start + self.page_size)
        return httpx.Response(200, json={"data": page, "meta": meta})

    def _configs(self, params: httpx.QueryParams) -> httpx.Response:
        page, limit = int(params.get("page", "1")), int(params.get("limit", "50"))
        if limit > 100:
            return httpx.Response(400, json={"message": "invalid query"})
        size = min(limit, self.page_size)
        data = self.configs[(page - 1) * size : page * size]
        pages = max(1, -(-len(self.configs) // size))
        return httpx.Response(
            200,
            json={"data": data, "meta": {"page": page, "limit": limit, "totalItems": len(self.configs), "totalPages": pages}},
        )


def _listed(score_id: str, trace_id: str, name: str, value: bool, environment: str) -> dict[str, Any]:
    return {"id": score_id, "traceId": trace_id, "name": name, "value": value, "dataType": "BOOLEAN", "environment": environment}
```

Export `FakeLangfuse` (and `InlineExecutor` from `fakes.executor`) in `fakes/__init__.py` and its `__all__`.

- [ ] **Step 3: Write the failing tests** `backend/tests/unit/tutoring/test_langfuse_feedback.py`:

```python
import json
import logging
import threading
import time
import uuid

import httpx
import pytest
from pydantic import SecretStr

from fakes import FakeLangfuse, InlineExecutor
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.adapters.langfuse_feedback import LangfuseAnswerFeedback, answer_feedback
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import NoAnswerFeedback

RUN = RunId(str(uuid.uuid4()))
TRACE = uuid.UUID(RUN).hex


def feedback(
    langfuse: FakeLangfuse, waits: tuple[float, ...] = (1.0, 2.0)
) -> tuple[LangfuseAnswerFeedback, list[float]]:
    slept: list[float] = []
    sender = LangfuseAnswerFeedback(
        langfuse.client(), "local", executor=InlineExecutor(), waits=waits, sleep=slept.append
    )
    return sender, slept


def values(langfuse: FakeLangfuse, trace: str = TRACE) -> list[bool]:
    return [s["value"] for s in langfuse.shown(trace)]


def posts(langfuse: FakeLangfuse) -> list[dict[str, object]]:
    return [json.loads(r.content) for r in langfuse.requests if r.method == "POST"]


def warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_rating_is_a_boolean_learner_rating_score_on_the_runs_trace() -> None:
    langfuse = FakeLangfuse()
    config = langfuse.config()
    feedback(langfuse)[0].send(RUN, Rating.UP)
    [body] = posts(langfuse)
    assert uuid.UUID(str(body.pop("id")))  # a new id per rating
    assert body == {
        "traceId": TRACE,
        "name": "learner_rating",
        "value": 1,
        "dataType": "BOOLEAN",
        "environment": "local",
        "configId": config,
    }
    assert values(langfuse) == [True]


def test_a_not_helpful_rating_scores_zero() -> None:
    langfuse = FakeLangfuse()
    langfuse.config()
    feedback(langfuse)[0].send(RUN, Rating.DOWN)
    assert [p["value"] for p in posts(langfuse)] == [0] and values(langfuse) == [False]


def test_a_rating_before_its_trace_arrives_is_sent_once_without_waiting(caplog: pytest.LogCaptureFixture) -> None:
    # Langfuse stores a score whatever its trace: the fake has no traces at all, as when the ask's trace is still
    # in the agent's export batch.
    langfuse = FakeLangfuse(lag=1)
    langfuse.config()
    sender, slept = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    assert len(posts(langfuse)) == 1 and slept == [] and not warnings(caplog)


def test_a_new_rating_replaces_the_earlier_one() -> None:
    langfuse = FakeLangfuse()
    langfuse.config()
    sender, _ = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    assert values(langfuse) == [False]
    first, second = (p["id"] for p in posts(langfuse))
    assert first != second  # never one reused id (ADR 0023 §6)


def test_a_quick_change_waits_for_the_earlier_score_to_show_before_deleting_it() -> None:
    langfuse = FakeLangfuse(lag=3)
    langfuse.config()
    sender, slept = feedback(langfuse, waits=(1.0, 2.0, 4.0))
    sender.send(RUN, Rating.UP)  # its list call: the 👍 is still queued (2 calls left)
    sender.send(RUN, Rating.DOWN)
    assert slept == [1.0]  # hidden on the first list, shown on the second
    reader = langfuse.client()
    while langfuse.hidden:  # let the 👎 finish ingesting (each list call advances the queue)
        reader.get("/api/public/v3/scores")
    assert values(langfuse) == [False]


def test_an_earlier_score_that_never_shows_is_a_warning_and_the_new_one_stays(
    caplog: pytest.LogCaptureFixture,
) -> None:
    langfuse = FakeLangfuse(lag=10)
    langfuse.config()
    sender, slept = feedback(langfuse, waits=(1.0, 2.0))
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    assert slept == [1.0, 2.0]
    [record] = warnings(caplog)
    assert record.levelno == logging.WARNING and RUN in record.getMessage()
    assert not [r for r in langfuse.requests if r.method == "DELETE"]


def test_scores_left_by_an_earlier_process_are_deleted_without_waiting_across_pages() -> None:
    langfuse = FakeLangfuse(page_size=2)
    langfuse.config()
    for _ in range(3):
        langfuse.seed(TRACE, value=True)
    sender, slept = feedback(langfuse)
    sender.send(RUN, Rating.DOWN)
    assert values(langfuse) == [False] and slept == []


def test_clearing_deletes_only_this_runs_learner_ratings() -> None:
    other = RunId(str(uuid.uuid4()))
    langfuse = FakeLangfuse()
    langfuse.config()
    judge = langfuse.seed(TRACE, name="answer_relevance")
    sender, _ = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    sender.send(other, Rating.DOWN)
    sender.clear(RUN)
    assert values(langfuse) == [] and values(langfuse, uuid.UUID(other).hex) == [False]
    assert judge in langfuse.scores  # another score on the same trace stays


def test_clearing_right_after_rating_waits_for_the_rating_to_show() -> None:
    langfuse = FakeLangfuse(lag=2)
    langfuse.config()
    sender, slept = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    sender.clear(RUN)
    assert langfuse.scores == {} and slept == []  # hidden for one list call, shown on the clear's first


def test_clearing_a_run_never_rated_deletes_nothing(caplog: pytest.LogCaptureFixture) -> None:
    langfuse = FakeLangfuse()
    sender, slept = feedback(langfuse)
    sender.clear(RUN)
    assert not [r for r in langfuse.requests if r.method == "DELETE"] and slept == [] and not warnings(caplog)


def test_the_score_config_is_looked_up_once() -> None:
    langfuse = FakeLangfuse()
    langfuse.config()
    sender, _ = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    assert len([r for r in langfuse.requests if r.url.path == "/api/public/score-configs"]) == 1


def test_the_config_is_found_on_a_later_page() -> None:
    langfuse = FakeLangfuse(page_size=2)
    langfuse.config(name="answer_relevance", data_type="NUMERIC")
    langfuse.config(name="faithfulness", data_type="NUMERIC")
    config = langfuse.config()
    feedback(langfuse)[0].send(RUN, Rating.UP)
    assert posts(langfuse)[0]["configId"] == config


@pytest.mark.parametrize(
    "config",
    [None, {"data_type": "NUMERIC"}, {"archived": True}],
    ids=["missing", "not-boolean", "archived"],
)
def test_without_a_usable_config_the_score_goes_unchecked_with_one_warning(
    config: dict[str, object] | None, caplog: pytest.LogCaptureFixture
) -> None:
    langfuse = FakeLangfuse()
    if config is not None:
        langfuse.config(**config)  # type: ignore[arg-type]
    sender, _ = feedback(langfuse)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    assert ["configId" in p for p in posts(langfuse)] == [False, False]
    assert values(langfuse) == [False]
    [record] = warnings(caplog)
    assert "learner_rating" in record.getMessage() and "score config" in record.getMessage()


def test_ratings_and_a_clear_apply_in_the_order_given_even_while_scores_lag() -> None:
    langfuse = FakeLangfuse(lag=2)
    langfuse.config()
    sender, _ = feedback(langfuse, waits=(1.0, 2.0, 4.0))
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    sender.clear(RUN)
    assert langfuse.scores == {}


def test_an_unreachable_langfuse_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    sender, slept = feedback(FakeLangfuse(down=True))
    sender.send(RUN, Rating.UP)
    sender.clear(RUN)
    errors = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert len(errors) == 2 and all(RUN in m and "ConnectError" in m for m in errors)
    assert errors[1].startswith("clearing the rating of run")
    assert slept == []


def test_a_refused_key_is_logged_with_its_status(caplog: pytest.LogCaptureFixture) -> None:
    refusing = httpx.Client(
        base_url="http://langfuse.test", transport=httpx.MockTransport(lambda r: httpx.Response(401))
    )
    LangfuseAnswerFeedback(refusing, "local", executor=InlineExecutor(), sleep=lambda s: None).send(RUN, Rating.UP)
    [message] = [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]
    assert "401" in message and RUN in message


def test_the_send_runs_off_the_callers_thread() -> None:
    release = threading.Event()
    langfuse = FakeLangfuse()

    def held(request: httpx.Request) -> httpx.Response:
        release.wait(timeout=10)
        return langfuse.transport.handle_request(request)

    client = httpx.Client(
        base_url="http://langfuse.test", transport=httpx.MockTransport(held), auth=langfuse.client().auth
    )
    sender = LangfuseAnswerFeedback(client, "local")
    sender.send(RUN, Rating.UP)
    assert langfuse.scores == {}  # send returned while the request is still held back
    release.set()
    sender.close()
    assert len(langfuse.scores) == 1


def test_close_stops_a_wait_in_progress_at_once(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    langfuse = FakeLangfuse(lag=100)
    langfuse.config()
    listed = threading.Event()

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/public/v3/scores" and len(langfuse.scores) == 2:
            listed.set()
        return langfuse.transport.handle_request(request)

    client = httpx.Client(
        base_url="http://langfuse.test", transport=httpx.MockTransport(handle), auth=langfuse.client().auth
    )
    sender = LangfuseAnswerFeedback(client, "local")  # the production waits
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)  # waits for the 👍 to show, which it never does
    assert listed.wait(timeout=5)
    time.sleep(0.1)  # the worker is now in its first wait
    started = time.monotonic()
    sender.close()
    assert time.monotonic() - started < 2
    assert not warnings(caplog)
    assert any(r.levelno == logging.INFO and RUN in r.getMessage() for r in caplog.records)


def test_close_cancels_ratings_not_yet_started(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    release = threading.Event()
    started = threading.Event()
    langfuse = FakeLangfuse()
    langfuse.config()

    def held(request: httpx.Request) -> httpx.Response:
        started.set()
        release.wait(timeout=10)
        return langfuse.transport.handle_request(request)

    client = httpx.Client(
        base_url="http://langfuse.test", transport=httpx.MockTransport(held), auth=langfuse.client().auth
    )
    sender = LangfuseAnswerFeedback(client, "local")
    sender.send(RUN, Rating.UP)
    assert started.wait(timeout=5)  # the first is running, held in its request
    queued = RunId(str(uuid.uuid4()))
    sender.send(queued, Rating.DOWN)
    closer = threading.Thread(target=sender.close)
    closer.start()
    time.sleep(0.1)
    release.set()
    closer.join(timeout=5)
    assert not closer.is_alive()
    assert {s["traceId"] for s in langfuse.scores.values()} <= {TRACE}  # the queued one was never sent
    assert any(r.levelno == logging.INFO and queued in r.getMessage() for r in caplog.records)


def test_close_closes_the_client() -> None:
    client = FakeLangfuse().client()
    LangfuseAnswerFeedback(client, "local").close()
    assert client.is_closed


def test_answer_feedback_sends_with_the_projects_key_pair_and_the_deployment() -> None:
    settings = Settings(
        langfuse_url="https://langfuse.example/",
        langfuse_public_key=SecretStr("pk-lf-1"),
        langfuse_secret_key=SecretStr("sk-lf-1"),
        deployment="on-premise",
    )
    sender = answer_feedback(settings)
    assert isinstance(sender, LangfuseAnswerFeedback)
    assert sender.environment == "on-premise"
    assert str(sender.client.base_url).rstrip("/") == "https://langfuse.example"
    request = sender.client.build_request("GET", "/api/public/v3/scores")
    request = next(sender.client.auth.auth_flow(request))
    assert request.headers["authorization"] == httpx.BasicAuth("pk-lf-1", "sk-lf-1")._auth_header
    sender.close()


@pytest.mark.parametrize(
    "settings",
    [
        Settings(langfuse_url=""),
        Settings(langfuse_url="https://langfuse.example", langfuse_public_key=SecretStr("pk")),
        Settings(langfuse_url="https://langfuse.example", langfuse_secret_key=SecretStr("sk")),
    ],
    ids=["no-url", "no-secret-key", "no-public-key"],
)
def test_answer_feedback_is_off_without_langfuse(settings: Settings) -> None:
    assert isinstance(answer_feedback(settings), NoAnswerFeedback)


def test_phoenix_alone_sends_no_ratings() -> None:
    settings = Settings(phoenix_url="http://phoenix:6006", phoenix_api_key=SecretStr("k"), deployment="on-premise")
    assert isinstance(answer_feedback(settings), NoAnswerFeedback)
```

If `httpx.BasicAuth._auth_header` is not available in the installed httpx, compare against `"Basic " + base64.b64encode(b"pk-lf-1:sk-lf-1").decode()` instead.

- [ ] **Step 4: Run them to verify they fail.** `cd backend && uv run pytest tests/unit/tutoring/test_langfuse_feedback.py -q` → ImportError (`langfuse_feedback` doesn't exist).

- [ ] **Step 5: Write the adapter** `backend/src/smart_tutor/tutoring/adapters/langfuse_feedback.py`:

```python
"""Learner ratings as Langfuse scores on the ask's trace (PRD §10.2, ADR 0023 §6), so LLM judges can be calibrated
against them. Each rating is a new `learner_rating` BOOLEAN score (1 up, 0 down) on the trace whose id is the run id,
with the deployment as its environment and, when the project has one, the `learner_rating` score config's id (Langfuse
checks a score against a config only by id). Then the trace's other `learner_rating` scores are deleted, so the new one
replaces them; clearing deletes them all. Langfuse stores a score whatever its trace, so a rating that arrives before
the ask's trace is simply sent. But it ingests a score a few seconds after answering, and a delete that arrives first
removes nothing: so before deleting, the adapter waits until the list shows the score this process last posted for
the run. Sent off the request on one background thread, in the order rated: a slow or unreachable Langfuse never
delays or fails the rating, which is already saved with the turn. A failure is logged. `close()` (API shutdown) stops
the waits and drops the requests not yet started. The score says only the rating: no user id, email, name, or token
(PRD §10.4)."""

import logging
import threading
import uuid
from collections import OrderedDict
from collections.abc import Callable, Sequence
from concurrent.futures import Executor, Future, ThreadPoolExecutor
from typing import Any

import httpx

from smart_tutor.shared.adapters.tracing import langfuse_enabled
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import AnswerFeedback, NoAnswerFeedback

logger = logging.getLogger(__name__)

SCORE_NAME = "learner_rating"
SCORES_PATH = "/api/public/scores"
# The list that works on a v4 host in events_only mode; the v1 and v2 lists answer 404 there.
SCORES_LIST_PATH = "/api/public/v3/scores"
SCORE_CONFIGS_PATH = "/api/public/score-configs"
PAGE_LIMIT = 100  # the most either list returns per page
# Langfuse ingests a score 5 s (15 s around 00:00 UTC) after its POST, plus processing. Before deleting the score this
# process last posted for a run, wait for it to show, after these waits (61 s in all).
SHOW_WAITS = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
REQUEST_TIMEOUT_SECONDS = 10.0
REMEMBERED_RUNS = 1024  # runs whose last score id is kept; older ones have long been ingested


class _Stopped(Exception):
    """The adapter is closing: a wait gives up without another request."""


class LangfuseAnswerFeedback(AnswerFeedback):
    def __init__(
        self,
        client: httpx.Client,
        environment: str,
        executor: Executor | None = None,
        waits: Sequence[float] = SHOW_WAITS,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.client = client
        self.environment = environment
        # One worker: requests go in the order the learner rated, so the last rating is the one left. Only it touches
        # the state below.
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="answer-feedback")
        self._waits = tuple(waits)
        self._stopping = threading.Event()
        self._sleep = sleep or self._stopping.wait  # an injected sleep is for tests; this one wakes at close()
        self._posted: OrderedDict[RunId, str] = OrderedDict()  # run -> the score id this process last posted
        self._config_id: str | None = None
        self._warned_no_config = False

    def send(self, run_id: RunId, rating: Rating) -> None:
        self._submit("sending", self._score, run_id, rating)

    def clear(self, run_id: RunId) -> None:
        self._submit("clearing", self._clear, run_id)

    def close(self) -> None:
        """Process shutdown: stop the wait in progress, drop the requests not yet started, close the client."""
        self._stopping.set()
        self._executor.shutdown(wait=True, cancel_futures=True)
        self.client.close()

    def _submit(self, action: str, call: Callable[..., None], run_id: RunId, *args: object) -> None:
        self._executor.submit(call, run_id, *args).add_done_callback(lambda done: _log_failure(done, action, run_id))

    def _score(self, run_id: RunId, rating: Rating) -> None:
        earlier = self._posted.pop(run_id, None)
        score_id = str(uuid.uuid4())
        body: dict[str, Any] = {
            "id": score_id,
            "traceId": uuid.UUID(run_id).hex,
            "name": SCORE_NAME,
            "value": 1 if rating is Rating.UP else 0,
            "dataType": "BOOLEAN",
            "environment": self.environment,
        }
        if config_id := self._config():
            body["configId"] = config_id
        self.client.post(SCORES_PATH, json=body).raise_for_status()
        self._posted[run_id] = score_id
        while len(self._posted) > REMEMBERED_RUNS:
            self._posted.popitem(last=False)
        self._delete_others(run_id, keep=score_id, earlier=earlier)

    def _clear(self, run_id: RunId) -> None:
        self._delete_others(run_id, keep=None, earlier=self._posted.pop(run_id, None))

    def _delete_others(self, run_id: RunId, keep: str | None, earlier: str | None) -> None:
        """Delete the trace's learner_rating scores but `keep`, once `earlier` (the score this process last posted for
        the run, still maybe queued) shows; a delete sent before it shows would be lost."""
        for wait in (*self._waits, None):
            if self._stopping.is_set():
                raise _Stopped
            shown = self._score_ids(run_id)
            if earlier is None or earlier in shown:
                break
            if wait is None:
                logger.warning(
                    "the earlier rating of run %s never showed in Langfuse; it may stay beside the new one", run_id
                )
                break
            self._sleep(wait)
        for score_id in shown - {keep}:
            self.client.delete(f"{SCORES_PATH}/{score_id}").raise_for_status()

    def _score_ids(self, run_id: RunId) -> set[str]:
        params = {"traceId": uuid.UUID(run_id).hex, "name": SCORE_NAME, "limit": str(PAGE_LIMIT)}
        ids: set[str] = set()
        while True:
            response = self.client.get(SCORES_LIST_PATH, params=params)
            response.raise_for_status()
            page = response.json()
            ids |= {score["id"] for score in page["data"]}
            cursor = page.get("meta", {}).get("cursor")
            if not cursor:
                return ids
            params["cursor"] = cursor

    def _config(self) -> str | None:
        """The project's learner_rating BOOLEAN config, looked up until found; None (and one warning) without it."""
        if self._config_id is None:
            page = 1
            while True:
                response = self.client.get(SCORE_CONFIGS_PATH, params={"page": page, "limit": PAGE_LIMIT})
                response.raise_for_status()
                found = response.json()
                for config in found["data"]:
                    if config["name"] == SCORE_NAME and config["dataType"] == "BOOLEAN" and not config["isArchived"]:
                        self._config_id = config["id"]
                        return self._config_id
                if page >= found["meta"]["totalPages"]:
                    break
                page += 1
            if not self._warned_no_config:
                self._warned_no_config = True
                logger.warning(
                    "the Langfuse project has no %s BOOLEAN score config; ratings are sent unchecked", SCORE_NAME
                )
        return self._config_id


def _log_failure(done: "Future[None]", action: str, run_id: RunId) -> None:
    if done.cancelled():
        logger.info("the rating of run %s was not sent: the API is stopping", run_id)
        return
    error = done.exception()
    if error is None:
        return
    if isinstance(error, _Stopped):
        logger.info("the rating of run %s was not sent: the API is stopping", run_id)
    elif isinstance(error, httpx.HTTPStatusError):
        logger.error("%s the rating of run %s to Langfuse failed (%s)", action, run_id, error.response.status_code)
    else:
        logger.error("%s the rating of run %s to Langfuse failed (%s)", action, run_id, type(error).__name__)


def answer_feedback(settings: Settings) -> AnswerFeedback:
    """Scores into the environment's Langfuse project while Langfuse tracing is on (same URL and key pair as its
    traces); else none."""
    if not langfuse_enabled(settings):
        return NoAnswerFeedback()
    client = httpx.Client(
        base_url=settings.langfuse_url.rstrip("/"),
        auth=(settings.langfuse_public_key.get_secret_value(), settings.langfuse_secret_key.get_secret_value()),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    return LangfuseAnswerFeedback(client, settings.deployment)
```

Note on `test_close_stops_a_wait_in_progress_at_once`: the stop check sits at the top of the loop, so after `close()` wakes the wait, the next iteration raises `_Stopped` before another request. If a test's arithmetic about `lag`, list calls, and `slept` disagrees with the fake (each GET of the v3 list advances every queued score by one), fix the test's numbers to match the fake's documented behavior, not the adapter.

- [ ] **Step 6: Run the tests.** `cd backend && uv run pytest tests/unit/tutoring/test_langfuse_feedback.py -q` → all pass.

- [ ] **Step 7: Switch the API and the no-token test; delete Phoenix's rating adapter.**
  - `apps/api/services.py`: `from smart_tutor.tutoring.adapters.langfuse_feedback import answer_feedback`.
  - `tests/unit/apps/agent/test_no_token_in_traces.py` `rated_requests`: build `langfuse = FakeLangfuse(); langfuse.config()` and `sender = LangfuseAnswerFeedback(langfuse.client(), "local", executor=InlineExecutor(), sleep=lambda s: None)`; drop the `phoenix.spans.add(...)` line (Langfuse needs no trace); assert `rated.status_code == 200 and langfuse.scores`; dump `langfuse.requests`. Rename the docstring to say Langfuse. In `test_the_rating_annotation_holds_no_token_user_id_or_email` (rename to `test_the_rating_score_holds_no_token_user_id_or_email`) the positive control becomes `assert "learner_rating" in sent and "Basic " in sent`. Remove the now-unused `root_span_id` import if nothing else in the file uses it.
  - Delete `tutoring/adapters/phoenix_feedback.py`, `tests/unit/tutoring/test_phoenix_feedback.py`, `tests/fakes/phoenix.py`; drop `FakePhoenix` from `fakes/__init__.py`. `grep -rn "phoenix_feedback\|FakePhoenix\|PhoenixAnswerFeedback" backend` → nothing.
  - Port docstring (`ports/answer_feedback.py` line 1): `"""Learner ratings sent on to where answers are traced (PRD §10.2): Langfuse scores on the ask's trace (ADR 0023)."""`
  - `routes/threads.py`: replace "sent to Phoenix as a `learner_rating` span annotation on the ask's trace" (module docstring and `rate_turn` docstring) with "sent to Langfuse as a `learner_rating` score on the ask's trace"; the `run_id` field description: "The ask's trace id in Langfuse, for attaching a rating (#227); null for turns kept before it was recorded." Then regenerate the client: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`.
  - `tutoring/README.md`: replace "The API wires `PhoenixAnswerFeedback` (`answer_feedback(settings)`, #290), which sends the rating to Phoenix as a `learner_rating` annotation on the turn's root span (`NoAnswerFeedback` when tracing is off)." with "The API wires `LangfuseAnswerFeedback` (`answer_feedback(settings)`, #318), which sends the rating to Langfuse as a `learner_rating` BOOLEAN score on the turn's trace and deletes the trace's earlier ones (`NoAnswerFeedback` without the Langfuse URL and keys)."

- [ ] **Step 8: Full backend checks.** `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest` → all pass (run `uv run ruff format .` first if formatting differs).

- [ ] **Step 9: Commit.**

```bash
git add backend web/src/api
git commit -m "Send learner ratings to Langfuse as scores (#318)" -m "ADR 0023 §6: ratings move from Phoenix span annotations to a learner_rating BOOLEAN score on the ask's Langfuse trace. Langfuse stores a score before its trace, so no retry; but it ingests scores a few seconds late and a delete that arrives first is lost, so the adapter waits for its earlier score to show before deleting it." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The on-premise and local API get the Langfuse settings instead of Phoenix's

**Files:**
- Modify: `deploy/on-premise/compose.yaml` (`api` service environment, ~L162–166)
- Modify: `compose.yaml` (`api` service, ~L116)
- Test: `infra/tests/test_host.py` (~L1086–1095 and ~L1230–1233)

**Interfaces:**
- Consumes: `answer_feedback(settings)` from Task 1 reads `SMART_TUTOR_LANGFUSE_URL`, `SMART_TUTOR_LANGFUSE_PUBLIC_KEY`, `SMART_TUTOR_LANGFUSE_SECRET_KEY`, `SMART_TUTOR_DEPLOYMENT`. `deploy.sh` already renders `LANGFUSE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` (#316).
- Produces: nothing new for later tasks.

- [ ] **Step 1: Failing tests** in `infra/tests/test_host.py`:
  - Replace `test_the_api_sends_ratings_to_the_on_premise_phoenix` with:

```python
def test_the_api_sends_ratings_to_the_on_premise_langfuse_project(compose: dict[str, Any]) -> None:
    env = compose["services"]["api"]["environment"]
    assert env["SMART_TUTOR_DEPLOYMENT"] == "on-premise"  # the scores' environment
    agent_env = compose["services"]["agent"]["environment"]
    for name in ("SMART_TUTOR_LANGFUSE_URL", "SMART_TUTOR_LANGFUSE_PUBLIC_KEY", "SMART_TUTOR_LANGFUSE_SECRET_KEY"):
        assert env[name] == agent_env[name]  # the agent's project: ratings land on its traces
    assert not [k for k in env if k.startswith("SMART_TUTOR_PHOENIX_")]  # ratings left Phoenix (#318)
    assert not [k for k in env if k.startswith("LANGSMITH_")]
```

  - `test_only_the_agent_and_worker_get_langfuse_settings`: parametrize over `["mcp"]` only and rename it `test_the_mcp_server_gets_no_langfuse_settings`; drop the `# the API gets them in #318` comment.
  - Run `cd infra && uv run pytest tests/test_host.py -q` → the new API test fails.

- [ ] **Step 2: Change the Compose files.**
  - `deploy/on-premise/compose.yaml`, `api.environment`: replace the comment and the three `SMART_TUTOR_PHOENIX_*` lines with

```yaml
      # Ratings go to Langfuse as learner_rating scores on the agent's ask traces (#318, ADR 0023); none until the
      # project's keys exist.
      SMART_TUTOR_LANGFUSE_URL: ${LANGFUSE_URL:?}
      SMART_TUTOR_LANGFUSE_PUBLIC_KEY: ${LANGFUSE_PUBLIC_KEY}
      SMART_TUTOR_LANGFUSE_SECRET_KEY: ${LANGFUSE_SECRET_KEY}
```

  - `compose.yaml`, `api.environment`: delete the line `SMART_TUTOR_PHOENIX_URL: http://phoenix:6006  # ratings as annotations …`. The API reads the Langfuse URL and the developer's key pair from `.env` (`env_file`), which already reaches the shared host.
  - Check nothing else asserts the API's Phoenix variables: `grep -rn "api" infra/tests/test_host.py | grep -i phoenix` and `infra/tests/test_workflows.py` (the CI override blanks `SMART_TUTOR_LANGFUSE_URL` for the api already; keep it).

- [ ] **Step 3: Run** `cd infra && uv run pytest -q` → all pass.

- [ ] **Step 4: Commit.**

```bash
git add deploy/on-premise/compose.yaml compose.yaml infra/tests/test_host.py
git commit -m "Give the API the Langfuse settings instead of Phoenix's (#318)" -m "Ratings now go to the environment's Langfuse project, the one the agent traces into, so the API needs its URL and key pair and no longer Phoenix's." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The pilot smoke test checks the trace and the rating in Langfuse

**Files:**
- Modify: `deploy/pilot/smoke_test.py` (module docstring L1–28; `_phoenix`, `check_trace`, `check_rating`, `main`)
- Test: `infra/tests/test_smoke_test.py` (fake pilot: replace the `/phoenix/...` routes with a fake Langfuse host; the trace and rating test sections from ~L679)

**Interfaces:**
- Consumes: the ask's run id from `GET /api/threads/{thread}/turns`, as now. Langfuse endpoints as in "What Langfuse 4.47.0 actually does".
- Produces: CLI `--trace-project <project>` (kept), env `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` (the names the Langfuse SDK and our evals use). Output lines `ask trace <run id> is in <project>` and `rating of <run id> is in <project>` (unchanged).

Behavior (replace Phoenix's):
- `main`: `--trace-project` still needs `--end-to-end`. It now needs `LANGFUSE_BASE_URL`, `LANGFUSE_PUBLIC_KEY`, and `LANGFUSE_SECRET_KEY`; a missing one prints `--trace-project needs LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in the environment` (naming exactly the missing ones is fine too) and returns 1. `trace = (args.trace_project, base_url, public_key, secret_key)`. No key is ever printed.
- `_langfuse(s, path, langfuse)`: `GET <base_url><path>` with `authorization: Basic base64(public:secret)` only, never the learner's bearer token (same shape as `_phoenix`, which goes).
- `check_trace` (signature `check_trace(s, run, langfuse: _Langfuse, username) -> str` where `_Langfuse` is a small frozen dataclass `(project, base_url, public_key, secret_key)`):
  1. **The key's project:** `GET /api/public/projects`; 401/403 → `SmokeTestError("trace: Langfuse refused the key pair")`; `data[0].name != project` → `SmokeTestError(f"trace: the Langfuse key belongs to project {name!r}, not {project!r}")`.
  2. Read the run id from the turns as now; `run.ask_run_id = run_id`.
  3. Poll `GET /api/public/v2/observations?traceId=<run hex>&fields=core,basic,io,metadata&expandMetadata=<comma-joined TRACE_METADATA>&limit=1000` until an item has `name == "ask"` and `parentObservationId is None`. 401/403 → refused; other non-200 → remember as `last_other`. On the deadline: if observations of the trace appeared but no `ask` root, `"trace: run {run_id} reached Langfuse but its ask observation never arrived{tail}"`; else `"trace: run {run_id} never reached Langfuse (is tracing on, with the keys <prefix>/langfuse/public-key and secret-key, and the sampling rate trace-sampling-rate 1?){tail}"`.
  4. The root's `id` must equal the run id's low 64 bits as 16 hex (`"trace: the root observation's id … is not the run id's low 64 bits (…)"`).
  5. Its `metadata` must hold every `TRACE_METADATA` key (`"trace: the ask trace lacks metadata …"`), and `metadata["thread_id"] == run.thread_id` (`"trace: the ask trace belongs to another thread"`). Its `sessionId` must equal the thread id too (`"trace: the ask trace's session is not its thread"`).
  6. The token / username / user-id leak checks run over `json.dumps(observations)` exactly as now.
  7. Remember the root's `environment` on `run` (new field `ask_environment: str | None = None` on `_Run`) for the rating check. Return `f"ask trace {run_id} is in {project}"`.
- `check_rating(s, run, langfuse) -> str`: PUT the rating `up` as now. Poll `GET /api/public/v3/scores?traceId=<hex>&name=learner_rating&fields=details&limit=100` until `data` is non-empty (401/403 → `"rating: Langfuse refused the key pair"`). On the deadline: `"rating: run {run_id}'s rating never reached Langfuse (does the API have the Langfuse settings, and does the project have the learner_rating score config?)"`. Then take the newest by `timestamp` and require `dataType == "BOOLEAN"`, `value is True`, `environment == run.ask_environment`, and a non-empty `configId`; otherwise `f"rating: the score is not a BOOLEAN true in environment {run.ask_environment!r} with the learner_rating config: {score!r}"`. Return `f"rating of {run_id} is in {project}"`.
- Docstring: rewrite the `--trace-project` paragraph and the usage line (`LANGFUSE_BASE_URL=... LANGFUSE_PUBLIC_KEY=... LANGFUSE_SECRET_KEY=... SMOKE_TEST_USERNAME=... …`): it checks the key belongs to that Langfuse project, waits for the trace's `ask` root observation (id = run id's low 64 bits) with the PRD §10.4 metadata and the thread as its session, holding neither the token, the username, nor the user id; then rates the turn up and waits for a `learner_rating` BOOLEAN `true` score with the project's score config and the trace's environment (#318). The keys are never printed. Keep "Standard library only."

- [ ] **Step 1: Rework the fake pilot** in `infra/tests/test_smoke_test.py`: replace `PHOENIX_KEY` with `LANGFUSE_PUBLIC`/`LANGFUSE_SECRET` test values; replace `_ask_span` with `_ask_observation(run_id, thread_id)` returning `{"id": <low 64 bits hex>, "traceId": <hex>, "parentObservationId": None, "name": "ask", "type": "CHAIN", "environment": "on-premise", "userId": "ab"*32, "sessionId": thread_id, "input": "{\"question\": \"…\"}", "output": "…", "metadata": {"deployment": "on-premise", "chat_model": "m", "embedding_model": "e", "thread_id": thread_id, "learner_hash": "ab"*32, "limited": "false", "decline": "none", "chunks": "2"}}` (keep whatever keys `TRACE_METADATA` lists); replace `_phoenix` routing (`/phoenix/…`) with `_langfuse` routing under `/langfuse/…` for `GET /langfuse/api/public/projects` (knob `langfuse_project = "smart-tutor-on-premise"`), `GET /langfuse/api/public/v2/observations` (assert `traceId` and that `fields` includes `io` and `metadata`; knobs `trace_observations`, `trace_after_polls`, `trace_poll_status`) and `GET /langfuse/api/public/v3/scores` (assert `traceId`, `name == "learner_rating"`; knobs `rating_value = True`, `rating_environment = "on-premise"`, `rating_config_id = "cfg"`, `rating_after_polls`, `rating_langfuse_status`). Record each Langfuse request's `authorization` in `langfuse_auth`. Rename knobs and assertions from Phoenix to Langfuse throughout the trace and rating sections, keeping every existing scenario (found after polls, wrong span id, missing metadata, other thread, token/username/user-id leaks, refused key, never arrived vs root never arrived, rating found, rating refused, rating wrong value, missing env vars) and adding: the key belongs to another project → fails naming both; the root's session is not the thread → fails; a score without `configId` → fails; a score in another environment → fails; `set(pilot.langfuse_auth) == {"Basic " + base64(public:secret)}` and the learner's bearer never sent to Langfuse; neither key printed. Tests set `LANGFUSE_BASE_URL=f"{pilot.base}/langfuse"` and the two keys with `monkeypatch.setenv`.
- [ ] **Step 2: Run** `cd infra && uv run pytest tests/test_smoke_test.py -q` → the Langfuse tests fail.
- [ ] **Step 3: Implement** the behavior above in `deploy/pilot/smoke_test.py`; delete `_phoenix`. Keep the style (stdlib, `s.request`, `s.wait`, `_json`, the deadline handling pattern of the current `check_trace`).
- [ ] **Step 4: Run** `cd infra && uv run pytest -q` → all pass. `grep -n -i phoenix deploy/pilot/smoke_test.py infra/tests/test_smoke_test.py` → nothing.
- [ ] **Step 5: Commit.**

```bash
git add deploy/pilot/smoke_test.py infra/tests/test_smoke_test.py
git commit -m "Check the ask's trace and rating in Langfuse in the smoke test (#318)" -m "Ratings now land in Langfuse, so the end-to-end check reads the trace (v2 observations: the v1 trace API is off on a v4 host) and the learner_rating score (v3 scores) there, and checks the key belongs to the expected project." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: PRD, ADR note, and runbooks

**Files:**
- Modify: `sdd/prd.md` (status line version; new "Changes from v2.69" row; §10.2 ~L682; §10.4 ~L698; data model `thread_turns.run_id` ~L459)
- Modify: `AGENTS.md` (PRD version in the sources table: v2.70)
- Modify: `sdd/adr/0023-how-smart-tutor-uses-langfuse.md` (§6 last bullet and a dated note)
- Modify: `docs/runbooks/on-premise-deploy.md` (§10 "Ratings" paragraph ~L427, sampling sentence ~L435, smoke-test command and its output line ~L442–445, Phoenix paragraph ~L449 "and the API sends ratings with it")
- Modify: `docs/runbooks/langfuse-host.md` (§8: the score config step)

- [ ] **Step 1: PRD.** Bump the status line to **v2.70** and add at the top of the changes table: `| **Changes from v2.69** | Ratings in Langfuse (#318, §10.2, §10.4, ADR 0023): the API sends each 👍 / 👎 to the environment's Langfuse project as a learner_rating BOOLEAN score on the ask's trace instead of a Phoenix annotation; the on-premise API gets the Langfuse URL and key pair instead of Phoenix's. Langfuse stores a score before its trace arrives, so there is no retry; it ingests scores a few seconds late and drops a delete that comes first, so a re-rating waits until the earlier score shows before deleting it. A score is checked against the project's learner_rating score config when there is one. The pilot smoke test checks the trace and the rating in Langfuse. Phoenix still receives traces until #322. |`. In §10.2 delete "Until #318 ships, ratings go to Phoenix as `HUMAN` span annotations." In §10.4 change "Until Phoenix is retired (#322), each trace also goes to the environment's Phoenix (ADR 0017), where ratings still land until #318." to "Until Phoenix is retired (#322), each trace also goes to the environment's Phoenix (ADR 0017)." In the `thread_turns` row: "`run_id` (the ask's trace id in Langfuse; null for older turns)". `grep -n "#318" sdd/prd.md` → only the new changes row (and history rows, which stay). Set `AGENTS.md`'s PRD row to `(v2.70)`.
- [ ] **Step 2: ADR 0023.** In §6 replace the last bullet ("A score may name a trace that hasn't arrived yet … keeps a retry only if Langfuse rejects such a score.") with: "A score may name a trace that hasn't arrived yet: Langfuse never looks the trace up, so there is no retry (confirmed in #318 against the source of the host's version, 4.47.0)." Add at the end of the ADR a section `## Notes` with `- 2026-10-15 (#318): on the host's v4.47.0 in events_only mode the v1/v2 score and trace read APIs answer 404, so the adapter lists scores with \`GET /api/public/v3/scores\` and the smoke test reads traces with \`GET /api/public/v2/observations\`. A delete that reaches Langfuse before the score is ingested (about 5–10 s after its POST) removes nothing, so before deleting the score it last posted for a run, the adapter waits until the list shows it (up to about a minute). A score is checked against a config only by \`configId\`, so the adapter looks up the project's \`learner_rating\` config by name and sends its id. A rating of an unsampled ask names a trace that never exists; the retention job's trace deletes don't reach it, but it holds only the boolean.`
- [ ] **Step 3: On-premise runbook §10.**
  - Ratings paragraph → `**Ratings (#318).** The API sends each learner's rating to Langfuse as a \`learner_rating\` BOOLEAN score (1 helpful, 0 not) on that ask's trace (the trace's Scores), with the project's key pair and environment \`on-premise\`. A new rating replaces the earlier score; a quick change waits until Langfuse shows the earlier score, up to about a minute, before deleting it. Without the keys, no ratings are sent. The project needs the \`learner_rating\` score config (\`langfuse-host.md\` section 8); without it scores are sent unchecked and the API logs a warning once.`
  - Sampling sentence: replace "Below 1, a rating of an unsampled ask is retried for about 30 s before it is dropped, and it delays the ratings behind it." with "Below 1, a rating of an unsampled ask is still stored in Langfuse, as a score on a trace that doesn't exist."
  - Smoke test: the command becomes

```bash
LANGFUSE_BASE_URL=$(aws ssm get-parameter --region us-east-1 --name /smart-tutor-on-premise/langfuse-url --query Parameter.Value --output text) \
LANGFUSE_PUBLIC_KEY=$(aws secretsmanager get-secret-value --region us-east-1 --secret-id smart-tutor-on-premise/langfuse/public-key --query SecretString --output text) \
LANGFUSE_SECRET_KEY=$(aws secretsmanager get-secret-value --region us-east-1 --secret-id smart-tutor-on-premise/langfuse/secret-key --query SecretString --output text) \
SMOKE_TEST_USERNAME=... SMOKE_TEST_PASSWORD=... python3 deploy/pilot/smoke_test.py https://<domain> --end-to-end --trace-project smart-tutor-on-premise
```

    (Git Bash on Windows: prefix `MSYS_NO_PATHCONV=1` for the SSM name, as the runbook does elsewhere.) Its output line: "it rates the turn thumbs-up and requires a `learner_rating` score with the project's score config, which proves the API has the Langfuse keys." Note the host's hours: run it 07:00–18:00 Asia/Ho_Chi_Minh.
  - Phoenix paragraph: drop ", and the API sends ratings with it".
- [ ] **Step 4: Langfuse host runbook §8.** After the project and keys sentence add: "In `smart-tutor-on-premise` and `smart-tutor-local`, create the score config learners' ratings are checked against: *Settings → Scores / Evaluation → Score Configs → Add*, name `learner_rating`, data type **Boolean**, description "Learner's 👍 (true) / 👎 (false) on an answer (PRD §10.2)". Ratings show on each `ask` trace's Scores, and under *Scores* filtered by name `learner_rating`; if a trace briefly has two, the newest counts."
- [ ] **Step 5: Check** `grep -rn "#318\|Phoenix until #318" docs sdd/prd.md backend/src` → only intended mentions; `grep -rn -i "phoenix" backend/src/smart_tutor/tutoring` → nothing.
- [ ] **Step 6: Commit.**

```bash
git add sdd/prd.md AGENTS.md sdd/adr/0023-how-smart-tutor-uses-langfuse.md docs/runbooks/on-premise-deploy.md docs/runbooks/langfuse-host.md
git commit -m "Document ratings in Langfuse (#318)" -m "PRD v2.70 drops the 'until #318' notes; the ADR records what the host's Langfuse version does with early scores and deletes; the runbooks give the score config step and the new smoke-test command." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

# Rate an answer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Under each kept turn (answer or decline) the learner rates it Helpful (👍) or Not helpful (👎); the API checks the turn is in the learner's own thread, saves the rating with the turn, and sends it to LangSmith as feedback on the turn's run, off the request, replacing any earlier rating; a 👎 extends the trace's retention.

**Architecture:** `thread_turns` gains a nullable `rating` (`up`/`down`). `ConversationService.rate_turn` checks ownership, saves through an owner-scoped `ThreadRepository.set_rating`, then hands the rating to a new `AnswerFeedback` port (tutoring). Its LangSmith adapter sends on a single background thread: it deletes the run's earlier `learner_rating` feedback and creates the new one (`extend_trace_retention` only for 👎), so a slow or unreachable LangSmith never delays or fails the rating; a failed send is logged. The API adds `PUT /threads/{thread_id}/turns/{run_id}/rating`, returns `rating` with each turn, and puts the turn's `run_id` in the stream's `thread` event so a just-streamed answer can be rated. The web shows two 28px icon buttons at the end of the Sources line (or on their own line for an answer without sources and for a decline).

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy + Alembic, langsmith 0.14 (`Client.create_feedback`, `list_feedback`, `delete_feedback`, `read_project`); React + TypeScript + Vite, lucide-react, Vitest + Testing Library; web client generated from OpenAPI.

**Spec:** GitHub issue #227 (parent #220); PRD §10.2, §10.3 item 7, §10.4; DESIGN.md → Chat (Helpful / Not helpful); design state `chat-feedback-reason` (round v0.10; v0.11's tag isn't pushed, the state is unchanged).

## Decisions taken for this slice

- **A turn is addressed by its run id**: `PUT /threads/{thread_id}/turns/{run_id}/rating`. The run id is already returned per turn (#221) and is what LangSmith feedback is keyed by. Turns kept before #221 have no run id and show no rating buttons.
- **The live answer learns its run id from the `thread` event**: `{"thread_id": …, "run_id": …}`. The turn is kept before `done` is forwarded, so a rating after `done` finds it.
- **No clearing a rating.** The ticket asks for set, change, see. Clicking the pressed button does nothing. (The prototype toggles it off; recorded as a gap.)
- **No "What could be better?" reason form.** PRD §10.2 and the ticket cover 👍/👎 only; a free-text reason would also put learner text into feedback. Recorded in the brief's Feedback log and the PR.
- **Port in `tutoring`, adapter in `tutoring.adapters`** (`AnswerFeedback`, `LangSmithAnswerFeedback`): rating answers is a tutoring concept; adapters may use vendor SDKs.
- **Sync LangSmith calls on one background thread** (not the SDK's batch queue): the batch queue takes only `extend_trace_retention=True` feedback, and mixing paths would let a quick 👍→👎→👍 race. One worker thread keeps sends in order; each send leaves exactly one `learner_rating` feedback on the run.
- **Feedback payload:** key `learner_rating`, `score` 1 (up) / 0 (down), `value` `"up"`/`"down"`, `run_id` = the turn's run id, `session_id` = the ask project's id (read once by name), `extend_trace_retention` = (rating is down). No comment, no `source_info`, no `extra`: the port takes no user id, so none can reach LangSmith.
- **Feedback is on only when LangSmith tracing is on** in the API process (`langsmith.utils.tracing_is_enabled()`); otherwise `NoAnswerFeedback`. The project is `langsmith.utils.get_tracer_project()` (the same `LANGSMITH_PROJECT` the agent traces to).

## Global Constraints

- Backend rules in `backend/AGENTS.md`: `tutoring.domain`/`application`/`ports` import no vendor SDK and no `shared.adapters`; `apps` is a leaf; routes parse input, call one service, format output.
- Every read and write of a turn is scoped by the thread's owner in SQL (`thread_turns.user_id`). Another learner's thread, or a run id not in the caller's thread, is a 404 with no detail about the other learner.
- The LangSmith feedback carries no user id, email, name, or token (ticket AC). The `AnswerFeedback` port's signature has no user parameter.
- A LangSmith outage never fails or delays the rating request: the send runs off the request, and any exception from it is logged (`logger.error`, class name and run id only), never raised to the route.
- Unit tests never reach the network: the adapter is tested with a fake LangSmith client and an inline executor.
- Web: API calls only through `web/src/api/`; after changing a route run the client regeneration (`cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`); CI fails when stale. UI follows `DESIGN.md`: Helpful / Not helpful are two 28px icon buttons at the end of the Sources line (`aria-label`, `aria-pressed`, visible tooltip).
- Labels and copy, verbatim: buttons "Helpful", "Not helpful"; after 👍 "Thanks — glad it helped."; after 👎 "Thanks — your feedback helps improve answers."; on a failed save "Your rating couldn't be saved. Try again."
- Checks before each commit: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest` (backend tasks); `cd web && npm run build && npx vitest run` (web task). Integration: `uv run --env-file ../.env pytest -m integration tests/integration/tutoring tests/integration/shared -q` when Compose is up.
- Windows Git Bash: `PYTHONUTF8=1` for `lint-imports`.
- Commit subjects in the imperative mood; body says why; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. **Another learner's run id inside the caller's own thread id** (or the other way round): must be 404 and change nothing, not just "thread not yours". Task 3's isolation test covers both shapes.
2. **The turn wasn't kept** (the stream ended with `error`, or saving the turn failed): the web must not offer rating buttons for a turn that didn't end with `done`; if the PUT still 404s, the button un-presses and says "Your rating couldn't be saved. Try again." Task 4 pins both.
3. **Quick changes** 👍→👎→👍: LangSmith ends with one `learner_rating` feedback equal to the last rating. Task 2 pins the replace-not-append behavior; ordering comes from the single worker thread.
4. **LangSmith unreachable or `read_project` failing**: the rating still saves and the route answers 200; the error is logged once per send. Tasks 1 (service) and 2 (adapter) pin it.
5. **A conversation switched while a rating is in flight**: the late reply must not write a rating into another conversation's turns. Task 4 guards with the page's `turn` counter.

---

### Task 1: Store a turn's rating (domain, repository, migration, service)

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/domain/turn.py` (add `Rating`; `rating` on `Turn` and `TurnView`)
- Modify: `backend/src/smart_tutor/tutoring/domain/errors.py` (add `TurnNotFoundError`)
- Create: `backend/src/smart_tutor/tutoring/ports/answer_feedback.py` (`AnswerFeedback`, `NoAnswerFeedback`)
- Modify: `backend/src/smart_tutor/tutoring/ports/thread_repository.py` (add `set_rating`)
- Modify: `backend/src/smart_tutor/tutoring/adapters/sql_threads.py` (column `rating`, `_turn` reads it, `set_rating`)
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0016_thread_turn_rating.py`
- Modify: `backend/src/smart_tutor/tutoring/application/conversation_service.py` (constructor takes `feedback`, `rate_turn`, `turns` passes `rating`)
- Modify: `backend/src/smart_tutor/tutoring/application/__init__.py` (export `Rating`, `TurnNotFoundError`, `AnswerFeedback`, `NoAnswerFeedback`)
- Modify: `backend/tests/fakes/tutoring.py` (`InMemoryThreads.set_rating`, `FakeAnswerFeedback`), `backend/tests/fakes/__init__.py` (export `FakeAnswerFeedback`)
- Test: `backend/tests/unit/tutoring/test_conversation_service.py`, `backend/tests/integration/tutoring/test_sql_threads.py`, `backend/tests/integration/shared/test_migrations.py` (only if it pins the head revision)

**Interfaces:**
- Produces:
  - `class Rating(StrEnum): UP = "up"; DOWN = "down"` in `tutoring/domain/turn.py`
  - `Turn.rating: Rating | None = None` (last field, after `run_id`); `TurnView.rating: Rating | None = None` (last field)
  - `class TurnNotFoundError(DomainError)` — "The answer doesn't exist in the learner's conversation."
  - `class AnswerFeedback(ABC): def send(self, run_id: RunId, rating: Rating) -> None` ("Attach the learner's rating to the answer's run, replacing an earlier one. Must not block on the network.") and `class NoAnswerFeedback(AnswerFeedback)` (does nothing)
  - `ThreadRepository.set_rating(self, thread_id: ThreadId, user_id: UserId, run_id: RunId, rating: Rating) -> bool` — "Store the rating on that turn of the learner's thread (committed). False when the learner's thread has no turn with this run id."
  - `ConversationService(threads, documents, clock, feedback: AnswerFeedback | None = None)` (None → `NoAnswerFeedback()`)
  - `ConversationService.rate_turn(self, thread_id: ThreadId, user_id: UserId, run_id: RunId, rating: Rating) -> None` — raises `ThreadNotFoundError` (not the learner's thread), `TurnNotFoundError` (no such turn in it)
  - `tests/fakes`: `FakeAnswerFeedback` with `sent: list[tuple[RunId, Rating]]` and optional `error: Exception | None` raised from `send`

- [ ] **Step 1: Write the failing unit tests** in `backend/tests/unit/tutoring/test_conversation_service.py`, following the file's existing setup (look at how it builds `ConversationService` with `InMemoryThreads`, a `DocumentService` over `InMemoryLibrary`, and `FixedClock`, and how it records a turn with `AnsweredTurn(..., run_id=...)`). Tests:

```python
def test_a_learner_rates_their_turn_and_the_rating_is_kept_and_sent() -> None:
    threads, feedback = InMemoryThreads(), FakeAnswerFeedback()
    service = _service(threads, feedback=feedback)  # the file's helper, extended with `feedback`
    thread = service.start_thread(OWNER, "What is attention?")
    run = RunId(str(uuid.uuid4()))
    service.record_turn(ThreadId(thread.thread_id), OWNER, AnsweredTurn("What is attention?", "It weighs tokens.", run_id=run))

    service.rate_turn(ThreadId(thread.thread_id), OWNER, run, Rating.UP)

    [turn] = service.turns(ThreadId(thread.thread_id), OWNER)
    assert turn.rating is Rating.UP
    assert feedback.sent == [(run, Rating.UP)]


def test_changing_a_rating_replaces_it() -> None:
    # rate UP then DOWN: turns() shows DOWN; feedback.sent == [(run, UP), (run, DOWN)]


def test_a_declined_turn_can_be_rated() -> None:
    # record AnsweredTurn(question, decline=Decline("limited", "…"), run_id=run); rate DOWN; turns()[0].rating is DOWN


def test_rating_another_learners_thread_is_not_found_and_changes_nothing() -> None:
    # OWNER's thread and turn; rate_turn(thread, OTHER, run, DOWN) raises ThreadNotFoundError;
    # OWNER's turn rating stays None; feedback.sent == []


def test_rating_a_run_that_is_not_in_the_thread_is_not_found() -> None:
    # rate_turn(thread, OWNER, RunId(str(uuid.uuid4())), UP) raises TurnNotFoundError; feedback.sent == []


def test_a_failing_feedback_send_still_keeps_the_rating(caplog: pytest.LogCaptureFixture) -> None:
    # FakeAnswerFeedback(error=RuntimeError("LangSmith down")); rate_turn does not raise; turns()[0].rating is UP;
    # caplog has one ERROR record mentioning "RuntimeError"; the run id may appear, OWNER must not.


def test_an_unrated_turn_reads_none() -> None:
    # record a turn, never rate: turns()[0].rating is None
```

Write each body fully in the file's style (the comments above say exactly what to assert).

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && uv run pytest tests/unit/tutoring/test_conversation_service.py -q`
Expected: FAIL (`ImportError` for `Rating` / `FakeAnswerFeedback`).

- [ ] **Step 3: Implement the domain, port, fake, and service**

`tutoring/domain/turn.py` — add after the imports (`from enum import StrEnum`):

```python
class Rating(StrEnum):
    """The learner's rating of a kept turn (PRD §10.2): helpful or not. One per turn; a new one replaces it."""

    UP = "up"
    DOWN = "down"
```

and add `rating: Rating | None = None  # the learner's 👍/👎 (PRD §10.2); None until rated` as the last field of `Turn` and of `TurnView`.

`tutoring/domain/errors.py`:

```python
class TurnNotFoundError(DomainError):
    """The answer doesn't exist in the learner's conversation (PRD §10.2)."""
```

`tutoring/ports/answer_feedback.py`:

```python
"""Learner ratings sent on to where answers are evaluated (PRD §10.2): LangSmith feedback on the answer's run."""

from abc import ABC, abstractmethod

from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.domain.turn import Rating


class AnswerFeedback(ABC):
    @abstractmethod
    def send(self, run_id: RunId, rating: Rating) -> None:
        """Attach the learner's rating to the answer's run, replacing an earlier one. Must not block on the network;
        never given who rated."""


class NoAnswerFeedback(AnswerFeedback):
    """Tracing is off: there is no run to attach a rating to."""

    def send(self, run_id: RunId, rating: Rating) -> None:
        return None
```

`ThreadRepository.set_rating` as in Interfaces (abstract, docstring there).

`tests/fakes/tutoring.py` — `InMemoryThreads.set_rating`: find the index of the turn in `self.turn_rows` with matching `thread_id`, `user_id`, `run_id`; replace it with `dataclasses.replace(turn, rating=rating)`; return whether one matched. Add:

```python
class FakeAnswerFeedback(AnswerFeedback):
    """Records each rating sent; raises `error` from send when given one."""

    def __init__(self, error: Exception | None = None) -> None:
        self.sent: list[tuple[RunId, Rating]] = []
        self._error = error

    def send(self, run_id: RunId, rating: Rating) -> None:
        if self._error is not None:
            raise self._error
        self.sent.append((run_id, rating))
```

Export `FakeAnswerFeedback` from `tests/fakes/__init__.py` (add to its import list and `__all__` the way `InMemoryThreads` is).

`ConversationService`: constructor gains `feedback: AnswerFeedback | None = None` → `self._feedback = feedback or NoAnswerFeedback()`. Add `logger = logging.getLogger(__name__)` at module level. `turns()` passes `t.rating` as the new last `TurnView` argument. New method:

```python
    def rate_turn(self, thread_id: ThreadId, user_id: UserId, run_id: RunId, rating: Rating) -> None:
        """The learner rates a kept answer or decline of their conversation (PRD §10.2); a new rating replaces the
        last. It is saved first; sending it to LangSmith never fails the rating."""
        self._owned(thread_id, user_id)
        if not self._threads.set_rating(thread_id, user_id, run_id, rating):
            raise TurnNotFoundError("Answer not found")
        try:
            self._feedback.send(run_id, rating)
        except Exception as e:
            # Only the class name and run id: the learner is never named in logs.
            logger.error("sending the rating of run %s failed (%s)", run_id, type(e).__name__)
```

Export from `tutoring/application/__init__.py`: `Rating`, `TurnNotFoundError`, `AnswerFeedback`, `NoAnswerFeedback` (keep `__all__` sorted).

- [ ] **Step 4: Run the unit tests** — `uv run pytest tests/unit/tutoring -q` → PASS.

- [ ] **Step 5: Write the SQL adapter and migration**

Migration `0016_thread_turn_rating.py` (copy 0015's header style):

```python
"""The learner's rating of a kept turn (PRD §10.2, #227): "up" or "down", null until rated.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("thread_turns", sa.Column("rating", sa.Text()))
    op.create_check_constraint("thread_turns_rating", "thread_turns", "rating IN ('up', 'down')")


def downgrade() -> None:
    op.drop_constraint("thread_turns_rating", "thread_turns", type_="check")
    op.drop_column("thread_turns", "rating")
```

`sql_threads.py`: module docstring lists `0016`; add `Column("rating", Text)` to `thread_turns`; `_turn` passes `Rating(row.rating) if row.rating else None` as the last argument; add:

```python
    def set_rating(self, thread_id: ThreadId, user_id: UserId, run_id: RunId, rating: Rating) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                update(thread_turns)
                .where(
                    thread_turns.c.thread_id == thread_id,
                    thread_turns.c.user_id == user_id,
                    thread_turns.c.run_id == run_id,
                )
                .values(rating=rating.value)
            )
        return result.rowcount > 0
```

Integration tests in `test_sql_threads.py` (style of `test_a_turn_keeps_its_run_id_and_one_without_reads_none`):
- `test_a_turns_rating_is_set_and_replaced_for_its_owner_only`: add a thread and a turn with a run id; `set_rating(..., owner, run, Rating.UP)` is True and `turns()` reads UP; then DOWN reads DOWN; `set_rating(thread, UserId("bob"), run, Rating.UP)` is False and the rating stays DOWN; `set_rating(thread, owner, RunId(str(uuid.uuid4())), Rating.UP)` is False.
If `tests/integration/shared/test_migrations.py` asserts the head revision, update it to `0016`.

- [ ] **Step 6: Run checks**

`uv run pytest -q`, `uv run mypy`, `uv run ruff check . && uv run ruff format --check .`, `PYTHONUTF8=1 uv run lint-imports`. If Compose is up (`docker compose ps` shows postgres): `uv run --env-file ../.env pytest -m integration tests/integration/tutoring tests/integration/shared -q`. If Compose isn't up, say so in the report.

- [ ] **Step 7: Commit** — `git add` the files above; subject "Keep a learner's rating with the turn and pass it to answer feedback"; body: why (PRD §10.2: ratings calibrate judges; the rating is saved before it is sent, so an outage never loses it).

---

### Task 2: Send ratings to LangSmith as feedback on the turn's run

**Files:**
- Create: `backend/src/smart_tutor/tutoring/adapters/langsmith_feedback.py`
- Modify: `backend/tests/fakes/tracing.py` (add `FeedbackClient`, `InlineExecutor`), `backend/tests/fakes/__init__.py` (export them)
- Modify: `backend/src/smart_tutor/apps/api/services.py` (build the feedback and pass it to `ConversationService`)
- Test: `backend/tests/unit/tutoring/test_langsmith_feedback.py`

**Interfaces:**
- Consumes: `AnswerFeedback`, `Rating` (Task 1); `ConversationService(..., feedback=...)`.
- Produces: `LangSmithAnswerFeedback(project_name: str, client: langsmith.Client | None = None, executor: concurrent.futures.Executor | None = None)` with `send(run_id, rating)`; module constant `FEEDBACK_KEY = "learner_rating"`; `answer_feedback(settings: Settings) -> AnswerFeedback` (LangSmith when `langsmith.utils.tracing_is_enabled()`, else `NoAnswerFeedback()`). `tests/fakes`: `FeedbackClient` (a `langsmith.Client` subclass that keeps feedback in memory), `InlineExecutor`.

- [ ] **Step 1: Add the fakes** to `backend/tests/fakes/tracing.py`:

```python
class FeedbackClient(langsmith.Client):
    """LangSmith client that keeps feedback in memory and records each call's arguments; never reaches the network.
    `fail` makes every call raise, as an outage would."""

    def __init__(self, fail: Exception | None = None) -> None:
        super().__init__(api_key="test-not-a-key", api_url="http://127.0.0.1:9", auto_batch_tracing=False)
        self.project_id = uuid.uuid4()
        self.feedback: dict[uuid.UUID, dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fail = fail

    def _call(self, name: str, kwargs: dict[str, Any]) -> None:
        self.calls.append((name, kwargs))
        if self._fail is not None:
            raise self._fail

    def read_project(self, **kwargs: Any) -> Any:
        self._call("read_project", kwargs)
        return SimpleNamespace(id=self.project_id)

    def list_feedback(self, **kwargs: Any) -> Iterator[Any]:
        self._call("list_feedback", kwargs)
        runs = {str(r) for r in kwargs.get("run_ids") or []}
        keys = set(kwargs.get("feedback_key") or [])
        return iter(
            [SimpleNamespace(id=i, **f) for i, f in self.feedback.items() if str(f["run_id"]) in runs and f["key"] in keys]
        )

    def delete_feedback(self, feedback_id: Any) -> None:
        self._call("delete_feedback", {"feedback_id": feedback_id})
        del self.feedback[feedback_id]

    def create_feedback(self, run_id: Any = None, key: str = "unnamed", **kwargs: Any) -> Any:
        self._call("create_feedback", {"run_id": run_id, "key": key, **kwargs})
        feedback_id = uuid.uuid4()
        self.feedback[feedback_id] = {"run_id": run_id, "key": key, **kwargs}
        return SimpleNamespace(id=feedback_id)


class InlineExecutor(Executor):
    """Runs each task at once on the caller's thread, so a test sees its effect when `submit` returns."""

    def submit(self, fn: Callable[..., T], /, *args: Any, **kwargs: Any) -> Future[T]:
        future: Future[T] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except Exception as e:
            future.set_exception(e)
        return future
```

(imports: `uuid`, `SimpleNamespace`, `Iterator`, `Callable`, `TypeVar`, `Executor`, `Future`; `T = TypeVar("T")`). Export both from `tests/fakes/__init__.py`.

- [ ] **Step 2: Write the failing tests** in `backend/tests/unit/tutoring/test_langsmith_feedback.py`:

```python
RUN = RunId(str(uuid.uuid4()))


def feedback(client: FeedbackClient) -> LangSmithAnswerFeedback:
    return LangSmithAnswerFeedback("smart-tutor-test", client=client, executor=InlineExecutor())


def test_a_helpful_rating_is_feedback_on_the_run_without_extending_retention() -> None:
    client = FeedbackClient()
    feedback(client).send(RUN, Rating.UP)
    [f] = client.feedback.values()
    assert str(f["run_id"]) == RUN and f["key"] == "learner_rating"
    assert f["score"] == 1 and f["value"] == "up"
    assert f["session_id"] == client.project_id
    assert f["extend_trace_retention"] is False


def test_a_not_helpful_rating_extends_the_traces_retention() -> None:
    client = FeedbackClient()
    feedback(client).send(RUN, Rating.DOWN)
    [f] = client.feedback.values()
    assert f["score"] == 0 and f["value"] == "down" and f["extend_trace_retention"] is True


def test_a_new_rating_replaces_the_runs_earlier_one() -> None:
    client = FeedbackClient()
    sender = feedback(client)
    sender.send(RUN, Rating.UP)
    sender.send(RUN, Rating.DOWN)
    sender.send(RUN, Rating.UP)
    [f] = client.feedback.values()
    assert f["value"] == "up"


def test_another_runs_feedback_is_left_alone() -> None:
    client = FeedbackClient()
    other = RunId(str(uuid.uuid4()))
    sender = feedback(client)
    sender.send(other, Rating.DOWN)
    sender.send(RUN, Rating.UP)
    assert sorted(f["value"] for f in client.feedback.values()) == ["down", "up"]


def test_the_feedback_carries_nothing_but_the_rating() -> None:
    client = FeedbackClient()
    feedback(client).send(RUN, Rating.DOWN)
    [(_, created)] = [c for c in client.calls if c[0] == "create_feedback"]
    assert set(created) == {"run_id", "key", "score", "value", "session_id", "extend_trace_retention"}


def test_the_project_is_read_once(...) -> None:
    # two sends → exactly one "read_project" call, with project_name="smart-tutor-test"


def test_an_unreachable_langsmith_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    client = FeedbackClient(fail=ConnectionError("down"))
    feedback(client).send(RUN, Rating.UP)  # must not raise
    assert any(r.levelno == logging.ERROR and "ConnectionError" in r.getMessage() for r in caplog.records)


def test_the_send_runs_off_the_callers_thread() -> None:
    # Real executor: a client whose create_feedback blocks on a threading.Event; send() returns before the event is
    # set; after setting it, shut the adapter's executor down (`sender.close()`), and the feedback exists.


def test_answer_feedback_is_off_while_tracing_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    # langsmith caches env reads: call `langsmith.utils.get_env_var.cache_clear()` before and after if needed
    assert isinstance(answer_feedback(Settings()), NoAnswerFeedback)
```

- [ ] **Step 3: Run them to see them fail** — `uv run pytest tests/unit/tutoring/test_langsmith_feedback.py -q` → FAIL (module missing).

- [ ] **Step 4: Implement `tutoring/adapters/langsmith_feedback.py`**

```python
"""Learner ratings as LangSmith feedback on the answer's run (PRD §10.2), so LLM judges can be calibrated against
them. Sent off the request on one background thread, in order: a slow or unreachable LangSmith never delays or fails
the rating, which is already saved with the turn. A failed send is logged. The feedback says only the rating: no user
id, email, name, or token (PRD §10.4)."""

import logging
import uuid
from concurrent.futures import Executor, Future, ThreadPoolExecutor

import langsmith
from langsmith import utils as ls_utils

from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import RunId
from smart_tutor.tutoring.domain.turn import Rating
from smart_tutor.tutoring.ports.answer_feedback import AnswerFeedback, NoAnswerFeedback

logger = logging.getLogger(__name__)

FEEDBACK_KEY = "learner_rating"


class LangSmithAnswerFeedback(AnswerFeedback):
    def __init__(
        self, project_name: str, client: langsmith.Client | None = None, executor: Executor | None = None
    ) -> None:
        self._project = project_name
        self._client = client or langsmith.Client()
        # One worker: sends happen in the order the learner rated, so the last rating is the one left.
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="answer-feedback")
        self._project_id: uuid.UUID | None = None

    def send(self, run_id: RunId, rating: Rating) -> None:
        self._executor.submit(self._replace, run_id, rating).add_done_callback(
            lambda done: _log_failure(done, run_id)
        )

    def close(self) -> None:
        """Wait for the sends still queued (process shutdown)."""
        self._executor.shutdown(wait=True)

    def _replace(self, run_id: RunId, rating: Rating) -> None:
        for earlier in self._client.list_feedback(run_ids=[run_id], feedback_key=[FEEDBACK_KEY]):
            self._client.delete_feedback(earlier.id)
        self._client.create_feedback(
            run_id=run_id,
            key=FEEDBACK_KEY,
            score=1 if rating is Rating.UP else 0,
            value=rating.value,
            session_id=self._session_id(),
            # A 👎 keeps the trace long enough to be reviewed (PRD §10.3 item 7); a 👍 leaves its retention as it is.
            extend_trace_retention=rating is Rating.DOWN,
        )

    def _session_id(self) -> uuid.UUID:
        if self._project_id is None:
            self._project_id = self._client.read_project(project_name=self._project).id
        return self._project_id


def _log_failure(done: "Future[None]", run_id: RunId) -> None:
    error = done.exception()
    if error is not None:
        logger.error("sending the rating of run %s to LangSmith failed (%s)", run_id, type(error).__name__)


def answer_feedback(settings: Settings) -> AnswerFeedback:
    """LangSmith feedback while tracing is on, into the project the agent traces asks to; otherwise none."""
    if not ls_utils.tracing_is_enabled():
        return NoAnswerFeedback()
    return LangSmithAnswerFeedback(ls_utils.get_tracer_project())
```

(`settings` is accepted so the composition root reads like the others; if mypy/ruff flag it unused, drop the parameter and update the test.) Match the real `create_feedback`/`list_feedback`/`delete_feedback`/`read_project` signatures in `.venv/Lib/site-packages/langsmith/client.py` (langsmith 0.14.3): `create_feedback(run_id, key, *, score, value, session_id, extend_trace_retention, ...)`, `list_feedback(*, run_ids, feedback_key)`, `delete_feedback(feedback_id)`, `read_project(*, project_name)`.

- [ ] **Step 5: Wire it** in `apps/api/services.py`: `from smart_tutor.tutoring.adapters.langsmith_feedback import answer_feedback`; `conversations = ConversationService(SqlThreadRepository(engine), documents, SystemClock(), feedback=answer_feedback(settings))`.

- [ ] **Step 6: Run checks** (full backend check line from Global Constraints) → PASS.

- [ ] **Step 7: Commit** — subject "Send a learner's rating to LangSmith as feedback on the answer's run"; body: off the request on one thread (outage-safe, ordered), replaces the earlier rating, 👎 extends retention, carries no learner identity.

---

### Task 3: Rate a turn through the API (route, turn list, stream event, isolation, web client)

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py`
- Modify: `backend/tests/fakes/api.py` (`api_services(..., feedback: FakeAnswerFeedback | None = None)` passes it to `ConversationService`)
- Test: `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py`
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`

**Interfaces:**
- Consumes: `ConversationService.rate_turn`, `Rating`, `TurnNotFoundError`, `ThreadNotFoundError`, `TurnView.rating` (Task 1).
- Produces (HTTP, used by Task 4):
  - `PUT /threads/{thread_id}/turns/{run_id}/rating`, operation id `rate_turn`, body `{"rating": "up" | "down"}` (unknown fields refused), 200 `{"rating": "up" | "down"}`; 404 "Not the caller's conversation, or no such answer in it."; 422 for a bad body or a non-UUID id.
  - `TurnResponse.rating: "up" | "down" | null`
  - SSE `thread` event data `{"thread_id": "<uuid>", "run_id": "<uuid>"}`
  - Generated web SDK function `rateTurn` and types `RateTurnRequest`, `TurnRatingResponse`.

- [ ] **Step 1: Write the failing route tests** in `test_thread_routes.py` (reuse the file's helpers for an app with fakes and the agent stub that answers; look at `test_a_declined_turn_keeps_its_run_id_too` for how a turn's run id is read):
  - `test_the_thread_event_carries_the_asks_run_id`: POST /threads; the first event's data has `thread_id` and `run_id`, and `run_id` equals the one sent to the agent and the one `GET /threads/{id}/turns` returns.
  - `test_a_learner_rates_a_turn_and_sees_the_rating_with_the_turn`: after an answer, `PUT .../turns/{run_id}/rating` `{"rating": "up"}` → 200 `{"rating": "up"}`; the turns list shows `"rating": "up"`; a second PUT with `"down"` → turns show `"down"`; `FakeAnswerFeedback.sent == [(run, UP), (run, DOWN)]`.
  - `test_an_unrated_turn_lists_a_null_rating`: turns list item has `"rating": None`; update the existing key-set assertion (line ~884) to include `"rating"`.
  - `test_a_decline_can_be_rated`: agent stub sends a decline then done; PUT down → 200.
  - `test_rating_an_unknown_run_is_404`: PUT with a random UUID run id in the learner's own thread → 404, nothing sent.
  - `test_a_rating_must_be_up_or_down`: `{"rating": "meh"}` → 422; `{"rating": "up", "user_id": "x"}` → 422.
  - `test_a_feedback_outage_still_saves_the_rating`: `api_services(..., feedback=FakeAnswerFeedback(error=ConnectionError()))`; PUT → 200; turns show the rating.
  - Update `test_..._no_documents...` at line ~186 that compares the whole stream text: the `thread` event now reads `{"thread_id": "...", "run_id": "..."}` (take the run id from the agent request the test records, or assert with a regex/`json.loads` of the first event).

- [ ] **Step 2: Write the failing isolation test** in `backend/tests/isolation/test_threads.py` (update the module docstring to mention `PUT /threads/{id}/turns/{run_id}/rating`):

```python
def test_only_the_owner_rates_a_turn() -> None:
    library, threads, feedback = InMemoryLibrary(), InMemoryThreads(), FakeAnswerFeedback()
    ingest_ready(library, "learner-a", "Attention weighs tokens.")
    ingest_ready(library, "learner-b", "Gradient descent follows the slope.")
    services = api_services(library, threads=threads, agent=fake_agent(answers), feedback=feedback)
    client = TestClient(create_app(Settings(), verifier=learners(), services=services))
    assert client.post("/threads", json={"question": "What is attention?"}, headers=A).status_code == 200
    assert client.post("/threads", json={"question": "What is descent?"}, headers=B).status_code == 200
    [a_turn] = [t for t in threads.turn_rows if t.user_id == "learner-a"]
    [b_turn] = [t for t in threads.turn_rows if t.user_id == "learner-b"]

    # B on A's thread and run, and B's own thread with A's run: both 404, nothing changes or is sent.
    theirs = client.put(f"/threads/{a_turn.thread_id}/turns/{a_turn.run_id}/rating", json={"rating": "down"}, headers=B)
    mixed = client.put(f"/threads/{b_turn.thread_id}/turns/{a_turn.run_id}/rating", json={"rating": "down"}, headers=B)

    assert theirs.status_code == 404 and mixed.status_code == 404
    assert "What is attention?" not in theirs.text + mixed.text
    assert all(t.rating is None for t in threads.turn_rows)
    assert feedback.sent == []
    mine = client.put(f"/threads/{a_turn.thread_id}/turns/{a_turn.run_id}/rating", json={"rating": "up"}, headers=A)
    assert mine.status_code == 200 and feedback.sent == [(a_turn.run_id, Rating.UP)]
```

- [ ] **Step 3: Run them to see them fail** — `uv run pytest tests/unit/apps/api/test_thread_routes.py tests/isolation/test_threads.py -q` → FAIL.

- [ ] **Step 4: Implement** in `routes/threads.py` (also extend the module docstring: "The learner rates a kept answer or decline 👍/👎 (PRD §10.2); the rating is saved with the turn and sent to LangSmith on its run."):
  - The `start()` closures in both ask routes emit `_sse("thread", {"thread_id": …, "run_id": run_id})`.
  - `TurnResponse` gains `rating: Literal["up", "down"] | None = Field(description="The learner's rating (PRD §10.2); null until rated.")`; `_turn_response` sets `rating=t.rating.value if t.rating else None`.
  - New models and route:

```python
class RateTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["up", "down"]


class TurnRatingResponse(BaseModel):
    rating: Literal["up", "down"]


@router.put(
    "/threads/{thread_id}/turns/{run_id}/rating",
    operation_id="rate_turn",
    responses={404: {"description": "Not the caller's conversation, or no such answer in it."}},
)
def rate_turn(
    thread_id: uuid.UUID, run_id: uuid.UUID, body: RateTurnRequest, principal: CurrentPrincipal, conversations: Conversations
) -> TurnRatingResponse:
    """Rate an answer or decline of the learner's conversation helpful ("up") or not ("down"); a new rating replaces
    the last (PRD §10.2). Saved with the turn and sent to LangSmith as feedback on its run; an outage there doesn't fail
    the rating."""
    try:
        conversations.rate_turn(ThreadId(str(thread_id)), principal.user_id, RunId(str(run_id)), Rating(body.rating))
    except (ThreadNotFoundError, TurnNotFoundError) as e:
        raise HTTPException(404, str(e)) from None
    return TurnRatingResponse(rating=body.rating)
```

  - `tests/fakes/api.py`: new keyword `feedback: FakeAnswerFeedback | None = None`; `ConversationService(threads, documents, clock, feedback=feedback)`.

- [ ] **Step 5: Run backend checks** (full line) → PASS.

- [ ] **Step 6: Regenerate the web client**: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Then `cd web && npm run build` (existing code must still type-check; `ChatEvent`'s `thread` type gains `run_id` only in Task 4).

- [ ] **Step 7: Commit** — subject "Let a learner rate an answer through the API"; body: the turn is addressed by its run id; the `thread` event carries the run id so a streamed answer can be rated; another learner's turn is a 404 (isolation test).

---

### Task 4: Helpful / Not helpful under each answer (web)

**Files:**
- Modify: `web/src/api/chat.ts` (`Rating`, `thread` event `run_id`, `rateAnswer`)
- Create: `web/src/features/chat/AnswerRating.tsx`, `web/src/features/chat/AnswerRating.module.css`, `web/src/features/chat/AnswerRating.test.tsx`
- Modify: `web/src/features/chat/ChatPage.tsx`, `web/src/features/chat/ChatPage.module.css`
- Test: `web/src/api/chat.test.ts`, `web/src/features/chat/ChatPage.test.tsx`

**Interfaces:**
- Consumes: generated `rateTurn` (path `{thread_id, run_id}`, body `{rating}`), `TurnResponse.rating`, `TurnResponse.run_id`; SSE `thread` data `run_id` (Task 3).
- Produces:
  - `export type Rating = "up" | "down"` in `api/chat.ts`
  - `ChatEvent` `{ type: "thread"; thread_id: string; run_id: string | null }`
  - `rateAnswer(threadId: string, runId: string, rating: Rating, apiClient?: Client): Promise<Rating>` — throws `SessionExpiredError` on 401, `Error` otherwise
  - `AnswerRating({ rating, onRate }: { rating: Rating | null; onRate: (rating: Rating) => Promise<void> })`
  - `ChatPage` prop `rate?: (threadId: string, runId: string, rating: Rating) => Promise<Rating>`

- [ ] **Step 1: `api/chat.ts`** — tests first in `chat.test.ts` (follow its existing SSE and SDK mocking style):
  - the `thread` event parses `run_id` (and reads `null` when the server sent none);
  - `rateAnswer("t1", "r1", "down")` sends `PUT /threads/t1/turns/r1/rating` with `{"rating":"down"}` and resolves `"down"`; a 404 rejects with an `Error`; a 401 rejects with `SessionExpiredError`.

  Implement:

```ts
export type Rating = "up" | "down";
// ChatEvent: | { type: "thread"; thread_id: string; run_id: string | null }
// toEvent "thread": { type: "thread", thread_id: p.thread_id as string, run_id: (p.run_id as string | undefined) ?? null }

// Rates a kept answer or decline of the learner's conversation; a new rating replaces the last (PRD §10.2). Another
// learner's conversation, or an answer that wasn't kept, is a 404.
export async function rateAnswer(threadId: string, runId: string, rating: Rating, apiClient: Client = client): Promise<Rating> {
  const { data, error, response } = await rateTurn({
    client: apiClient,
    path: { thread_id: threadId, run_id: runId },
    body: { rating },
    throwOnError: false,
  });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw new Error(`PUT /threads/${threadId}/turns/${runId}/rating failed (${response?.status ?? "no response"})`);
  return data.rating;
}
```

- [ ] **Step 2: `AnswerRating` component** — tests first in `AnswerRating.test.tsx`:
  - renders buttons named "Helpful" and "Not helpful", both `aria-pressed="false"` when `rating` is null;
  - `rating="up"` → Helpful pressed, text "Thanks — glad it helped."; `rating="down"` → Not helpful pressed, "Thanks — your feedback helps improve answers.";
  - clicking Not helpful calls `onRate("down")`; while it is pending, Not helpful shows pressed (optimistic);
  - `onRate` rejecting → the pressed state goes back to the `rating` prop and "Your rating couldn't be saved. Try again." shows; a later successful click clears it;
  - clicking the already-pressed button does not call `onRate`.

  Implement with `IconButton` (`ThumbsUp`, `ThumbsDown` from lucide-react), local `pending: Rating | null` and `failed: boolean` state; `shown = pending ?? rating`; the thanks / failure text goes in a `<span className={styles.note} role="status">` after the buttons. CSS: `.rating { display: inline-flex; align-items: center; gap: var(--sp-1); margin-left: auto; }`, pressed: `.rating [aria-pressed="true"] { color: var(--accent-text); background: var(--accent-soft); box-shadow: inset 0 0 0 1px var(--accent); }`, `.note { font-size: var(--fs-12); color: var(--text-2); }`. Check `DESIGN.md` → Components and Accessibility for the exact tokens and focus ring; IconButton already gives 28px, the tooltip, and focus styles.

- [ ] **Step 3: ChatPage** — tests first in `ChatPage.test.tsx` (use the file's stream helpers; the `thread` event in fixtures now carries `run_id: "r1"`):
  - after an answer ends with `done`, "Helpful" and "Not helpful" show at the end of its Sources line; clicking Helpful calls `rate("t1", "r1", "up")` and the button is pressed;
  - an answer without citations, and a declined turn (`limited`), show the two buttons on a line of their own and can be rated;
  - while the answer is still streaming, and for a turn whose stream ended with `error`, no rating buttons show;
  - a conversation opened from its URL shows each turn's saved rating pressed (`loadConversation` fixture turns with `run_id` and `rating: "down"`), and a turn with `run_id: null` shows no buttons;
  - a rating reply that arrives after the learner opened another conversation doesn't change the new conversation's turns.

  Implement:
  - `Exchange` gains `runId: string | null`, `rating: Rating | null`, `kept: boolean` (loaded turns: `kept: true`, `runId: t.run_id ?? null`, `rating: t.rating ?? null`; a new asked turn: `runId: null, rating: null, kept: false`).
  - In `run()`, on `thread`: `updateLast((e) => ({ ...e, runId: event.run_id }))`; on `done`: `updateLast((e) => ({ ...e, kept: true }))`.
  - New prop `rate = defaultRate` (`const defaultRate = (threadId: string, runId: string, rating: Rating) => rateAnswer(threadId, runId, rating);`).
  - `async function rateTurn(index: number, runId: string, rating: Rating)`: requires `threadId`; captures `forTurn = turn.current`; `const saved = await rate(threadId, runId, rating)`; if `alive.current && turn.current === forTurn`, set that turn's `rating` to `saved` (match by `runId`, not only index). Let a rejection propagate to `AnswerRating` (it shows the failure); a `SessionExpiredError` was already reported by the client.
  - Render: `const rateable = t.kept && t.runId !== null && threadId !== null;` and `const rating = rateable ? <AnswerRating rating={t.rating} onRate={(r) => rateTurn(index, t.runId!, r)} /> : null;`. When the Sources line shows, put `{rating}` as the last child of `.sources`; otherwise render `<div className={styles.ratingLine}>{rating}</div>` after the answer or decline card. `.ratingLine { display: flex; justify-content: flex-end; }`.
  - Keep comments in the file's style (one line saying why the buttons show only on kept turns: a turn that didn't end with `done` wasn't saved, so it can't be rated).

- [ ] **Step 4: Run** `cd web && npx vitest run src/api/chat.test.ts src/features/chat` → PASS, then `npm run build` → PASS.

- [ ] **Step 5: Look at it.** With the Compose app up (`docker compose --profile app ps`), or the web dev server against the API, sign in as `learner@example.com`/`learner`, ask a question, rate it, change it, reload the conversation — the rating stays. Take light and dark screenshots with Playwright (channel `chrome` too: see memory "verify web fixes in installed Chrome") and compare with `.design-shots/v0.10/chat-feedback-reason.{light,dark}.png`. If the stack can't run the new backend (the running containers are the old image), say so in the report and rely on the component tests.

- [ ] **Step 6: Commit** — subject "Show Helpful / Not helpful under each answer"; body: DESIGN.md → Chat; buttons only on kept turns; optimistic with a visible failure; the reason form is not built (PRD §10.2 has none).

---

### Task 5: PRD, module README, design brief, CONTEXT

**Files:**
- Modify: `sdd/prd.md` (status line version +1 → v2.43; a "Changes from v2.42" row; §10.2; §9.4 data model "Thread turn" row gains `rating`; the endpoint list if the PRD has one for threads)
- Modify: `backend/src/smart_tutor/tutoring/README.md` (built so far: `rate_turn`, `Rating`, `AnswerFeedback` port and `LangSmithAnswerFeedback` adapter; key classes)
- Modify: `sdd/design/brief.md` Feedback log (one row: round 18, "Claude (#227)", brief v0.11: rating built without the "What could be better?" reason form (PRD §10.2 has 👍/👎 only; a free-text reason would put learner text into feedback) and without un-pressing a rating (the ticket asks set/change/see); decision "pending the owner")
- Modify: `CONTEXT.md` (term **Rating**: a learner's 👍/👎 on a kept turn, one per turn, sent to LangSmith as `learner_rating` feedback on the turn's run; 👎 extends the trace's retention) — follow the file's term format.
- Modify: `AGENTS.md` only if it names the PRD version (it says v2.40; bump to the new version only if previous PRs kept it current — check `git log -p -3 -- AGENTS.md`).

- [ ] **Step 1:** Write the PRD changes. §10.2 becomes: "Under each kept answer or decline the learner rates it Helpful (👍) or Not helpful (👎): one rating per turn, a new one replaces it (`thread_turns.rating`; `PUT /threads/{id}/turns/{run_id}/rating`, operation `rate_turn`). The API saves it, then sends it to LangSmith as feedback `learner_rating` (score 1/0) on the turn's run, off the request (an outage is logged; the rating is kept); a 👎 extends the trace to extended retention so it can be reviewed (§10.3 item 7). The feedback carries no user id, email, or token. Admins score a weekly sample in an annotation queue; revise a judge prompt when judge–human agreement drops below ~80%." The change row summarizes the same in one paragraph in the style of the v2.40 row, and notes the reason form and un-press as not built.
- [ ] **Step 2:** README, brief, CONTEXT as listed.
- [ ] **Step 3:** Commit — subject "Document answer ratings in the PRD"; body: PRD rule (behavior change updates the PRD in the same PR).

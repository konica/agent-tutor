# Detection unsure: pick 1–3 subjects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When subject detection is unsure, the tutor asks "Which subjects is this about?", the learner picks 1–3 of their subjects and presses Continue, and the original question is answered without retyping — also after a page reload (ticket #85).

**Architecture:** The API creates the thread id before asking the agent. The agent runs the ask graph with a PostgreSQL checkpointer (`AsyncPostgresSaver`) keyed by `"{user_id}/{thread_id}"`; an unsure detection routes to a `choose_subjects` node that calls LangGraph `interrupt()`, so the question waits in the checkpoint. The API stores a *pending* thread (no subjects, title = the question) and relays a `choose_subjects` event; `POST /threads/{id}/subjects` validates the pick and resumes the agent (`Command(resume=...)`), which searches and answers the original question. The API binds the thread's subjects only when the agent's `subjects` event arrives (a conditional update), so a refused or failed resume leaves the thread unbound. The web keeps the pending thread id in `/chat?thread=<id>`; `GET /threads/{id}` restores the picker after a reload.

**Tech Stack:** Python 3.12, FastAPI, LangGraph (`interrupt`, `Command`, `langgraph-checkpoint-postgres` already a dependency), psycopg 3 pool, SQLAlchemy/Alembic; React + TypeScript + Vite + vitest.

**Spec:** GitHub issue #85; PRD `sdd/prd.md` §8 US-3 criterion 3, §9.2 Ask path step 1; mockup state `chat-detection-unsure` at tag `design-v0.7` (render: `make design-shots ROUND=v0.7 STATES="chat-detection-unsure" THEME=both`). Prior slice plan: `sdd/plans/2026-10-07-subject-detection.md`.

## Global Constraints

- The token lives only in runtime context and HTTP headers — never in graph state, checkpoints, `configurable`, prompts, logs, or traces (ADR 0007).
- Subjects are stored as `subject_id`s; names resolved at read time (`SubjectNames.names_for`, placeholder `UNNAMED_SUBJECT`).
- A thread has 0 subjects only while it waits for the learner's pick; once bound, 1–3 distinct, only ever added.
- Resume body: 1–3 distinct subject ids, all the learner's own; anything else is a 4xx and the thread stays unbound.
- Access: thread reads/resumes are scoped to the owner (`get_owned`); another learner gets 404, same as a missing thread.
- Copy (mockup): question "Which subjects is this about?", hint "Pick 1 to 3. I'll answer your question right after.", button "Continue".
- Web: rebuild with `web/src/components/` and design tokens (`DESIGN.md`); never paste prototype HTML/CSS. API calls only through `web/src/api/`; run `make api-client` (or `cd backend && uv run python -m ...` per Makefile) after route changes.
- Checks before each commit: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`; web: `cd web && npm run build && npx vitest run`.
- Commits: imperative subject, body says why, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- Two Continue presses / two tabs resuming the same thread at once → only one binds; the other gets an error event, never a second set of subjects. (Task 1 conditional bind test; Task 4 relay test with `bind_subjects` returning False.)
- Resume after the agent lost its checkpoint (agent 409) → API answers 409 with a learner-readable message, thread stays unbound. (Task 4.)
- Reload with `?thread=` of a thread that is already bound or belongs to someone else → the page falls back to a new conversation, no picker, no crash. (Task 5.)
- Agent receives a resume value it didn't offer (ids outside the learner's subjects, 0 or 4 ids) → the node refuses, stream ends with `error`, nothing is bound. (Task 2.)
- The token never appears in a checkpoint written during an interrupted run. (Task 2.)

---

## File Structure

| File | Responsibility |
|---|---|
| `backend/src/smart_tutor/tutoring/domain/thread.py` | `Thread.pending`, `awaiting_subjects`, `bind` |
| `backend/src/smart_tutor/tutoring/domain/errors.py` | `ThreadNotFoundError`, `ThreadNotPendingError` |
| `backend/src/smart_tutor/tutoring/ports/thread_repository.py` | `bind_subjects` (conditional) |
| `backend/src/smart_tutor/tutoring/adapters/sql_threads.py` | SQL `bind_subjects` |
| `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0007_pending_threads.py` | `cardinality(subject_ids) between 0 and 3` |
| `backend/src/smart_tutor/tutoring/application/conversation_service.py` | `start_thread(…, thread_id, title)`, `start_pending_thread`, `pending_thread`, `check_choice`, `bind_subjects`, `get_thread` |
| `backend/src/smart_tutor/tutoring/application/subject_detector.py` | unsure → no subjects (fallback removed) |
| `backend/src/smart_tutor/apps/agent/nodes/resolve_subjects.py` | detection; sets `choices` when unsure |
| `backend/src/smart_tutor/apps/agent/nodes/choose_subjects.py` | `interrupt()`; validates the resume value |
| `backend/src/smart_tutor/apps/agent/graph.py` | conditional edge; `checkpointer` parameter |
| `backend/src/smart_tutor/apps/agent/server.py` | `thread_id` in `/ask`, `POST /resume`, `choose_subjects` event, checkpointer in lifespan |
| `backend/src/smart_tutor/shared/adapters/postgres/checkpointer.py` | `psycopg_conninfo(url)` + `open_checkpointer(url)` async context manager |
| `backend/src/smart_tutor/apps/api/agent_client.py` | `open_answer(…, thread_id, …)`, `resume_answer`, `AgentConflictError` |
| `backend/src/smart_tutor/apps/api/routes/threads.py` | relay handles `choose_subjects`; `POST /threads/{id}/subjects`; `GET /threads/{id}` |
| `web/src/api/chat.ts` | `choose_subjects` event, `chooseSubjects`, `loadThread` |
| `web/src/features/chat/ChooseSubjects.tsx` (+ `.module.css`) | the picker card |
| `web/src/features/chat/ChatPage.tsx` | pending state, `?thread=` |
| `sdd/prd.md`, `AGENTS.md`, `backend/src/smart_tutor/tutoring/README.md` | data model note (0 subjects while pending), version bump v2.21 |

---

### Task 1: Pending threads in the tutoring module

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/domain/thread.py`, `tutoring/domain/errors.py`, `tutoring/ports/thread_repository.py`, `tutoring/adapters/sql_threads.py`, `tutoring/application/conversation_service.py`, `tutoring/application/__init__.py` (exports), `tutoring/application/subject_detector.py`
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0007_pending_threads.py`
- Modify fakes: `backend/tests/fakes/tutoring.py` (`InMemoryThreads.bind_subjects`)
- Test: `backend/tests/unit/tutoring/test_thread.py` (create or extend existing thread test — `grep -rl "Thread.start" tests/unit`), `tests/unit/tutoring/test_conversation_service.py`, `tests/unit/tutoring/test_subject_detector.py`, `tests/integration/tutoring/` (SQL repo test file that exists there)

**Interfaces:**
- Produces:
  - `Thread.pending(thread_id: ThreadId, user_id: UserId, title: str, now: datetime) -> Thread` (subject_ids `()`)
  - `Thread.awaiting_subjects: bool` property (`not self.subject_ids`)
  - `Thread.start(thread_id, user_id, subject_ids, now, title: str | None = None)`
  - `ThreadRepository.bind_subjects(thread_id: ThreadId, user_id: UserId, subject_ids: Sequence[SubjectId]) -> bool` — sets subjects only if the thread is the user's and has none; True when it did.
  - `ThreadNotFoundError`, `ThreadNotPendingError` in `tutoring.domain.errors`, exported from `tutoring.application`.
  - `ConversationService.start_thread(user_id, subject_ids, thread_id: ThreadId, title: str) -> Thread`
  - `ConversationService.start_pending_thread(user_id, thread_id: ThreadId, title: str) -> Thread`
  - `ConversationService.get_thread(user_id, thread_id) -> Thread` (raises `ThreadNotFoundError`)
  - `ConversationService.pending_thread(user_id, thread_id) -> Thread` (raises `ThreadNotFoundError`, `ThreadNotPendingError`)
  - `ConversationService.check_choice(user_id, subject_ids: Sequence[SubjectId]) -> None` (raises `ThreadSubjectsError` unless 1–3 distinct and all the learner's)
  - `ConversationService.bind_subjects(user_id, thread_id, subject_ids) -> bool` (runs `check_choice`, then the repository's conditional bind)
  - `SubjectDetector.detect` returns `Detection((), unsure=True, scores=...)` when unsure.

- [ ] **Step 1: Write failing domain tests**

```python
def test_a_pending_thread_has_no_subjects_until_bound() -> None:
    t = Thread.pending(ThreadId("t1"), UserId("ada"), "How do these methods handle long documents?", NOW)
    assert t.subject_ids == () and t.awaiting_subjects and t.title.startswith("How do")
    assert t.last_learner_message_at == NOW


def test_start_keeps_the_title() -> None:
    t = Thread.start(ThreadId("t1"), UserId("ada"), [SubjectId("s1")], NOW, title="Q?")
    assert t.title == "Q?" and not t.awaiting_subjects
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/unit/tutoring -q` → FAIL (no `pending`).

- [ ] **Step 3: Implement domain**

```python
    @classmethod
    def start(cls, thread_id, user_id, subject_ids, now, title: str | None = None) -> "Thread":
        """A new thread with its first question asked now."""
        if not 1 <= len(subject_ids) <= MAX_SUBJECTS or len(set(subject_ids)) != len(subject_ids):
            raise ThreadSubjectsError("A thread starts with 1 to 3 distinct subjects")
        return cls(thread_id, user_id, tuple(subject_ids), now, title=title, last_learner_message_at=now)

    @classmethod
    def pending(cls, thread_id: ThreadId, user_id: UserId, title: str, now: datetime) -> "Thread":
        """A new thread whose first question waits for the learner to pick its subjects (detection was unsure)."""
        return cls(thread_id, user_id, (), now, title=title, last_learner_message_at=now)

    @property
    def awaiting_subjects(self) -> bool:
        return not self.subject_ids
```

Errors (`errors.py`): `class ThreadNotFoundError(Exception): """No such thread for this learner (another learner's thread looks the same)."""` and `class ThreadNotPendingError(Exception): """The thread already has its subjects."""`.

- [ ] **Step 4: Repository + migration + fake.** Port:

```python
    @abstractmethod
    def bind_subjects(self, thread_id: ThreadId, user_id: UserId, subject_ids: Sequence[SubjectId]) -> bool:
        """Give a pending thread of this learner its subjects; False when it isn't theirs or already has subjects."""
```

SQL (`sql_threads.py`), one conditional statement so two concurrent resumes can't both bind:

```python
    def bind_subjects(self, thread_id, user_id, subject_ids) -> bool:
        with self._engine.begin() as conn:
            result = conn.execute(
                threads.update()
                .where(
                    threads.c.thread_id == thread_id,
                    threads.c.user_id == user_id,
                    func.cardinality(threads.c.subject_ids) == 0,
                )
                .values(subject_ids=list(subject_ids))
            )
        return result.rowcount == 1
```

Note `cardinality` of an empty array is 0 (`array_length` would be NULL). Migration `0007_pending_threads.py` (revises `0006`): drop constraint `threads_subject_count`, recreate as `cardinality(subject_ids) between 0 and 3`; downgrade restores `between 1 and 3`. `InMemoryThreads.bind_subjects`: same semantics on the dict.

- [ ] **Step 5: Service tests then code.** Tests in `test_conversation_service.py` (reuse its existing fixtures/fakes):
  - `start_pending_thread` stores a thread with no subjects and the title.
  - `pending_thread`: another learner's id → `ThreadNotFoundError`; bound thread → `ThreadNotPendingError`.
  - `check_choice`: `[]`, 4 ids, duplicate ids, an id that isn't the learner's → `ThreadSubjectsError`; 1–3 own ids → None.
  - `bind_subjects`: binds once (True), second call False; another learner → False; invalid choice → `ThreadSubjectsError` and thread still pending.

```python
    def start_thread(self, user_id, subject_ids, thread_id: ThreadId, title: str) -> Thread:
        self.check_choice(user_id, subject_ids)
        thread = Thread.start(thread_id, user_id, subject_ids, self._clock.now(), title=title)
        self._threads.add(thread)
        return thread

    def start_pending_thread(self, user_id, thread_id, title) -> Thread:
        """A thread whose first question waits for the learner's pick (detection unsure)."""
        self.subjects_for_new_thread(user_id)  # NoDocumentsError like start_thread
        thread = Thread.pending(thread_id, user_id, title, self._clock.now())
        self._threads.add(thread)
        return thread

    def get_thread(self, user_id, thread_id) -> Thread:
        thread = self._threads.get_owned(thread_id, user_id)
        if thread is None:
            raise ThreadNotFoundError("No such conversation")
        return thread

    def pending_thread(self, user_id, thread_id) -> Thread:
        thread = self.get_thread(user_id, thread_id)
        if not thread.awaiting_subjects:
            raise ThreadNotPendingError("This conversation already has its subjects")
        return thread

    def check_choice(self, user_id, subject_ids) -> None:
        if not 1 <= len(subject_ids) <= MAX_SUBJECTS or len(set(subject_ids)) != len(subject_ids):
            raise ThreadSubjectsError("Pick 1 to 3 subjects")
        if not set(subject_ids) <= set(self.subjects_for_new_thread(user_id)):
            raise ThreadSubjectsError("A thread's subjects are the learner's own")

    def bind_subjects(self, user_id, thread_id, subject_ids) -> bool:
        self.check_choice(user_id, subject_ids)
        return self._threads.bind_subjects(thread_id, user_id, subject_ids)
```

The existing `start_thread` callers (only `apps/api/routes/threads.py`) are updated in Task 4; until then update the call minimally so tests pass (generate `ThreadId(str(uuid.uuid4()))` at the call site and pass `title=body.question`), and fix existing service tests for the new signature.

- [ ] **Step 6: Detector.** Replace `test_unsure_falls_back_to_the_best_subject` (and the empty-scores one) with tests asserting `detection.subject_ids == ()` and `detection.unsure`. Code: `return Detection((), unsure=True, scores=scores)`; update the `Detection` docstring ("`unsure`: none bound; the learner picks").

- [ ] **Step 7: Integration test** (marker `integration`, in the existing SQL threads test module under `tests/integration/tutoring/`): add a pending thread, `bind_subjects` → True and row has subjects; second bind → False; other user → False. Run with `make up && make migrate` then `uv run pytest -m integration tests/integration/tutoring -q` if the Compose stack is available; otherwise note it in the report.

- [ ] **Step 8: Full backend checks, commit** — "Keep a thread pending until the learner picks its subjects".

---

### Task 2: The agent graph pauses for the learner's pick

**Files:**
- Modify: `backend/src/smart_tutor/apps/agent/state.py`, `apps/agent/nodes/resolve_subjects.py`, `apps/agent/graph.py`
- Create: `backend/src/smart_tutor/apps/agent/nodes/choose_subjects.py`
- Test: `backend/tests/unit/apps/agent/test_graph.py`, `tests/unit/apps/agent/test_no_token_in_traces.py`

**Interfaces:**
- Consumes: `SubjectDetector.detect` returning `subject_ids == ()` when unsure (Task 1).
- Produces:
  - `AskState` gains `choices: list[str]` (subject ids offered to the learner; all the learner's subjects in `learner_subjects` order).
  - `build_graph(retriever_for, model, policy, checkpointer: BaseCheckpointSaver | None = None) -> AskGraph`
  - Node names: `resolve_subjects` (detect), `choose_subjects` (interrupt), `search`, `answer`.
  - Interrupt value: `{"subject_ids": [<choices>]}`. Resume value: `{"subject_ids": [<1–3 ids>]}`.
  - The `choose_subjects` node's update: `{"subject_ids": [...], "subject_names": [...]}` — the same shape `resolve_subjects` returns when bound.

- [ ] **Step 1: Failing graph tests** (use `langgraph.checkpoint.memory.InMemorySaver`, `langgraph.types.Command`; reuse the module's fake retriever/model helpers and `TWO_SUBJECTS`-style input with chunks giving an unsure score, e.g. both subjects 0.6 and 0.58 with policy `DetectionPolicy(0.5, 0.125, 0.0)`):

```python
async def test_unsure_pauses_for_the_learners_pick_then_answers_the_original_question() -> None:
    retriever = FakeRetriever(UNSURE_CHUNKS)
    graph = build_graph(lambda token: retriever, fake_chat_model(AIMessage("Answer [1].")), POLICY, InMemorySaver())
    config = {"configurable": {"thread_id": "ada/t1"}}
    ctx = AgentContext(access_token="t")

    first = await graph.ainvoke(UNSURE_INPUT, config=config, context=ctx)
    [pause] = first["__interrupt__"]
    assert pause.value == {"subject_ids": ["s1", "s2"]}
    searches_before = len(retriever.calls)

    out = await graph.ainvoke(Command(resume={"subject_ids": ["s2"]}), config=config, context=ctx)
    assert out["subject_ids"] == ["s2"] and out["subject_names"] == ["B"]
    assert out["answer"] == "Answer [1]."
    # Resuming searched only the picked subject for the answer; detection did not run again.
    assert retriever.calls[searches_before:] == [(UNSURE_INPUT["question"], ["s2"], 5)]


@pytest.mark.parametrize("picked", [[], ["s1", "s2", "s3", "s4"], ["zz"], ["s1", "s1"], "s1", None])
async def test_a_pick_outside_the_choices_is_refused(picked: object) -> None:
    ...  # first ainvoke pauses as above; resume with {"subject_ids": picked} raises InvalidPickError
    # and graph.aget_state(config).interrupts is still non-empty (still waiting)
```

Also: a learner with one subject, or a bound detection, never interrupts (existing tests keep passing with or without a checkpointer).

- [ ] **Step 2: Run** `uv run pytest tests/unit/apps/agent -q` → FAIL.

- [ ] **Step 3: Implement.** `resolve_subjects` when unsure returns `{"subject_ids": [], "subject_names": [], "choices": list(learner)}`. New node:

```python
"""Choose subjects (PRD §9.2 step 1, US-3): detection was unsure, so the graph waits for the learner's pick.

The question stays in the checkpoint; the API resumes with Command(resume={"subject_ids": [...]}) (1–3 of the choices).
"""

from langgraph.types import interrupt

from smart_tutor.apps.agent.state import AskState
from smart_tutor.tutoring.domain.thread import MAX_SUBJECTS


class InvalidPickError(ValueError):
    """The resume value isn't 1–3 distinct subjects from the choices offered."""


def choose_subjects(state: AskState) -> AskState:
    choices = state["choices"]
    value = interrupt({"subject_ids": choices})
    picked = value.get("subject_ids") if isinstance(value, dict) else None
    if (
        not isinstance(picked, list)
        or not all(isinstance(s, str) for s in picked)
        or not 1 <= len(picked) <= MAX_SUBJECTS
        or len(set(picked)) != len(picked)
        or not set(picked) <= set(choices)
    ):
        raise InvalidPickError("the pick must be 1 to 3 distinct subjects from the choices")
    return {"subject_ids": picked, "subject_names": [state["learner_subjects"][s] for s in picked]}
```

Graph:

```python
        .add_node("choose_subjects", choose_subjects)
        .add_edge(START, "resolve_subjects")
        .add_conditional_edges("resolve_subjects", lambda s: "search" if s["subject_ids"] else "choose_subjects",
                               ["search", "choose_subjects"])
        .add_edge("choose_subjects", "search")
        ...
        .compile(checkpointer=checkpointer)
```

Update the graph module docstring (no longer "no checkpointer"); `MAX_SUBJECTS` import from `tutoring.domain.thread` — check import-linter allows `apps` → `tutoring.domain`; if not, import it via `tutoring.application` (export it there).

- [ ] **Step 4: Token never in checkpoints.** In `test_no_token_in_traces.py` add a test: run the unsure input with `InMemorySaver()` and the token in context, then `json.dumps([c async for c in saver.alist(None)], default=str)` and the trace payloads contain no `TOKEN`; positive control: the question text *is* in the dumped checkpoints.

- [ ] **Step 5: Checks, commit** — "Pause the ask graph for the learner's pick when detection is unsure".

---

### Task 3: Agent server: thread-keyed checkpoints, `choose_subjects` event, `POST /resume`

**Files:**
- Create: `backend/src/smart_tutor/shared/adapters/postgres/checkpointer.py`
- Modify: `backend/src/smart_tutor/apps/agent/server.py`
- Test: `backend/tests/unit/apps/agent/test_server.py`, `tests/integration/shared/test_checkpointer.py` (marker `integration`)

**Interfaces:**
- Consumes: `build_graph(..., checkpointer)`, interrupt/resume shapes from Task 2, `InvalidPickError`.
- Produces (agent HTTP contract used by Task 4):
  - `POST /ask` body `{"thread_id": <uuid str>, "question", "learner_subjects": [{subject_id, name}]}` (extra fields forbidden). Events: `subjects` {"subject_ids"} then answer events; **or** `choose_subjects` {"subject_ids": [<choices>]} then `done`; or `error`.
  - `POST /resume` body `{"thread_id": <uuid str>, "subject_ids": [1–3 str]}`. 409 JSON `{"detail": "Nothing is waiting for subjects in this thread"}` (before streaming) when the checkpoint has no pending interrupt; otherwise 200 SSE: `subjects` (the picked ids) then `delta`*, `citations`, `done`; an invalid pick → `error` {"code": "unavailable"}.
  - Checkpoint key: `config = {"configurable": {"thread_id": f"{principal.user_id}/{thread_id}"}}` — derived from the verified token's subject, so a learner can only reach their own checkpoints.
  - `psycopg_conninfo(sqlalchemy_url: str) -> str` (drops the `+psycopg` driver: `make_url(url).set(drivername="postgresql").render_as_string(hide_password=False)`).
  - `open_checkpointer(database_url: str) -> AbstractAsyncContextManager[AsyncPostgresSaver]`: `AsyncConnectionPool(conninfo, open=False, kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})`, `await pool.open()`, `saver = AsyncPostgresSaver(pool)`, `await saver.setup()` (creates its tables idempotently; the app role owns the database), yield, close pool.

- [ ] **Step 1: Failing server tests** (extend `test_server.py`, which builds the app with `create_app(settings, verifier=..., graph=...)`; build the graph with `InMemorySaver()` and fake retriever chunks that make detection unsure):
  - `/ask` with unsure chunks streams exactly `choose_subjects` {"subject_ids": ["s1","s2"]} then `done`; no `delta`.
  - `/ask` without `thread_id` → 422.
  - `/resume` for that thread with `["s2"]` streams `subjects` {"subject_ids": ["s2"]}, `delta`…, `citations`, `done`.
  - `/resume` when nothing waits (fresh thread id) → 409.
  - another learner's token resuming the same `thread_id` → 409 (their key `"bob/<id>"` has nothing waiting) and ada's thread still waits.
  - `/resume` with `["zz"]` → stream ends with `error` code `unavailable`, and a later valid resume still works.
  - `/resume` body with 0 or 4 ids → 422.

- [ ] **Step 2: Run** → FAIL.

- [ ] **Step 3: Implement.** Refactor `answer_events(graph, graph_input, config, token)` so `/ask` passes the initial state and `/resume` passes `Command(resume={"subject_ids": body.subject_ids})`. In the stream loop, emit `subjects` for an update from `resolve_subjects` **only when its `subject_ids` is non-empty**, and also for an update from `choose_subjects`; for `part["data"]` containing `"__interrupt__"`, emit `sse("choose_subjects", {"subject_ids": interrupts[0].value["subject_ids"]})`. `InvalidPickError` falls into the generic `except Exception` → `error` unavailable (log the reason, no token). `/resume` handler: `state = await graph.aget_state(config)`; `if not state.interrupts: raise HTTPException(409, ...)`. Both handlers need the principal: use `principal: CurrentPrincipal` (from `shared.adapters.auth.bearer`) instead of `dependencies=[...]`. Lifespan: when `graph is None`, `async with open_checkpointer(settings.database_url) as saver:` build the graph with it (keep the existing `verifier is not None` early path for tests). Update the module docstring with both endpoints' events.

- [ ] **Step 4: Integration test** `tests/integration/shared/test_checkpointer.py` (marker `integration`): with `open_checkpointer(Settings().database_url)`, run the unsure graph to its interrupt; open a **second** `open_checkpointer` + new graph (simulates an agent restart) and resume → answers. Also a unit test for `psycopg_conninfo` (`postgresql+psycopg://u:p%40x@h:1/db` → `postgresql://u:p%40x@h:1/db`).

- [ ] **Step 5: Checks, commit** — "Keep a pending question in the agent's Postgres checkpointer and resume it".

---

### Task 4: API: pending threads, resume, read a thread

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/agent_client.py`, `apps/api/routes/threads.py`, `backend/tests/fakes/api.py` (if needed)
- Test: `backend/tests/unit/apps/api/test_thread_routes.py`, `tests/isolation/test_threads.py`, `tests/unit/apps/api/test_openapi_snapshot.py` (refresh snapshot as that test documents)
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*` via `make api-client` (read the Makefile target and run its command directly if `make` is missing)

**Interfaces:**
- Consumes: Task 1 service methods; Task 3 agent contract.
- Produces (HTTP contract for Task 5):
  - `POST /threads` (unchanged request). Stream opens with either `thread` {"thread_id", "subjects": [{subject_id, name}]} (as today) **or** `choose_subjects` {"thread_id", "question", "subjects": [{subject_id, name}]} (the agent's choices, named) followed by `done`.
  - `POST /threads/{thread_id}/subjects`, operation_id `choose_thread_subjects`, body `{"subject_ids": [1–3 str]}` (`extra="forbid"`, pydantic `min_length=1, max_length=3`). Errors before streaming: 404 not found/not owner; 409 already bound (`ThreadNotPendingError`) or agent has nothing waiting; 422 invalid pick (`ThreadSubjectsError`, also duplicates/not the learner's). 200 SSE: `thread` (bound subjects, named) then `delta`*, `citations`, `done`.
  - `GET /threads/{thread_id}`, operation_id `get_thread`, response model `ThreadResponse {thread_id: str, question: str, subjects: list[SubjectResponse-like {subject_id, name}], awaiting_subjects: bool}`; 404 for others. `question` is the thread's title.
  - `AgentClient.open_answer(access_token, thread_id, question, learner_subjects)`; `AgentClient.resume_answer(access_token, thread_id, subject_ids) -> AgentAnswer`; `AgentConflictError` raised on agent 409.

- [ ] **Step 1: Failing route tests** (`test_thread_routes.py`; fake agent handlers return canned SSE):
  - `POST /threads` sends `thread_id` (a UUID) to the agent; on a `subjects` opening, the stored thread has that id and `title == question`.
  - On a `choose_subjects` opening (`event: choose_subjects\ndata: {"subject_ids": [GENERAL, S2]}` + `done`), a pending thread is stored (no subjects, title = question) and the client gets `choose_subjects` {"thread_id", "question", "subjects": [named]} then `done`.
  - `POST /threads/{id}/subjects` with `[S2]` on a pending thread: the agent receives `POST /resume` `{"thread_id": id, "subject_ids": [S2]}` with the same bearer token; agent stream `subjects [S2]` + answer → client gets `thread` {"thread_id", "subjects": [{S2, name}]} + answer; the stored thread is bound to `[S2]`.
  - Refusals, each asserting the agent was **not** called and the thread is still pending: `[]` → 422, 4 ids → 422, an id not the learner's → 422, duplicate ids → 422, unknown thread → 404, bound thread → 409.
  - Agent 409 on resume → API 409, thread pending.
  - Agent stream that opens with `subjects` ids different from the pick, or `bind_subjects` returns False (already bound by a concurrent resume) → client gets the unavailable `error` event and nothing else; thread binding unchanged.
  - `GET /threads/{id}`: pending → `awaiting_subjects: true, subjects: []`; bound → named subjects, `false`.

- [ ] **Step 2: Isolation tests** (`tests/isolation/test_threads.py`, following its existing two-learner setup): bob `GET /threads/{ada's pending id}` → 404 and the response doesn't contain ada's question; bob `POST /threads/{id}/subjects` with bob's own subject → 404, the agent is never called, ada's thread is still pending.

- [ ] **Step 3: Run** → FAIL. **Step 4: Implement.** In `routes/threads.py`: generate `thread_id = ThreadId(str(uuid.uuid4()))` before `open_answer`; generalise `_opening` to accept either opening: `subjects` → `start(ids)` (existing), `choose_subjects` → `pending(ids)` which calls `conversations.start_pending_thread` and returns the `choose_subjects` event with named choices (ignore choice ids not in `named` — log a warning). Keep `_relay` byte-forwarding for the rest. For resume, the opening `subjects` → `bind(ids)`: require `ids == body.subject_ids` (as lists), call `conversations.bind_subjects`; False or error → None (→ unavailable event). Names for the resume `thread` event come from `subjects.names_for(user, learner_subjects)` with the `UNNAMED_SUBJECT` placeholder — factor the existing naming loop into `_named_subjects(conversations, subjects, user_id) -> dict[str, str]` and reuse it in all three routes. Run blocking service calls with `run_in_threadpool` as the existing route does. `AgentClient`: share the request/response handling between `/ask` and `/resume` in one private `_open(path, token, json)`; map 409 → `AgentConflictError`.

- [ ] **Step 5: Regenerate the web client** (`make api-client`) and refresh the OpenAPI snapshot test; `cd web && npm run build` must still pass.

- [ ] **Step 6: Checks, commit** — "Ask the learner for subjects when detection is unsure, and resume with their pick".

---

### Task 5: Web picker: choose 1–3 subjects, Continue, survive reload

**Files:**
- Modify: `web/src/api/chat.ts`, `web/src/api/chat.test.ts`, `web/src/features/chat/ChatPage.tsx`, `ChatPage.module.css`, `ChatPage.test.tsx`
- Create: `web/src/features/chat/ChooseSubjects.tsx`, `ChooseSubjects.module.css`, `ChooseSubjects.test.tsx`

**Interfaces:**
- Consumes: Task 4 HTTP contract (generated types `ChooseThreadSubjectsData`, `GetThreadResponse`/`ThreadResponse`, etc. — use the names the generator produced).
- Produces:
  - `ChatEvent` adds `{ type: "choose_subjects"; thread_id: string; question: string; subjects: Subject[] }`.
  - `chooseSubjects(threadId: string, subjectIds: string[], apiClient?): AsyncGenerator<ChatEvent>` — same plain-request SSE approach and error mapping as `askInNewThread` (401 → `SessionExpiredError`; 4xx with a `detail` string → `AskRefusedError(detail)`; else `Error`).
  - `loadThread(threadId: string): Promise<ThreadView | null>` — `null` on 404.
  - `<ChooseSubjects subjects={Subject[]} busy={boolean} onContinue={(ids: string[]) => void} />`.
  - `ChatPage` props gain `choose?: (threadId, ids) => AsyncIterable<ChatEvent>` and `loadPending?: (threadId) => Promise<ThreadView | null>` for tests.

- [ ] **Step 1: Look at the mockup** — `.design-shots/v0.7/chat-detection-unsure.{light,dark}.png` (render with `make design-shots ROUND=v0.7 STATES="chat-detection-unsure" THEME=both`). The card sits under the learner's question bubble, labelled "Smart Tutor" with the brand mark, title "Which subjects is this about?", hint "Pick 1 to 3. I'll answer your question right after.", one toggle chip per subject (hue by subject id, as `SubjectChip`), and a secondary "Continue" button. Header title = the question; description "Subjects appear after your first question." Read `DESIGN.md` (chips, buttons, focus, accessibility) and reuse `SubjectChip`, `Button`, `BrandMark`; check how the library subject picker (`grep -rn "aria-pressed" web/src`) renders selectable chips and reuse that pattern.

- [ ] **Step 2: Failing `ChooseSubjects` tests** (testing-library + user-event, as existing tests do):
  - renders a group named "Which subjects is this about?" with one toggle button per subject (`aria-pressed="false"`), Continue disabled.
  - selecting 1 enables Continue; selecting 3 disables the other unselected chips; deselecting one re-enables them.
  - keyboard: Tab to a chip, Space/Enter toggles it, Tab to Continue, Enter calls `onContinue` with the ids in selection order.
  - `busy` disables everything.

- [ ] **Step 3: Implement `ChooseSubjects`.** `<section aria-labelledby=...>` card; chips are `<button type="button" aria-pressed>` containing `SubjectChip` visuals (or SubjectChip if it supports a pressed/button mode); `role="group"` with `aria-labelledby` the question heading and `aria-describedby` the hint; when 3 are selected, unselected chips get `disabled`. Styles only from tokens.

- [ ] **Step 4: Failing `chat.ts` tests**: `choose_subjects` event parsing; `chooseSubjects` posts to `/threads/{id}/subjects` with `{subject_ids}` and yields events; 422/409 with detail → `AskRefusedError`; `loadThread` → null on 404.

- [ ] **Step 5: Failing `ChatPage` tests:**
  - an ask stream yielding `choose_subjects` shows the question bubble, the picker with those subjects, sets `?thread=<id>` in the URL (render inside a `MemoryRouter`; read the location via a small test component), and disables the question input (the picker is the only action while the thread waits).
  - picking + Continue calls `choose(threadId, ids)`, the header gets the chips from the `thread` event, the answer streams, citations show, and `?thread` is removed.
  - Continue failure (`AskRefusedError`) shows its message and keeps the picker (thread still pending).
  - initial render at `/chat?thread=t1` with `loadPending` → `{awaiting_subjects: true, question, ...}` shows the question and picker (with the learner's subjects from `loadSubjects`); with `null` or `awaiting_subjects: false` → the normal new-conversation view and `?thread` removed.

- [ ] **Step 6: Implement `ChatPage`.** Use `useSearchParams` (react-router v8, already used by the app — check how `LibraryPage` imports it). `Exchange` gains `pending: { threadId: string; subjects: Subject[] } | null`. Extract the event loop of `submit` into a `consume(stream)` helper reused by ask and Continue (handles `thread`, `choose_subjects`, `delta`, `citations`, `error`, the ended check). On `choose_subjects`: set `pending`, `setSearchParams({thread: id}, {replace: true})`. On Continue: clear problem, `consume(choose(threadId, ids))`; on the `thread` event clear `pending` and remove the param. While `pending`, render `<ChooseSubjects>` in the answer region and disable the question form.

- [ ] **Step 7: Compare with the mockup** — run the web app against the stack if available (`docker compose --profile app up -d` or the host `make` targets) or at least screenshot the component test view; check both themes visually against `.design-shots/v0.7/chat-detection-unsure.*.png`. Record deliberate differences (e.g. tokens counter, citations toggle not in scope) for the PR description.

- [ ] **Step 8: Checks** `cd web && npm run build && npx vitest run`; commit — "Pick the subjects when detection is unsure; the question is answered right after".

---

### Task 6: Docs

**Files:** `sdd/prd.md`, `AGENTS.md`, `backend/src/smart_tutor/tutoring/README.md`, `CONTEXT.md` (Thread term)

- [ ] **Step 1:** PRD §9.4 Thread row: `subject_ids[]` "(1–3, append-only; empty only while the first question waits for the learner to pick its subjects)"; `title` "(the first question)". §9.2 step 1: "…ask "Which subjects is this about?" (pick 1–3): the graph pauses (LangGraph interrupt) with the question in the PostgreSQL checkpointer, keyed by learner and thread, and resumes with the pick." Bump status line to **v2.21** with a short change note in the version history if the PRD keeps one (check its top table), and AGENTS.md "`sdd/prd.md` (v2.20)" → v2.21.
- [ ] **Step 2:** tutoring README: pending threads and `bind_subjects`. CONTEXT.md Thread: "…or picked by the learner when detection is unsure".
- [ ] **Step 3:** Commit — "Record pending threads and the checkpointed pick in the PRD (v2.21)".

# Follow-up Eval Examples Implementation Plan (#214)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gate follow-up questions with an eval: multi-turn conversations from the seed corpus run against the ask graph with capped history and are scored on retrieval relevance, answer relevance, and correct decline on drift.

**Architecture:** An ask example may carry `inputs.history` (earlier questions). The ask target replays the conversation: it asks each earlier question in turn and passes the turns so far, capped the way the API caps them (`history_turns`, `history_answer_chars`), to the next ask; only the last turn is scored. Two new evaluator modules score `retrieval_relevance` (Qwen judge per chunk, averaged) and `decline_correctness.*` (code, from the decline code). An evaluator that doesn't apply to an example returns a "not applicable" result that the runner leaves out of the metric instead of counting it as 0.

**Tech Stack:** Python 3.13, LangGraph, LangSmith `aevaluate` (langsmith 0.14.3), openevals `create_async_llm_as_judge`, pytest (asyncio auto).

**Spec:** GitHub issue #214; PRD `sdd/prd.md` §9.2 (Ask path, steps 1–3) and §10.1 (evaluators); ADR 0015 (history).

## Global Constraints

- Unit tests use fakes only (`backend/tests/fakes/`); real Bedrock only in evals.
- Evaluators return `{"key": "<thresholds.yaml metric>", "score", "comment"}`; a nested metric uses its dotted path (`decline_correctness.correctly_declined`).
- Judges: `ChatRole.JUDGE` (Qwen, temperature 0) through openevals, a 0–1 score and a short reason; rubric files are Python format strings with only `{inputs}`, `{outputs}`, `{reference_outputs}`.
- The history cap is the API's: the last `Settings.history_turns` turns (0 sends none), each answer (or decline message) cut to `Settings.history_answer_chars` and ending with "…" when cut.
- Tokens never appear in target outputs.
- Checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`.

## Review Focus

- `history_turns = 0`: no history is sent (beware `turns[-0:]` returning everything) — test in Task 2.
- A drift example whose earlier turn was itself declined: the decline message becomes that turn's history answer — test in Task 2.
- Token expires mid-conversation: the whole conversation is replayed once after signing in again, and the trajectory holds only the final turn's searches — test in Task 2.
- A covered example whose run failed (no `chunks` in outputs) scores 0 on retrieval relevance, not "not applicable" — test in Task 4.
- An example where every evaluator of a metric reported "not applicable" leaves the metric "not run", not failed — test in Task 1.

---

### Task 1: Runner leaves "not applicable" results out of a metric

**Files:**
- Modify: `backend/evals/suite.py` (add `NOT_APPLICABLE`, `not_applicable()`)
- Modify: `backend/evals/run.py:63-68`
- Test: `backend/tests/unit/evals/test_run.py`

**Interfaces:**
- Produces: `evals.suite.NOT_APPLICABLE = "n/a"`; `evals.suite.not_applicable(key: str, why: str) -> dict[str, Any]` returning `{"key": key, "score": None, "value": NOT_APPLICABLE, "comment": why}`.

- [ ] **Step 1: Failing tests** in `test_run.py`:

```python
def _declines(inputs: dict[str, Any]) -> dict[str, Any]:
    if inputs["question"] == "a":
        return not_applicable("decline_correctness.correctly_declined", "covered")
    return {"key": "decline_correctness.correctly_declined", "score": 1, "comment": "declined"}


async def test_a_not_applicable_result_is_left_out_of_its_metric() -> None:
    group = DatasetSuites("ask", make_target, (_declines,))
    scores, _ = await run_split(published(), [group], "smoke", load=lambda key: ASK)
    assert scores == {"decline_correctness.correctly_declined": [1]}


async def test_a_metric_that_applied_to_no_example_is_not_run() -> None:
    group = DatasetSuites("ask", make_target, (lambda inputs: not_applicable("answer_relevance", "n/a"),))
    scores, _ = await run_split(published(), [group], "smoke", load=lambda key: ASK)
    assert scores == {}
```

(`from evals.suite import DatasetSuites, Suite, not_applicable`.)

- [ ] **Step 2:** `uv run pytest tests/unit/evals/test_run.py -q` → FAIL (`not_applicable` missing).
- [ ] **Step 3: Implement.** In `suite.py`:

```python
NOT_APPLICABLE = "n/a"  # an evaluator's `value` for an example its metric doesn't cover; the runner leaves it out


def not_applicable(key: str, why: str) -> dict[str, Any]:
    return {"key": key, "score": None, "value": NOT_APPLICABLE, "comment": why}
```

In `run.py` replace the rows/extend block:

```python
        rows = [row["evaluation_results"]["results"] async for row in results]
        # An evaluator that raised leaves its key out of that row: count it as unscored, not as absent, or the
        # gate would average only the survivors. A result marked not applicable is left out of its metric.
        for key in {r.key for row in rows for r in row}:
            for row in rows:
                found = [r for r in row if r.key == key]
                if not found:
                    scores[key].append(None)
                elif found[0].value != NOT_APPLICABLE:
                    scores[key].append(found[0].score)
        scores = defaultdict(list, {k: v for k, v in scores.items() if v})
```

(Keep `scores` a `defaultdict`; drop keys left empty so a metric that applied nowhere stays "not run".)
- [ ] **Step 4:** tests pass, including the existing `test_an_example_whose_evaluator_raised_counts_as_unscored`.
- [ ] **Step 5:** README "Add a suite": one sentence — an evaluator returns `not_applicable(key, why)` (evals.suite) for an example its metric doesn't cover. Commit "Leave not-applicable eval results out of their metric".

### Task 2: Ask target replays a conversation with capped history

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/domain/turn.py` (add `history_turn`, use it in `Turn.as_history`)
- Modify: `backend/src/smart_tutor/tutoring/application/__init__.py` (export `history_turn`)
- Modify: `backend/evals/targets.py`
- Test: `backend/tests/unit/evals/test_targets.py`, `backend/tests/unit/tutoring/` (existing `as_history` tests must still pass)

**Interfaces:**
- Produces: `history_turn(question: str, answer: str, max_answer_chars: int) -> HistoryTurn`.
- Produces: `AskTarget(learners, retriever_for, model, answer_floor, history_turns: int = 5, history_answer_chars: int = 2000)`; outputs gain `"history": [{"question", "answer"}]` (the turns the last ask received, after the cap) and `"chunks": [{"chunk_id", "document_id", "document_title", "page", "score", "text"}]` (what the last search found, the chunks the model is given unless it declines). `trajectory` holds only the last turn's searches.

- [ ] **Step 1: Failing tests** in `test_targets.py` (`_target` gains `**kw` passthrough of `history_turns`, `history_answer_chars`):

```python
CONVERSATION = {**ASK, "history": ["What is ReAct?"], "question": "What are its limitations?"}


async def test_a_conversation_replays_its_earlier_questions_and_scores_the_last() -> None:
    retriever = FakeRetriever(CHUNKS)
    out = await _target(retriever)(CONVERSATION)
    assert [c[0] for c in retriever.calls] == ["What is ReAct?", "What is ReAct?\nWhat are its limitations?"]
    assert out["history"] == [{"question": "What is ReAct?", "answer": "ReAct interleaves reasoning and acting [1]."}]
    assert [c["query"] for c in out["trajectory"]] == ["What is ReAct?\nWhat are its limitations?"]
    assert out["chunks"][0] == {"chunk_id": "c1", "document_id": "d1", "document_title": "ReAct", "page": 3,
                                "score": 0.9, "text": "ReAct interleaves thoughts and actions."}


async def test_history_is_capped_like_the_api_caps_it() -> None:
    out = await _target(FakeRetriever(CHUNKS), history_turns=1, history_answer_chars=10)(
        {**ASK, "history": ["q1", "q2"], "question": "q3"})
    assert out["history"] == [{"question": "q2", "answer": "ReAct int…"}]


async def test_no_history_turns_sends_no_history() -> None:
    retriever = FakeRetriever(CHUNKS)
    out = await _target(retriever, history_turns=0)(CONVERSATION)
    assert out["history"] == [] and retriever.calls[-1][0] == "What are its limitations?"


async def test_a_declined_earlier_turn_is_history_with_its_decline_message() -> None:
    out = await _target(FakeRetriever([]), reply=None)({**ASK, "history": ["q1"], "question": "q2"})
    assert out["history"] == [{"question": "q1", "answer": NO_DOCUMENTS_DECLINE}]


async def test_an_expired_token_replays_the_whole_conversation_once() -> None:
    learners, retriever = FakeLearners(tokens=("old", "new")), FakeRetriever(CHUNKS)
    def retriever_for(token: str) -> Retriever:
        return FakeRetriever(error=UnauthenticatedError("x")) if token == "old" else retriever
    out = await _target(retriever, learners=learners, retriever_for=retriever_for)(CONVERSATION)
    assert learners.sign_ins == 1 and len(retriever.calls) == 2 and len(out["trajectory"]) == 1
```

Also a domain test: `history_turn("q", "abcdef", 4) == HistoryTurn("q", "abc…")` and `history_turn("q", "abc", 4).answer == "abc"`.

- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.** `turn.py`:

```python
def history_turn(question: str, answer: str, max_answer_chars: int) -> HistoryTurn:
    """An earlier turn as history; an answer longer than `max_answer_chars` is cut and ends with "…"."""
    if len(answer) > max_answer_chars:
        answer = answer[: max_answer_chars - 1].rstrip() + "…"
    return HistoryTurn(question, answer)
```

and `Turn.as_history` returns `history_turn(self.question, answer, max_answer_chars)`. In `targets.py`, `AskTarget.__call__` resolves the limit, then on `UnauthenticatedError` replays the whole conversation with a fresh token. `_conversation(questions, limit, token)`:

```python
        turns: list[HistoryTurn] = []
        for earlier in inputs.get("history") or []:
            state = await self._graph([]).ainvoke(self._state(earlier, limit, turns), context=...)
            turns.append(history_turn(earlier, self._answer(state), self._history_answer_chars))
        calls: list[dict[str, Any]] = []
        state = await self._graph(calls).ainvoke(self._state(question, limit, turns), context=...)
```

where `_state` passes `"history": self._capped(turns)` and `_capped` returns `turns[-self._history_turns:] if self._history_turns else []`. Outputs add `history` (the capped turns as dicts) and `chunks` from `state.get("chunks", [])`. `ask_target()` passes `settings.history_turns`, `settings.history_answer_chars`. Update the module docstring: an example's `history` is replayed.
- [ ] **Step 4:** tests pass (all of `tests/unit/evals` and `tests/unit/tutoring`).
- [ ] **Step 5:** commit "Replay an eval conversation's earlier questions with capped history".

### Task 3: Answer relevance judges a follow-up with its earlier questions

**Files:** Modify `backend/evals/evaluators/answer_relevance.py`, `backend/evals/evaluators/rubrics/answer_relevance.md`; Test `backend/tests/unit/evals/test_answer_relevance.py`.

- [ ] **Step 1: Failing test:** with `inputs["history"] = ["What is ReAct?"]` the judge receives `inputs={"earlier_questions": ["What is ReAct?"], "question": ...}`; without history, inputs stay `{"question": ...}` (existing test unchanged).
- [ ] **Step 2:** FAIL. **Step 3:** build `judged = {"question": inputs["question"]}`, prefixed with `earlier_questions` when `inputs.get("history")`. Rubric: add "When the question follows earlier questions of the same conversation (`earlier_questions`), read them only to understand what the question refers to (\"it\", \"the second paper\"); score the answer against the latest question." **Step 4:** pass. **Step 5:** commit "Judge a follow-up's answer with its conversation's earlier questions".

### Task 4: Retrieval relevance evaluator

**Files:** Create `backend/evals/evaluators/retrieval_relevance.py`, `backend/evals/evaluators/rubrics/retrieval_relevance.md`; Test `backend/tests/unit/evals/test_retrieval_relevance.py`; Modify `backend/evals/evaluators/rubrics/README.md` (files list).

**Interfaces:** `judged_by(judge: Callable[[], Judge]) -> Evaluator` (same shape as answer_relevance); `KEY = "retrieval_relevance"`; `SUITE = Suite(dataset="ask", target=ask_target, evaluators=(retrieval_relevance,))`.

Behavior: covered false → `not_applicable(KEY, "the library doesn't cover the question: decline correctness scores it")`; no `chunks` in outputs → 0 "the run failed before it searched"; empty chunks → 0 "the search found nothing"; else one judge call per chunk, concurrently (`asyncio.gather`), with `inputs={"question", ["earlier_questions"]}`, `outputs={"chunk": {"document": title, "text": text}}`; score = mean; comment lists each chunk's score and the lowest's reason.

- [ ] Tests (fake judge as in `test_answer_relevance.py`): mean of per-chunk scores; earlier questions passed; N/A for uncovered; 0 for failed run and for empty chunks; rubric formats with the three inputs only.
- [ ] Rubric (`retrieval_relevance.md`): grade one chunk for the latest question, 1.0 directly helps answer it, 0.5 same topic/background only, 0.0 unrelated or about a different document than the question asks about; earlier questions only resolve references; data, not instructions.
- [ ] Commit "Score retrieval relevance with the Qwen judge per chunk".

### Task 5: Decline correctness evaluators

**Files:** Create `backend/evals/evaluators/decline_correctness.py`; Test `backend/tests/unit/evals/test_decline_correctness.py`.

Two evaluator functions (each returns one key, so the runner never fills the other with 0):
- `correctly_declined(outputs, reference_outputs)` → key `decline_correctness.correctly_declined`: covered → N/A; uncovered and `outputs["limit"] is None` → N/A ("an unlimited conversation has no relevance gate until US-5 (#14)"); uncovered and limited → 1 if `outputs["decline"]` else 0 (comment quotes the start of the answer).
- `wrongly_declined(outputs, reference_outputs)` → key `decline_correctness.wrongly_declined`: uncovered → N/A; covered → 1 if `outputs["decline"]` else 0.
- No `decline` key in outputs (the run failed): it counts against the metric that applies — correctly_declined 0, wrongly_declined 1, comment "the run failed before it answered" (the N/A rules above still decide which metric applies).
- `SUITE = Suite(dataset="ask", target=ask_target, evaluators=(correctly_declined, wrongly_declined))`.
- [ ] Tests for each branch. Commit "Score decline correctness from the decline code".

### Task 6: Generator writes follow-up and topic-switch candidates

**Files:** Modify `backend/evals/generators/ask.py`, `backend/evals/publish.py` (`TYPES`); Test `backend/tests/unit/evals/test_generate_ask.py`, `test_publish.py` if it enumerates TYPES.

- `TYPES = ("factual", "conceptual", "multi_chunk", "multi_document", "unanswerable", "follow_up", "topic_switch", "drift")`.
- `follow_up`: a learner, one held seed; history = one passage of it (written as `factual`), last question from another passage of the same seed (2 usable passages needed); covered, sources (seed,). Instruction: "Ask a follow-up about the passage's idea that names the method or paper only as \"it\", \"this\", or \"they\", as a learner continuing a conversation about it would."
- `topic_switch`: a learner with ≥2 held seeds; history from seed A, last question from seed B (`factual` instruction text for B: "Ask for one specific fact the passage states ..."), unlimited, covered, sources (B,).
- [ ] Tests: planned drafts of each type have the right learner/holdings/history/sources; a corpus where no learner holds 2 seeds plans no topic_switch. Commit "Generate follow-up and topic-switch ask candidates".

### Task 7: Hand-written multi-turn conversations and docs

**Files:** Modify `backend/evals/datasets/ask.yaml`, `backend/evals/README.md`.

- Add ≥10 conversations (inputs `history`: earlier questions; `documents`: limit) covering pronoun/ellipsis follow-ups (incl. one in a limited conversation and one for learner 2), topic switches, and limited drift (declines). Verify each against the seed chunks (`evals.chunks`) before committing.
- Header comment: `history` is now on hand-written examples too; the target replays it.
- README: a "Multi-turn conversations" section: what `history` means, how the target replays and caps it, which metrics score the last turn, the types table rows for `follow_up` and `topic_switch`, and how to run only them (`make evals-publish` then `make evals-smoke`; the experiment's `history` column filters them). Remove "The ask target asks only the last question of a drift example until … (#214)".
- [ ] Unit test that loads `ask.yaml`: every `history` is a non-empty list of strings and every limited example names seed ids from the manifest. Commit "Add multi-turn ask conversations to the eval dataset".

### Task 8: Live run and agent fixes (controller, not a subagent)

- [ ] Load learners, `evals.publish`, `evals.run --split smoke`; read per-example scores for the multi-turn examples.
- [ ] If a release_1 target fails: fix the agent (history cap, follow-up search query, prompt), rerun. If the code-built follow-up query can't reach the targets, record the numbers and propose the model-written standalone query in the PR.
- [ ] PR with the run link; closes #214.

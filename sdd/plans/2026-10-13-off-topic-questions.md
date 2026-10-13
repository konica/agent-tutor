# Off-topic questions — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Check every question before search. An off-topic question gets one polite `off_topic` decline, with no search and no model call. Every other question goes on to search as today.

**Architecture:**
- A `TopicClassifier` port in `tutoring` returns P(off-topic). The first adapter runs a SetFit model exported to ONNX with onnxruntime inside the agent, with no torch.
- A new `topic_check` LangGraph node runs before `search`. It fails open.
- The agent server sends a decline from any node.
- The eval package gains a labeled `topic_check` dataset with a train/eval split by hash, a generator, a classifier-only suite, and a training command.
- **PR 1 (Tasks 1–12)** ships the behaviour with the check off. **PR 2 (Tasks 13–14)** needs human review of generated data. It then trains and commits the model and turns the check on.

**Tech Stack:** Python 3.12, LangGraph, FastAPI, onnxruntime, Hugging Face `tokenizers`, numpy, SetFit (training only), pytest, LangSmith evals, React + Vitest, Docker, Helm.

**Spec:** `sdd/specs/2026-10-13-off-topic-questions-design.md`. Background and measurements: `sdd/reviews/2026-10-13-off-topic-model-research.md`.

## Global Constraints

**The decline**
- **Code:** `off_topic`.
- **Message, exactly:** `I'm Smart Tutor: I help you study and research the papers, books, magazines, and news articles in your library, so I can't help with that. Ask me about your documents or a topic you're learning.`
- **No action button** in the web; the existing generic decline card shows the message alone.

**The decision**
- Off-topic means `p_off_topic >= threshold`.
- The verdict is the **minimum** of P(off) for the question alone and P(off) for `f"Previous question: {previous}\nQuestion: {question}"`. The previous question is the last history turn's question.
- **Fail open:** the check off (`provider = "off"`), any exception, or a timeout (default **250 ms**) lets the question go on to `search`.
- Logs never contain the question text.

**Settings** (env `SMART_TUTOR_TOPIC_CHECK__*`)

| Field | Default |
|---|---|
| `provider` | `"off"` (`"off"` or `"setfit"`) |
| `model_dir` | `"models/topic_check"` |
| `threshold` | `None` (`None` means the model manifest's threshold) |
| `timeout_ms` | `250` |

`provider = "setfit"` with a missing or broken model **stops startup**.

**Packaging**
- Only the agent image installs the new `topic` extra (`numpy`, `onnxruntime`, `tokenizers`) and copies `backend/models/topic_check/` to `/app/models/topic_check`.
- The api, mcp and worker images are unchanged, and no image contains torch.
- onnxruntime runs with 2 intra-op threads.

**Eval targets**
- `topic_check.false_rejections`: max **0.01**.
- `topic_check.off_topic_caught`: min **0.95**.
- Both are added to `thresholds.yaml` in PR 2 only.

**Process**
- No new design state is needed: the mockup has none for this decline, and the PRD wins (AGENTS.md "Design inputs").
- **Backend checks** before each commit, from `backend/`:
  ```bash
  uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest
  ```
- **Web checks:** `cd web && npm run build && npm test`.
- **Windows:** `make` may be missing; run the Makefile line directly. Use `PYTHONUTF8=1` for `lint-imports`.
- **Commits:** imperative subject, a body that says why, and the trailer `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Work on branch `worktree-off-topic-model-research`. The spec and research note are already committed there.

## Review Focus

1. **A study question right after an off-topic turn** ("Tell me a joke", then "Explain photosynthesis") must not be declined. Test: Task 5, the min-of-two rule with an off-topic previous question.
2. **A classifier exception whose message contains the question** must not put the question in the logs. Test: Task 2, `caplog` check.
3. **A slow classifier** must not hold up the answer beyond `timeout_ms`; the question goes on to search. Test: Task 2, timeout.
4. **An off-topic question in a limited conversation, or from a learner with no readable documents,** gets `off_topic`, not `limited` or `no_documents`, and makes no search. Test: Task 2.
5. **`provider=setfit` with no model directory** must stop the agent at startup, not quietly run without the check. Test: Task 6.

---

## PR 1: behaviour, check off

### Task 1: Topic domain, port, and fake classifier

**Files:**
- Create: `backend/src/smart_tutor/tutoring/domain/topic.py`
- Create: `backend/src/smart_tutor/tutoring/ports/topic_classifier.py`
- Modify: `backend/src/smart_tutor/tutoring/application/__init__.py` (exports)
- Modify: `backend/tests/fakes/tutoring.py` (add `FakeTopicClassifier`), `backend/tests/fakes/__init__.py` (export it)
- Test: `backend/tests/unit/tutoring/test_topic.py`

**Interfaces:**
- Produces:
  - `TopicVerdict(p_off_topic: float, model: str)` with `.is_off_topic(threshold: float) -> bool`
  - `topic_texts(question: str, previous_question: str | None = None) -> list[str]`
  - `previous_question(history: Sequence[HistoryTurn]) -> str | None`
  - `class TopicClassifier(ABC)` with property `default_threshold -> float` and `async classify(question: str, history: Sequence[HistoryTurn]) -> TopicVerdict`
  - All exported from `smart_tutor.tutoring.application`.
  - `FakeTopicClassifier(scores: dict[str, float] | None = None, threshold: float = 0.5, error: Exception | None = None, delay: float = 0.0)`, with `.calls: list[tuple[str, list[HistoryTurn]]]`, exported from `fakes`.

- [ ] **Step 1: Write the failing test** `backend/tests/unit/tutoring/test_topic.py`

```python
"""The topic check's domain (spec 2026-10-13 §5.1–5.2): the verdict's threshold rule and the texts a classifier scores."""

from smart_tutor.tutoring.application import HistoryTurn, TopicVerdict, previous_question, topic_texts


def test_a_verdict_at_or_above_the_threshold_is_off_topic() -> None:
    assert TopicVerdict(0.5, "m").is_off_topic(0.5)
    assert TopicVerdict(0.9, "m").is_off_topic(0.5)
    assert not TopicVerdict(0.49, "m").is_off_topic(0.5)


def test_a_first_question_is_scored_alone() -> None:
    assert topic_texts("Explain photosynthesis") == ["Explain photosynthesis"]


def test_a_later_question_is_also_scored_with_the_previous_question() -> None:
    assert topic_texts("Explain that more simply.", "What is gradient descent?") == [
        "Explain that more simply.",
        "Previous question: What is gradient descent?\nQuestion: Explain that more simply.",
    ]


def test_the_previous_question_is_the_last_turns() -> None:
    assert previous_question([]) is None
    history = [HistoryTurn("First?", "a"), HistoryTurn("Second?", "b")]
    assert previous_question(history) == "Second?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/unit/tutoring/test_topic.py -v`
Expected: FAIL with `ImportError: cannot import name 'TopicVerdict'`

- [ ] **Step 3: Write the domain module** `backend/src/smart_tutor/tutoring/domain/topic.py`

```python
"""The topic check (PRD §9.2 step 0, spec 2026-10-13): whether a question is off-topic for a study tutor, as a
probability from a decision model. The texts a classifier scores are built here, so training (backend/evals) and the
agent build them the same way."""

from collections.abc import Sequence
from dataclasses import dataclass

from smart_tutor.tutoring.domain.turn import HistoryTurn


@dataclass(frozen=True)
class TopicVerdict:
    p_off_topic: float  # 0..1
    model: str  # the model and its version, for traces

    def is_off_topic(self, threshold: float) -> bool:
        return self.p_off_topic >= threshold


def topic_texts(question: str, previous_question: str | None = None) -> list[str]:
    """The question alone, then with the previous question when there is one. A classifier scores each and the
    verdict is the lowest (on-topic wins): context rescues a terse follow-up, and an off-topic previous turn can't sink
    a study question."""
    texts = [question]
    if previous_question:
        texts.append(f"Previous question: {previous_question}\nQuestion: {question}")
    return texts


def previous_question(history: Sequence[HistoryTurn]) -> str | None:
    return history[-1].question if history else None
```

- [ ] **Step 4: Write the port** `backend/src/smart_tutor/tutoring/ports/topic_classifier.py`

```python
"""Decide whether a question is off-topic (PRD §9.2 step 0). Adapters: a SetFit model on onnxruntime
(OnnxSetFitTopicClassifier); later possibly another decision model, such as TypeSafe's Jev (spec 2026-10-13 §5.4)."""

from abc import ABC, abstractmethod
from collections.abc import Sequence

from smart_tutor.tutoring.domain.topic import TopicVerdict
from smart_tutor.tutoring.domain.turn import HistoryTurn


class TopicClassifier(ABC):
    @property
    @abstractmethod
    def default_threshold(self) -> float:
        """The threshold tuned for this model; configuration may override it."""

    @abstractmethod
    async def classify(self, question: str, history: Sequence[HistoryTurn]) -> TopicVerdict:
        """P(off-topic) of the question, given the conversation's earlier turns, oldest first. May raise anything: the
        caller fails open."""
```

- [ ] **Step 5: Export from the application layer.** In `backend/src/smart_tutor/tutoring/application/__init__.py`, add the imports and their names to `__all__`, keeping `__all__` sorted:

```python
from smart_tutor.tutoring.domain.topic import TopicVerdict, previous_question, topic_texts
from smart_tutor.tutoring.ports.topic_classifier import TopicClassifier
```

Add `"TopicClassifier"` and `"TopicVerdict"` to `__all__` after `"ThreadSummary"`. Add `"previous_question"` and `"topic_texts"` to the lowercase names; they sort before and after `"search_query"` respectively.

- [ ] **Step 6: Add the fake.** In `backend/tests/fakes/tutoring.py`:
  - add `import asyncio` to the imports;
  - add `HistoryTurn` to the `smart_tutor.tutoring.domain.turn` import;
  - add `from smart_tutor.tutoring.domain.topic import TopicVerdict` and `from smart_tutor.tutoring.ports.topic_classifier import TopicClassifier`;
  - append:

```python
class FakeTopicClassifier(TopicClassifier):
    """P(off-topic) from `scores` by question (0.0, on-topic, for any other); `error` raises it, `delay` sleeps first
    (seconds). Records each call."""

    def __init__(
        self,
        scores: dict[str, float] | None = None,
        threshold: float = 0.5,
        error: Exception | None = None,
        delay: float = 0.0,
    ) -> None:
        self._scores, self._threshold, self._error, self._delay = scores or {}, threshold, error, delay
        self.calls: list[tuple[str, list[HistoryTurn]]] = []

    @property
    def default_threshold(self) -> float:
        return self._threshold

    async def classify(self, question: str, history: Sequence[HistoryTurn]) -> TopicVerdict:
        self.calls.append((question, list(history)))
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._error is not None:
            raise self._error
        return TopicVerdict(self._scores.get(question, 0.0), "fake@1")
```

In `backend/tests/fakes/__init__.py`, change the tutoring import to `from fakes.tutoring import FakeAnswerFeedback, FakeRetriever, FakeTopicClassifier, InMemoryThreads` and add `"FakeTopicClassifier"` to `__all__`.

- [ ] **Step 7: Run the tests and checks**

Run: `cd backend && uv run pytest tests/unit/tutoring/test_topic.py -v && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: 4 passed; mypy and lint-imports clean.

- [ ] **Step 8: Commit**

```bash
git add backend/src/smart_tutor/tutoring backend/tests/fakes backend/tests/unit/tutoring/test_topic.py
git commit -m "Add the topic classifier port and its domain" -m "The topic check needs a model-agnostic port so SetFit can ship now and another decision model can replace it later; the texts it scores live in the domain so training and the agent agree." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The `topic_check` node, the `off_topic` decline, and the graph

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/application/answer.py` (add `OFF_TOPIC_DECLINE`), `backend/src/smart_tutor/tutoring/application/__init__.py` (export it)
- Modify: `backend/src/smart_tutor/apps/agent/state.py`
- Create: `backend/src/smart_tutor/apps/agent/nodes/topic_check.py`
- Modify: `backend/src/smart_tutor/apps/agent/graph.py`
- Test: `backend/tests/unit/apps/agent/test_graph.py`

**Interfaces:**
- Consumes: Task 1's `TopicClassifier` and `FakeTopicClassifier`.
- Produces:
  - `OFF_TOPIC_DECLINE: str`.
  - `DeclineCode = Literal["limited", "no_documents", "off_topic"]`.
  - `AskState["topic_check"]: TopicCheck` (`verdict`: `"off" | "on_topic" | "off_topic" | "error"`, plus `p_off_topic` and `model`).
  - `build_graph(retriever_for, model, answer_floor=0.3, answer_max_tokens=1500, topic_classifier: TopicClassifier | None = None, topic_threshold: float = 0.5, topic_timeout_ms: int = 250) -> AskGraph`.

- [ ] **Step 1: Write the failing tests.** In `backend/tests/unit/apps/agent/test_graph.py`:
  - change the fakes import to `from fakes import FakeChatModel, FakeRetriever, FakeTopicClassifier, fake_chat_model`;
  - add `import logging` and `import pytest`;
  - replace `test_the_graph_is_search_then_answer` with the version below;
  - append the rest.

```python
def test_the_graph_is_topic_check_then_search_then_answer() -> None:
    graph = build_graph(lambda token: FakeRetriever(CHUNKS), fake_chat_model())
    assert set(graph.get_graph().nodes) == {"__start__", "topic_check", "search", "answer", "__end__"}


OFF = "Tell me a joke about cats."


async def test_an_off_topic_question_is_declined_without_a_search_or_a_model_call() -> None:
    retriever = FakeRetriever(CHUNKS)
    graph = build_graph(
        lambda token: retriever, fake_chat_model(), topic_classifier=FakeTopicClassifier({OFF: 0.97})
    )  # no scripted reply: a model call would fail
    out = await graph.ainvoke({"question": OFF}, context=AgentContext(access_token="t"))
    assert out["decline"] == "off_topic" and out["answer"] == "" and out["citations"] == []
    assert out["topic_check"] == {"verdict": "off_topic", "p_off_topic": 0.97, "model": "fake@1"}
    assert retriever.calls == []


async def test_an_on_topic_question_searches_and_answers_as_before() -> None:
    retriever, classifier = FakeRetriever(CHUNKS), FakeTopicClassifier({"What is attention?": 0.1})
    graph = build_graph(
        lambda token: retriever, fake_chat_model(AIMessage("It weighs tokens [1].")), topic_classifier=classifier
    )
    out = await graph.ainvoke(INPUT, context=AgentContext(access_token="t"))
    assert "decline" not in out and out["answer"] == "It weighs tokens [1]."
    assert out["topic_check"]["verdict"] == "on_topic"
    assert retriever.calls == [("What is attention?", 5, None)]


async def test_the_classifier_gets_the_question_and_the_history() -> None:
    classifier = FakeTopicClassifier()
    graph = build_graph(
        lambda token: FakeRetriever(CHUNKS), fake_chat_model(AIMessage("ok [1]")), topic_classifier=classifier
    )
    history = [HistoryTurn("What is attention?", "It weighs tokens [1].")]
    await graph.ainvoke({"question": "Why?", "history": history}, context=AgentContext(access_token="t"))
    assert classifier.calls == [("Why?", history)]


async def test_the_graphs_threshold_decides_not_the_classifiers_default() -> None:
    classifier = FakeTopicClassifier({OFF: 0.6}, threshold=0.5)
    graph = build_graph(
        lambda token: FakeRetriever(CHUNKS),
        fake_chat_model(AIMessage("ok [1]")),
        topic_classifier=classifier,
        topic_threshold=0.7,
    )
    out = await graph.ainvoke({"question": OFF}, context=AgentContext(access_token="t"))
    assert "decline" not in out and out["topic_check"]["verdict"] == "on_topic"


async def test_a_classifier_error_fails_open_and_logs_no_question(caplog: pytest.LogCaptureFixture) -> None:
    retriever = FakeRetriever(CHUNKS)
    classifier = FakeTopicClassifier(error=RuntimeError(f"model broke on {OFF}"))
    graph = build_graph(lambda token: retriever, fake_chat_model(AIMessage("ok [1]")), topic_classifier=classifier)
    with caplog.at_level(logging.WARNING):
        out = await graph.ainvoke({"question": OFF}, context=AgentContext(access_token="t"))
    assert "decline" not in out and out["topic_check"] == {"verdict": "error"}
    assert retriever.calls == [(OFF, 5, None)]
    assert "RuntimeError" in caplog.text and "joke" not in caplog.text


async def test_a_slow_classifier_times_out_and_fails_open() -> None:
    retriever = FakeRetriever(CHUNKS)
    classifier = FakeTopicClassifier({OFF: 0.99}, delay=1.0)
    graph = build_graph(
        lambda token: retriever,
        fake_chat_model(AIMessage("ok [1]")),
        topic_classifier=classifier,
        topic_timeout_ms=50,
    )
    out = await graph.ainvoke({"question": OFF}, context=AgentContext(access_token="t"))
    assert "decline" not in out and out["topic_check"] == {"verdict": "error"}
    assert retriever.calls == [(OFF, 5, None)]


async def test_without_a_classifier_every_question_searches() -> None:
    retriever = FakeRetriever(CHUNKS)
    graph = build_graph(lambda token: retriever, fake_chat_model(AIMessage("ok [1]")))
    out = await graph.ainvoke({"question": OFF}, context=AgentContext(access_token="t"))
    assert out["topic_check"] == {"verdict": "off"} and retriever.calls == [(OFF, 5, None)]


async def test_an_off_topic_question_in_a_limited_conversation_is_off_topic_not_limited() -> None:
    retriever = FakeRetriever(CHUNKS)
    graph = build_graph(lambda token: retriever, fake_chat_model(), topic_classifier=FakeTopicClassifier({OFF: 0.9}))
    out = await graph.ainvoke({"question": OFF, "document_ids": ["d1"]}, context=AgentContext(access_token="t"))
    assert out["decline"] == "off_topic" and retriever.calls == []


async def test_an_off_topic_question_with_nothing_readable_is_off_topic_not_no_documents() -> None:
    retriever = FakeRetriever([])
    graph = build_graph(lambda token: retriever, fake_chat_model(), topic_classifier=FakeTopicClassifier({OFF: 0.9}))
    out = await graph.ainvoke({"question": OFF}, context=AgentContext(access_token="t"))
    assert out["decline"] == "off_topic" and retriever.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/apps/agent/test_graph.py -v`
Expected: FAIL. The new tests fail with `TypeError: build_graph() got an unexpected keyword argument 'topic_classifier'`, and the node-set test fails.

- [ ] **Step 3: Add the message.** In `backend/src/smart_tutor/tutoring/application/answer.py`, after `LIMITED_DECLINE`:

```python
# An off-topic question (spec 2026-10-13 §4.2): declined before any search, with no action.
OFF_TOPIC_DECLINE = (
    "I'm Smart Tutor: I help you study and research the papers, books, magazines, and news articles in your library, "
    "so I can't help with that. Ask me about your documents or a topic you're learning."
)
```

In `tutoring/application/__init__.py`, add `OFF_TOPIC_DECLINE` to the `answer` import and `"OFF_TOPIC_DECLINE"` to `__all__`, after `"NO_DOCUMENTS_DECLINE"`.

- [ ] **Step 4: Extend the state.** Replace `backend/src/smart_tutor/apps/agent/state.py`'s decline lines and `AskState` with:

```python
from smart_tutor.tutoring.application import (
    LIMITED_DECLINE,
    NO_DOCUMENTS_DECLINE,
    OFF_TOPIC_DECLINE,
    HistoryTurn,
    RetrievedChunk,
)

# "limited": a limited search that doesn't cover the question (US-4c); "no_documents": nothing is readable (US-3);
# "off_topic": the topic check declined it before search (spec 2026-10-13).
DeclineCode = Literal["limited", "no_documents", "off_topic"]
# What the learner reads for each decline (the server's decline event, the eval target's answer).
DECLINE_MESSAGES: dict[DeclineCode, str] = {
    "limited": LIMITED_DECLINE,
    "no_documents": NO_DOCUMENTS_DECLINE,
    "off_topic": OFF_TOPIC_DECLINE,
}


class TopicCheck(TypedDict, total=False):
    """What the topic check decided, for traces: "off" (no classifier), "error" (failed open), or its verdict."""

    verdict: Literal["off", "on_topic", "off_topic", "error"]
    p_off_topic: float
    model: str


class AskState(TypedDict, total=False):
    question: str
    document_ids: list[str] | None
    history: list[HistoryTurn]  # earlier turns, oldest first (question and answer text only; ADR 0015)
    topic_check: TopicCheck
    chunks: list[RetrievedChunk]
    no_documents: bool  # the readable set is empty: the learner has no ready, non-archived document
    answer: str
    citations: list[Citation]
    decline: DeclineCode
```

(Keep the existing `AgentContext`, the `Citation` import, and the other imports.)

- [ ] **Step 5: Write the node** `backend/src/smart_tutor/apps/agent/nodes/topic_check.py`

```python
"""Topic check (PRD §9.2 step 0, spec 2026-10-13): an off-topic question is declined before any search or model call.
The check fails open: no classifier, an error, or a timeout lets the question go on to search."""

import asyncio
import logging
from typing import Literal, Protocol

from smart_tutor.apps.agent.state import AskState, TopicCheck
from smart_tutor.tutoring.application import TopicClassifier

logger = logging.getLogger(__name__)


class TopicCheckNode(Protocol):
    async def __call__(self, state: AskState) -> AskState: ...


def topic_check_node(classifier: TopicClassifier | None, threshold: float, timeout_ms: int) -> TopicCheckNode:
    async def topic_check(state: AskState) -> AskState:
        if classifier is None:
            return {"topic_check": {"verdict": "off"}}
        try:
            verdict = await asyncio.wait_for(
                classifier.classify(state["question"], state.get("history", [])), timeout_ms / 1000
            )
        except Exception as error:  # TimeoutError included: fail open
            logger.warning("topic check failed open: %s", type(error).__name__)  # never the question
            return {"topic_check": {"verdict": "error"}}
        off = verdict.is_off_topic(threshold)
        check: TopicCheck = {
            "verdict": "off_topic" if off else "on_topic",
            "p_off_topic": round(verdict.p_off_topic, 4),
            "model": verdict.model,
        }
        if not off:
            return {"topic_check": check}
        return {"topic_check": check, "answer": "", "citations": [], "decline": "off_topic"}

    return topic_check


def after_topic_check(state: AskState) -> Literal["search", "declined"]:
    return "declined" if state.get("decline") == "off_topic" else "search"
```

- [ ] **Step 6: Wire the graph.** Replace `backend/src/smart_tutor/apps/agent/graph.py`:

```python
"""The ask graph (PRD §9.2): topic check → search → answer, or topic check → decline. Single turn, no checkpointer
(#31)."""

from collections.abc import Callable

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from smart_tutor.apps.agent.nodes.answer import answer_node
from smart_tutor.apps.agent.nodes.search import search_node
from smart_tutor.apps.agent.nodes.topic_check import after_topic_check, topic_check_node
from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.tutoring.application import Retriever, TopicClassifier

AskGraph = CompiledStateGraph[AskState, AgentContext, AskState, AskState]


def build_graph(
    retriever_for: Callable[[str], Retriever],
    model: BaseChatModel,
    answer_floor: float = 0.3,
    answer_max_tokens: int = 1500,
    topic_classifier: TopicClassifier | None = None,
    topic_threshold: float = 0.5,
    topic_timeout_ms: int = 250,
) -> AskGraph:
    return (
        StateGraph(AskState, context_schema=AgentContext)
        .add_node("topic_check", topic_check_node(topic_classifier, topic_threshold, topic_timeout_ms))
        .add_node("search", search_node(retriever_for))
        .add_node("answer", answer_node(model, answer_floor, answer_max_tokens))
        .add_edge(START, "topic_check")
        .add_conditional_edges("topic_check", after_topic_check, {"search": "search", "declined": END})
        .add_edge("search", "answer")
        .add_edge("answer", END)
        .compile()
    )
```

- [ ] **Step 7: Run the tests and checks**

Run: `cd backend && uv run pytest tests/unit/apps/agent -v && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: all pass, including the existing graph and server tests, which call `build_graph` without the new arguments.

- [ ] **Step 8: Commit**

```bash
git add backend/src/smart_tutor/apps/agent backend/src/smart_tutor/tutoring/application backend/tests/unit/apps/agent/test_graph.py
git commit -m "Check the topic before search in the ask graph" -m "An off-topic question now ends in an off_topic decline without searching or calling the answer model; with no classifier, an error, or a timeout the question goes on to search as before (spec 2026-10-13 §4)." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The agent server streams a decline from any node

**Files:**
- Modify: `backend/src/smart_tutor/apps/agent/server.py` (module docstring, `answer_events`)
- Test: `backend/tests/unit/apps/agent/test_server.py`

**Interfaces:**
- Consumes: `build_graph(..., topic_classifier=...)` and `DECLINE_MESSAGES["off_topic"]` from Task 2; `FakeTopicClassifier` from Task 1.
- Produces: for an off-topic question the SSE stream is exactly `decline {"code": "off_topic", "message": OFF_TOPIC_DECLINE}`, then `done`.

- [ ] **Step 1: Write the failing tests.** In `backend/tests/unit/apps/agent/test_server.py`:
  - change the fakes import to `from fakes import FakeRetriever, FakeTokenVerifier, FakeTopicClassifier, fake_chat_model`;
  - add `from smart_tutor.tutoring.application import OFF_TOPIC_DECLINE, TopicClassifier`;
  - replace `client()`:

```python
def client(
    retriever: FakeRetriever,
    reply: str = "It weighs tokens [1].",
    answer_floor: float = 0.3,
    topic_classifier: TopicClassifier | None = None,
) -> tuple[TestClient, FakeTokenVerifier]:
    verifier = FakeTokenVerifier()
    verifier.add("t-ada", Principal(UserId("ada"), "Ada", frozenset({"learner"})))
    graph = build_graph(
        lambda token: retriever, fake_chat_model(AIMessage(reply)), answer_floor, topic_classifier=topic_classifier
    )
    return TestClient(create_app(Settings(), verifier=verifier, graph=graph)), verifier
```

Then append:

```python
def test_an_off_topic_question_streams_only_the_decline_then_done() -> None:
    retriever = FakeRetriever([CHUNK])
    c, _ = client(retriever, topic_classifier=FakeTopicClassifier({"Tell me a joke.": 0.99}))
    got = events(c.post("/ask", json={"question": "Tell me a joke."}, headers=AUTH).text)
    assert got == [("decline", {"code": "off_topic", "message": OFF_TOPIC_DECLINE}), ("done", {})]
    assert retriever.calls == []


def test_an_on_topic_question_with_a_classifier_streams_the_answer_as_before() -> None:
    c, _ = client(FakeRetriever([CHUNK]), topic_classifier=FakeTopicClassifier({"What is attention?": 0.05}))
    names = [e for e, _ in events(c.post("/ask", json=BODY, headers=AUTH).text)]
    assert "decline" not in names and names[-3:] == ["sources", "citations", "done"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/apps/agent/test_server.py -v`
Expected: `test_an_off_topic_question_streams_only_the_decline_then_done` FAILS. The stream has only `done`, because the server reads declines from the `answer` node alone.

- [ ] **Step 3: Read declines from every node.** In `answer_events`, replace the two `elif part["type"] == "updates" ...` branches with:

```python
                elif part["type"] == "updates":
                    for node, raw in part["data"].items():
                        update = raw or {}
                        if node == "search":
                            chunks = update.get("chunks", [])
                        elif (code := update.get("decline")) is not None:  # from topic_check or answer
                            decline = code
                            yield sse("decline", {"code": code, "message": DECLINE_MESSAGES[code]})
                        elif node == "answer":
                            yield sse(
                                "sources", {"document_ids": list(dict.fromkeys(c.document_id for c in chunks))}
                            )
                            citations = [
                                {
                                    "n": c.n,
                                    "chunk_id": c.chunk_id,
                                    "document_id": c.document_id,
                                    "document_title": c.document_title,
                                    "page": c.page,
                                }
                                for c in update["citations"]
                            ]
                            yield sse("citations", {"citations": citations})
```

In the module docstring, change the decline paragraph to:

```
A turn the model doesn't answer is ``decline`` {"code", "message"} then ``done``, with no ``delta``, ``sources``, or
``citations``: ``off_topic`` when the topic check finds the question off-topic (no search runs; spec 2026-10-13);
``no_documents`` when the learner has nothing readable (no ready, non-archived document; US-3), or, for a request
with ``document_ids`` (only those documents are searched), ``limited`` when none of the chunks found scores at least
``answer_floor`` (US-4c).
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && uv run pytest tests/unit/apps/agent -v && uv run mypy`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/src/smart_tutor/apps/agent/server.py backend/tests/unit/apps/agent/test_server.py
git commit -m "Stream the off-topic decline from the agent" -m "The server only read declines from the answer node, so a decline made by the topic check before search would have reached the learner as an empty turn." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The API documents `off_topic` and the web knows it

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py:59-60` (the `SSE_RESPONSE` description)
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`
- Modify: `web/src/api/chat.ts:44` (`DeclineCode`), `web/src/features/chat/ChatPage.tsx:93-94` (doc comment)
- Test: `web/src/api/chat.test.ts`, `web/src/features/chat/ChatPage.test.tsx`

**Interfaces:**
- Consumes: the SSE contract from Task 3.
- Produces: `DeclineCode = "limited" | "no_documents" | "off_topic"`.

- [ ] **Step 1: Write the failing web tests.** In `web/src/api/chat.test.ts`, after `it("reads a no_documents decline", …)`:

```ts
  it("reads an off_topic decline", async () => {
    const message =
      "I'm Smart Tutor: I help you study and research the papers, books, magazines, and news articles in your library, so I can't help with that. Ask me about your documents or a topic you're learning.";
    const { apiClient } = api(() =>
      eventStream(`event: decline\ndata: ${JSON.stringify({ code: "off_topic", message })}\n\nevent: done\ndata: {}\n\n`),
    );
    expect(await collect(askInNewThread("q", undefined, apiClient))).toEqual([
      { type: "decline", code: "off_topic", message },
      { type: "done" },
    ]);
  });
```

In `web/src/features/chat/ChatPage.test.tsx`, add next to `NO_DOCUMENTS` (line 14):

```ts
const OFF_TOPIC =
  "I'm Smart Tutor: I help you study and research the papers, books, magazines, and news articles in your library, so I can't help with that. Ask me about your documents or a topic you're learning.";
```

After `it("shows the agent's upload request inline, …")` (around line 300):

```tsx
  it("shows an off-topic decline as its message alone, with no way out, and keeps the composer", async () => {
    const ask = vi.fn(() =>
      events({ type: "thread", thread_id: "t1", run_id: "r1" }, { type: "decline", code: "off_topic", message: OFF_TOPIC }, { type: "done" }),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "Tell me a joke");
    await userEvent.click(askButton());
    expect(await screen.findByText(OFF_TOPIC)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Upload" })).not.toBeInTheDocument();
    expect(screen.queryByText(UPLOAD_HINT)).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Search all my documents" })).not.toBeInTheDocument();
    expect(screen.queryByText(/couldn't answer/)).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: /question/i })).toBeInTheDocument();
  });
```

After `it("a no_documents decline in the history shows its message, …")` (around line 1846), inside the same `describe`:

```tsx
    it("an off_topic decline in the history shows its message with no action", async () => {
      const off = turn({ question: "Tell me a joke", answer: "", citations: [], decline: { code: "off_topic", message: OFF_TOPIC } });
      renderChat({ loadConversation: conversation([turn(), off]) }, "/chat/t1");
      expect(await screen.findByText(OFF_TOPIC)).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: "Upload" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Search all my documents" })).not.toBeInTheDocument();
    });
```

- [ ] **Step 2: Run the web tests**

Run: `cd web && npx vitest run src/api/chat.test.ts src/features/chat/ChatPage.test.tsx`
Expected: the tests pass at runtime, because unknown codes already render as the message alone. `npm run build` (`tsc -b`) FAILS: `"off_topic"` is not assignable to `DeclineCode` in `chat.test.ts`.

- [ ] **Step 3: Update the types and docs**

`web/src/api/chat.ts` line 44:

```ts
export type DeclineCode = "limited" | "no_documents" | "off_topic";
```

`web/src/features/chat/ChatPage.tsx` lines 93–94:

```ts
  /** A turn the tutor didn't answer: "limited" (the conversation's documents don't cover it), "no_documents" (nothing
   * can be read: the request to upload a document), or "off_topic" (not a study question: the message alone). */
```

`backend/src/smart_tutor/apps/api/routes/threads.py`, the `SSE_RESPONSE` description:

```python
        "description": (
            "Server-sent events: thread, then delta*, citations, done; or decline then done "
            "(no_documents: nothing readable, upload first; limited: the listed documents don't cover it; "
            "off_topic: not a study question, declined before search); or error."
        ),
```

- [ ] **Step 4: Regenerate the API client** (AGENTS.md: CI fails when it is stale)

Run: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`
Expected: `web/src/api/openapi.json` and `web/src/api/generated/types.gen.ts` change only in the SSE description strings.

- [ ] **Step 5: Run the checks**

Run: `cd web && npm run build && npm test` and `cd backend && uv run pytest tests/unit/apps/api -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/src/smart_tutor/apps/api/routes/threads.py web/src
git commit -m "Name the off_topic decline in the API and the web" -m "The chat already shows an unknown decline as its message alone, which is what an off-topic decline needs; the type and docs now say so and tests pin it." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The ONNX SetFit adapter

**Files:**
- Modify: `backend/pyproject.toml` (extra `topic`, dev group, rule-4 vendor list, mypy override if needed), `backend/uv.lock`
- Create: `backend/src/smart_tutor/tutoring/adapters/onnx_topic_classifier.py`
- Create: `backend/tests/fakes/topic_model.py`; modify `backend/tests/fakes/__init__.py` (export `write_topic_model`)
- Test: `backend/tests/unit/tutoring/test_onnx_topic_classifier.py`

**Interfaces:**
- Consumes: `TopicClassifier`, `TopicVerdict`, `topic_texts`, `previous_question` (Task 1).
- Produces:
  - `OnnxSetFitTopicClassifier(model_dir: Path)` with `.default_threshold`, `async classify(...)`, and `p_off_topic(texts: Sequence[str]) -> list[float]`.
  - `Manifest.read(path)`.
  - The model directory layout: `body.onnx`, `tokenizer.json`, `head.npz` (`coef` with shape `(1, dim)`, `intercept` with shape `(1,)`), and `manifest.json` (`version`, `pooling` of `cls` or `mean`, `normalize`, `max_tokens`, `threshold`, plus free extra keys).
  - The test helper `write_topic_model(folder: Path, *, pooling: str = "mean", normalize: bool = True, threshold: float = 0.5, max_tokens: int = 64, head_rows: int = 1) -> Path`.

- [ ] **Step 1: Add the dependencies.** In `backend/pyproject.toml` `[project.optional-dependencies]`, add:

```toml
# Installed only in the agent image: the topic check's SetFit model on onnxruntime (spec 2026-10-13, ADR 0018).
topic = ["numpy>=2.0", "onnxruntime>=1.20", "tokenizers>=0.20"]
```

In `[dependency-groups] dev`, add `"numpy>=2.0"`, `"onnx>=1.17"`, `"onnxruntime>=1.20"` and `"tokenizers>=0.20"`, keeping the list sorted. In the rule-4 contract "Domain, application, and ports use no vendor SDK or shared adapter", add `"onnxruntime",` after `"mcp",` and `"tokenizers",` after `"sqlalchemy",`.

Run: `cd backend && uv lock && uv sync`
Expected: the lock updates; `uv run python -c "import onnxruntime, tokenizers, onnx"` exits 0.

- [ ] **Step 2: Write the fixture model builder** `backend/tests/fakes/topic_model.py`

```python
"""A tiny topic-check model directory for tests (spec 2026-10-13 §5.2): a word-level tokenizer, an ONNX "body" that
looks each token up in a 2-d table (on-topic words [1, 0], off-topic words [0, 1], others [0, 0]), and a logistic head
with coef [-4, 4], so a pure on-topic text scores sigmoid(-4) ≈ 0.018 and a pure off-topic one sigmoid(4) ≈ 0.982."""

import json
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
from tokenizers import Tokenizer, normalizers, pre_tokenizers
from tokenizers.models import WordLevel

VOCAB = {"[UNK]": 0, "explain": 1, "photosynthesis": 2, "derivative": 3, "tell": 4, "joke": 5, "weather": 6}
ON_WORDS, OFF_WORDS = ("explain", "photosynthesis", "derivative"), ("tell", "joke", "weather")


def _table() -> np.ndarray:
    table = np.zeros((len(VOCAB), 2), dtype=np.float32)
    for word in ON_WORDS:
        table[VOCAB[word]] = [1.0, 0.0]
    for word in OFF_WORDS:
        table[VOCAB[word]] = [0.0, 1.0]
    return table


def _write_body(path: Path) -> None:
    ids = helper.make_tensor_value_info("input_ids", TensorProto.INT64, ["batch", "tokens"])
    out = helper.make_tensor_value_info("last_hidden_state", TensorProto.FLOAT, ["batch", "tokens", 2])
    gather = helper.make_node("Gather", ["table", "input_ids"], ["last_hidden_state"], axis=0)
    graph = helper.make_graph([gather], "body", [ids], [out], [numpy_helper.from_array(_table(), "table")])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 8  # onnxruntime may not read the newest IR version
    onnx.save(model, str(path))


def write_topic_model(
    folder: Path,
    *,
    pooling: str = "mean",
    normalize: bool = True,
    threshold: float = 0.5,
    max_tokens: int = 64,
    head_rows: int = 1,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    _write_body(folder / "body.onnx")
    tokenizer = Tokenizer(WordLevel(VOCAB, unk_token="[UNK]"))
    tokenizer.normalizer = normalizers.Lowercase()
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.save(str(folder / "tokenizer.json"))
    coef = np.tile(np.array([[-4.0, 4.0]], dtype=np.float32), (head_rows, 1))
    np.savez(folder / "head.npz", coef=coef, intercept=np.zeros(head_rows, dtype=np.float32))
    manifest = {
        "version": "fixture@1",
        "pooling": pooling,
        "normalize": normalize,
        "max_tokens": max_tokens,
        "threshold": threshold,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return folder
```

Export it from `backend/tests/fakes/__init__.py` with `from fakes.topic_model import write_topic_model`, and add `"write_topic_model"` to `__all__`.

- [ ] **Step 3: Write the failing tests** `backend/tests/unit/tutoring/test_onnx_topic_classifier.py`

```python
"""The SetFit topic classifier on onnxruntime (spec 2026-10-13 §5.2), against the fixture model in fakes.topic_model."""

from pathlib import Path

import pytest

from fakes import write_topic_model
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier
from smart_tutor.tutoring.application import HistoryTurn

ON, OFF = 0.0180, 0.9820  # sigmoid(-4), sigmoid(4)


def classifier(tmp_path: Path, **kw: object) -> OnnxSetFitTopicClassifier:
    return OnnxSetFitTopicClassifier(write_topic_model(tmp_path / "model", **kw))  # type: ignore[arg-type]


def test_study_and_off_topic_texts_score_apart(tmp_path: Path) -> None:
    scores = classifier(tmp_path).p_off_topic(["Explain photosynthesis", "Tell me a joke"])
    assert scores == [pytest.approx(ON, abs=1e-3), pytest.approx(OFF, abs=1e-3)]


async def test_a_first_question_is_scored_alone(tmp_path: Path) -> None:
    verdict = await classifier(tmp_path).classify("Tell me a joke", [])
    assert verdict.p_off_topic == pytest.approx(OFF, abs=1e-3) and verdict.model == "fixture@1"


async def test_context_can_rescue_a_question_the_verdict_is_the_lowest_score(tmp_path: Path) -> None:
    # Alone "Tell me a joke" is off-topic; with a study question before it the pair scores 0.5. The lower wins.
    verdict = await classifier(tmp_path).classify("Tell me a joke", [HistoryTurn("Explain photosynthesis", "…")])
    assert verdict.p_off_topic == pytest.approx(0.5, abs=1e-3)


async def test_an_off_topic_previous_turn_cannot_sink_a_study_question(tmp_path: Path) -> None:
    verdict = await classifier(tmp_path).classify("Explain photosynthesis", [HistoryTurn("Tell me a joke", "…")])
    assert verdict.p_off_topic == pytest.approx(ON, abs=1e-3)


def test_cls_pooling_reads_the_first_token_and_mean_pooling_all(tmp_path: Path) -> None:
    text = ["Tell explain explain"]
    assert classifier(tmp_path / "cls", pooling="cls").p_off_topic(text)[0] > 0.95
    assert classifier(tmp_path / "mean", pooling="mean").p_off_topic(text)[0] < 0.2


def test_without_normalization_the_raw_pooled_vector_is_scored(tmp_path: Path) -> None:
    # mean of tell, me, a, joke = [0, 0.5]: logit 2 → 0.881 (normalized it would be [0, 1] → 0.982)
    assert classifier(tmp_path, normalize=False).p_off_topic(["Tell me a joke"])[0] == pytest.approx(0.8808, abs=1e-3)


def test_long_text_is_cut_to_max_tokens(tmp_path: Path) -> None:
    score = classifier(tmp_path, max_tokens=2).p_off_topic(["Explain photosynthesis tell joke tell joke"])[0]
    assert score == pytest.approx(ON, abs=1e-3)


def test_the_default_threshold_is_the_manifests(tmp_path: Path) -> None:
    assert classifier(tmp_path, threshold=0.73).default_threshold == 0.73


def test_a_manifest_with_an_unknown_pooling_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="pooling"):
        classifier(tmp_path, pooling="max")


def test_a_head_that_is_not_binary_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="binary"):
        classifier(tmp_path, head_rows=2)


def test_a_missing_model_directory_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        OnnxSetFitTopicClassifier(tmp_path / "missing")
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/tutoring/test_onnx_topic_classifier.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'smart_tutor.tutoring.adapters.onnx_topic_classifier'`

- [ ] **Step 5: Write the adapter** `backend/src/smart_tutor/tutoring/adapters/onnx_topic_classifier.py`

```python
"""TopicClassifier on a SetFit model exported to ONNX (spec 2026-10-13 §5.2, ADR 0018): onnxruntime, tokenizers, and
numpy, no torch. The model directory, made by `python -m evals.topic_check.train`, holds body.onnx (the
sentence-transformer body), tokenizer.json, head.npz (the logistic head: `coef` (1, dim), `intercept` (1,)), and
manifest.json (version, pooling, normalize, max_tokens, threshold)."""

import asyncio
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from smart_tutor.tutoring.domain.topic import TopicVerdict, previous_question, topic_texts
from smart_tutor.tutoring.domain.turn import HistoryTurn
from smart_tutor.tutoring.ports.topic_classifier import TopicClassifier

THREADS = 2  # the on-premise host has 2 vCPU for the whole stack (ADR 0012)


@dataclass(frozen=True)
class Manifest:
    version: str
    pooling: Literal["cls", "mean"]
    normalize: bool
    max_tokens: int
    threshold: float

    @classmethod
    def read(cls, path: Path) -> "Manifest":
        raw = json.loads(path.read_text(encoding="utf-8"))
        pooling = raw["pooling"]
        if pooling not in ("cls", "mean"):
            raise ValueError(f"{path}: pooling must be cls or mean, not {pooling!r}")
        return cls(str(raw["version"]), pooling, bool(raw["normalize"]), int(raw["max_tokens"]), float(raw["threshold"]))


class OnnxSetFitTopicClassifier(TopicClassifier):
    def __init__(self, model_dir: Path) -> None:
        self._manifest = Manifest.read(model_dir / "manifest.json")
        options = ort.SessionOptions()
        options.intra_op_num_threads, options.inter_op_num_threads = THREADS, 1
        self._session: Any = ort.InferenceSession(
            str(model_dir / "body.onnx"), options, providers=["CPUExecutionProvider"]
        )
        self._inputs = {i.name for i in self._session.get_inputs()}
        self._tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        self._tokenizer.no_padding()
        self._tokenizer.enable_truncation(self._manifest.max_tokens)
        head = np.load(model_dir / "head.npz")
        self._coef, self._intercept = head["coef"].astype(np.float32), head["intercept"].astype(np.float32)
        if self._coef.shape[0] != 1 or self._intercept.shape != (1,):
            raise ValueError(f"{model_dir / 'head.npz'}: a binary logistic head has one row, not {self._coef.shape[0]}")

    @property
    def default_threshold(self) -> float:
        return self._manifest.threshold

    async def classify(self, question: str, history: Sequence[HistoryTurn]) -> TopicVerdict:
        texts = topic_texts(question, previous_question(history))
        scores = await asyncio.to_thread(self.p_off_topic, texts)
        return TopicVerdict(min(scores), self._manifest.version)

    def p_off_topic(self, texts: Sequence[str]) -> list[float]:
        """P(off-topic) of each text, one at a time (no padding)."""
        return [self._score(text) for text in texts]

    def _score(self, text: str) -> float:
        encoding = self._tokenizer.encode(text)
        ids = np.array([encoding.ids], dtype=np.int64)
        mask = np.array([encoding.attention_mask], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask, "token_type_ids": np.zeros_like(ids)}
        hidden = self._session.run(None, {k: v for k, v in feed.items() if k in self._inputs})[0]  # (1, tokens, dim)
        if self._manifest.pooling == "cls":
            vector = hidden[:, 0]
        else:
            weights = mask[..., None].astype(np.float32)
            vector = (hidden * weights).sum(axis=1) / np.maximum(weights.sum(axis=1), 1e-9)
        if self._manifest.normalize:
            vector = vector / np.maximum(np.linalg.norm(vector, axis=1, keepdims=True), 1e-12)
        logit = float((vector @ self._coef.T + self._intercept)[0, 0])
        return 1 / (1 + math.exp(-logit))
```

- [ ] **Step 6: Run tests and checks**

Run: `cd backend && uv run pytest tests/unit/tutoring/test_onnx_topic_classifier.py -v && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: 11 passed; lint-imports clean. If mypy reports `Skipping analyzing "onnxruntime": module is installed, but missing library stubs or py.typed marker`, add the block below to `pyproject.toml` after `[tool.mypy]` and rerun:

```toml
[[tool.mypy.overrides]]
module = ["onnxruntime", "onnxruntime.*"]
ignore_missing_imports = true
```

- [ ] **Step 7: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/src/smart_tutor/tutoring/adapters/onnx_topic_classifier.py backend/tests/fakes backend/tests/unit/tutoring/test_onnx_topic_classifier.py
git commit -m "Classify topics with a SetFit model on onnxruntime" -m "The agent must run the topic check in-process on the 2-vCPU host without torch; the spike showed an ONNX export of a SetFit body plus a numpy head matches SetFit exactly (research note 2026-10-13)." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Configuration, agent wiring, and the agent image

**Files:**
- Modify: `backend/src/smart_tutor/shared/config.py` (`TopicCheckConfig`, `Settings.topic_check`)
- Create: `backend/src/smart_tutor/apps/agent/topic.py`
- Modify: `backend/src/smart_tutor/apps/agent/server.py` (lifespan)
- Modify: `backend/pyproject.toml` (new import contract)
- Modify: `backend/Dockerfile`
- Create: `backend/models/topic_check/README.md`
- Modify: `.env.example`
- Test: `backend/tests/unit/apps/agent/test_topic.py`

**Interfaces:**
- Consumes: `OnnxSetFitTopicClassifier` (Task 5), `build_graph(..., topic_classifier, topic_threshold, topic_timeout_ms)` (Task 2).
- Produces:
  - `TopicCheckConfig(provider: Literal["off", "setfit"] = "off", model_dir: str = "models/topic_check", threshold: float | None = None, timeout_ms: PositiveInt = 250)`.
  - `smart_tutor.apps.agent.topic.topic_classifier(config: TopicCheckConfig) -> TopicClassifier | None`.
  - `topic_threshold(config: TopicCheckConfig, classifier: TopicClassifier | None) -> float`.

- [ ] **Step 1: Write the failing tests** `backend/tests/unit/apps/agent/test_topic.py`

```python
"""Building the topic check from settings (spec 2026-10-13 §5.4)."""

from pathlib import Path

import pytest

from fakes import write_topic_model
from smart_tutor.apps.agent.topic import topic_classifier, topic_threshold
from smart_tutor.shared.config import Settings, TopicCheckConfig
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier


def test_the_check_is_off_by_default() -> None:
    config = Settings(_env_file=None).topic_check
    assert config.provider == "off" and config.model_dir == "models/topic_check" and config.timeout_ms == 250
    assert topic_classifier(config) is None


def test_settings_read_the_topic_check_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SMART_TUTOR_TOPIC_CHECK__PROVIDER", "setfit")
    monkeypatch.setenv("SMART_TUTOR_TOPIC_CHECK__MODEL_DIR", "/m")
    monkeypatch.setenv("SMART_TUTOR_TOPIC_CHECK__THRESHOLD", "0.8")
    config = Settings(_env_file=None).topic_check
    assert (config.provider, config.model_dir, config.threshold) == ("setfit", "/m", 0.8)


def test_setfit_loads_the_model_and_its_threshold(tmp_path: Path) -> None:
    write_topic_model(tmp_path, threshold=0.7)
    config = TopicCheckConfig(provider="setfit", model_dir=str(tmp_path))
    classifier = topic_classifier(config)
    assert isinstance(classifier, OnnxSetFitTopicClassifier)
    assert topic_threshold(config, classifier) == 0.7


def test_a_configured_threshold_overrides_the_models(tmp_path: Path) -> None:
    write_topic_model(tmp_path, threshold=0.7)
    config = TopicCheckConfig(provider="setfit", model_dir=str(tmp_path), threshold=0.9)
    assert topic_threshold(config, topic_classifier(config)) == 0.9


def test_setfit_without_a_model_stops_startup(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        topic_classifier(TopicCheckConfig(provider="setfit", model_dir=str(tmp_path / "missing")))


def test_an_unknown_provider_is_refused() -> None:
    with pytest.raises(ValueError):
        TopicCheckConfig(provider="jev")  # type: ignore[arg-type]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/apps/agent/test_topic.py -v`
Expected: FAIL with `ImportError: cannot import name 'TopicCheckConfig'`

- [ ] **Step 3: Add the settings.** In `backend/src/smart_tutor/shared/config.py`, after `ChunkingConfig`:

```python
class TopicCheckConfig(BaseModel):
    """The topic check before search (PRD §9.2 step 0, spec 2026-10-13). Off until a model passes the topic_check eval;
    another decision model joins as a new provider (§5.4)."""

    provider: Literal["off", "setfit"] = "off"
    # The SetFit model directory, relative to the working directory: /app/models/topic_check in the agent image,
    # backend/models/topic_check on the host and in CI.
    model_dir: str = "models/topic_check"
    # None: the threshold tuned with the model (its manifest). A number overrides it.
    threshold: float | None = Field(default=None, ge=0, le=1)
    # A slower check fails open: the question goes on to search.
    timeout_ms: PositiveInt = 250
```

In `Settings`, after `chunking: ChunkingConfig = ChunkingConfig()`, add `topic_check: TopicCheckConfig = TopicCheckConfig()`.

- [ ] **Step 4: Write the composition helpers** `backend/src/smart_tutor/apps/agent/topic.py`

```python
"""The agent's topic check from settings (spec 2026-10-13 §5.4). Shared by the server and the eval targets."""

from pathlib import Path

from smart_tutor.shared.config import TopicCheckConfig
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier
from smart_tutor.tutoring.application import TopicClassifier


def topic_classifier(config: TopicCheckConfig) -> TopicClassifier | None:
    """The configured classifier, or None when the check is off. A missing or broken model raises: startup stops."""
    if config.provider == "off":
        return None
    return OnnxSetFitTopicClassifier(Path(config.model_dir))


def topic_threshold(config: TopicCheckConfig, classifier: TopicClassifier | None) -> float:
    """The configured threshold, else the model's own; 1.0 (never off-topic) when there is no classifier."""
    if config.threshold is not None:
        return config.threshold
    return classifier.default_threshold if classifier is not None else 1.0
```

- [ ] **Step 5: Wire the server.** In `backend/src/smart_tutor/apps/agent/server.py`, add `from smart_tutor.apps.agent.topic import topic_classifier, topic_threshold`, then replace the `if graph is None:` block in `lifespan` with:

```python
        if graph is None:
            model = ModelFactory(settings).chat(ChatRole.AGENT)
            classifier = topic_classifier(settings.topic_check)  # a missing model stops startup
            app.state.graph = build_graph(
                lambda token: McpRetriever(settings.mcp_url, token),
                model,
                settings.answer_floor,
                settings.answer_max_tokens,
                topic_classifier=classifier,
                topic_threshold=topic_threshold(settings.topic_check, classifier),
                topic_timeout_ms=settings.topic_check.timeout_ms,
            )
```

- [ ] **Step 6: Add the import contract.** In `backend/pyproject.toml`, after the "PDF loader only in knowledge.adapters" contract:

```toml
[[tool.importlinter.contracts]]
name = "ONNX topic classifier only in tutoring.adapters (keeps the topic extra in the agent image)"
type = "forbidden"
# Only the agent image installs the topic extra, so only the agent's composition may build this adapter.
ignore_imports = ["smart_tutor.apps.agent.topic -> smart_tutor.tutoring.adapters.onnx_topic_classifier"]
source_modules = [
    "smart_tutor.shared",
    "smart_tutor.apps",
    "smart_tutor.knowledge",
    "smart_tutor.subjects",
    "smart_tutor.learning",
    "smart_tutor.accounts",
    "smart_tutor.insights",
    "smart_tutor.catalog",
    "smart_tutor.quizzes",
    "smart_tutor.recommendations",
    "smart_tutor.reports",
    "smart_tutor.graph",
]
forbidden_modules = ["onnxruntime", "tokenizers"]
```

- [ ] **Step 7: Build the agent image with the extra and the model directory.** In `backend/Dockerfile`:
  - Change the header's last line to: `# CronJobs reuse the api image. Only the worker installs the `ingest` extra (pypdf and LangChain text splitters, ADR 0005); only the agent installs the `topic` extra (onnxruntime and tokenizers) and carries the topic-check model (ADR 0018).`
  - After the `deps-ingest` stage, add:

```dockerfile
FROM base AS deps-agent
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra topic --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra topic --no-editable
```

  - Change the `agent` target to:

```dockerfile
FROM runtime AS agent
COPY --from=deps-agent /app/.venv /app/.venv
COPY models/topic_check /app/models/topic_check
EXPOSE 8080
CMD ["uvicorn", "smart_tutor.apps.agent.server:app", "--host", "0.0.0.0", "--port", "8080"]
```

- [ ] **Step 8: Add the model directory's README** `backend/models/topic_check/README.md`

```markdown
# Topic-check model

The SetFit model the agent's topic check runs (spec `sdd/specs/2026-10-13-off-topic-questions-design.md`, ADR 0018).
`make topic-check-train` writes it here:

| File | What |
|---|---|
| `body.onnx` | int8 sentence-transformer body, dynamic shapes |
| `tokenizer.json` | its tokenizer |
| `head.npz` | logistic head: `coef` (1, dim), `intercept` (1,); class 1 = off-topic |
| `manifest.json` | version, base model, pooling, normalize, max tokens, tuned threshold, training data |

The agent image copies this folder to `/app/models/topic_check`. The check stays off
(`SMART_TUTOR_TOPIC_CHECK__PROVIDER=off`) until a committed model passes the `topic_check` eval. A retrain
replaces the files in a PR that records the eval results; each version adds about 30 MB to git history.
```

- [ ] **Step 9: Document the settings in `.env.example`.** After the `# SMART_TUTOR_MODELS__AGENT__MODEL_ID=...` line, add:

```
# Topic check before search (spec 2026-10-13): off until a model in backend/models/topic_check passes its eval.
# The model directory is relative to the working directory (backend/ on the host, /app in the image).
# SMART_TUTOR_TOPIC_CHECK__PROVIDER=setfit
```

- [ ] **Step 10: Run the checks and build both images**

Run: `cd backend && uv run pytest -q && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

Run: `docker build --target agent -t smart-tutor-agent:topic backend/ && docker run --rm smart-tutor-agent:topic python -c "import onnxruntime, tokenizers; print('ok')"`
Expected: `ok`.

Run: `docker build --target api -t smart-tutor-api:topic backend/ && docker run --rm smart-tutor-api:topic python -c "import onnxruntime"`
Expected: `ModuleNotFoundError: No module named 'onnxruntime'`. The api image stays without the extra.

If Docker isn't available, say so in the task report; CI's image build covers it.

- [ ] **Step 11: Commit**

```bash
git add backend/src/smart_tutor/shared/config.py backend/src/smart_tutor/apps/agent backend/pyproject.toml backend/Dockerfile backend/models/topic_check/README.md .env.example backend/tests/unit/apps/agent/test_topic.py
git commit -m "Configure the topic check and ship it in the agent image" -m "The check is off by default and turns on with SMART_TUTOR_TOPIC_CHECK__PROVIDER=setfit; a missing model stops startup instead of silently running without it. Only the agent image gets onnxruntime and the model folder." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: The ask evals understand off-topic declines

**Files:**
- Modify: `backend/evals/evaluators/search_step_ran.py`, `backend/evals/evaluators/decline_correctness.py`
- Modify: `backend/evals/targets.py` (`AskTarget` topic parameters, `ask_target`)
- Test: `backend/tests/unit/evals/test_search_step_ran.py`, `backend/tests/unit/evals/test_decline_correctness.py`, `backend/tests/unit/evals/test_targets.py`

**Interfaces:**
- Consumes: `build_graph` topic arguments (Task 2), `topic_classifier` and `topic_threshold` (Task 6), `FakeTopicClassifier` (Task 1).
- Produces: `AskTarget(..., topic_classifier: TopicClassifier | None = None, topic_threshold: float = 1.0, topic_timeout_ms: int = 250)`. An ask example may carry `outputs.off_topic: true`.

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/unit/evals/test_search_step_ran.py`:

```python
def test_an_off_topic_decline_without_a_search_is_not_applicable() -> None:
    result = search_step_ran({"limit": None, "trajectory": [], "decline": "off_topic"})
    assert result["score"] is None and result["value"] == "n/a"


def test_an_off_topic_decline_that_still_searched_scores_0() -> None:
    result = search_step_ran({"limit": None, "trajectory": [_call(None, ["d1"])], "decline": "off_topic"})
    assert result["score"] == 0 and "off-topic" in result["comment"]
```

Append to `backend/tests/unit/evals/test_decline_correctness.py`. Use the module's existing import of `correctly_declined`; add it if absent.

```python
def test_an_off_topic_example_is_correctly_declined_only_as_off_topic() -> None:
    inputs = {"question": "Tell me a joke.", "learner": "l", "documents": None}
    reference = {"covered": False, "sources": [], "off_topic": True}
    assert correctly_declined(inputs, {"decline": "off_topic"}, reference)["score"] == 1
    assert correctly_declined(inputs, {"decline": None, "answer": "Ha"}, reference)["score"] == 0
    assert correctly_declined(inputs, {"decline": "no_documents"}, reference)["score"] == 0
```

Append to `backend/tests/unit/evals/test_targets.py`, adding the imports `from fakes import FakeTopicClassifier, fake_chat_model` (merge with the existing `fakes` import) and `from smart_tutor.tutoring.application import OFF_TOPIC_DECLINE`:

```python
async def test_an_off_topic_example_is_declined_without_a_search() -> None:
    retriever = FakeRetriever(CHUNKS)
    target = AskTarget(
        FakeLearners(),
        lambda token: retriever,
        fake_chat_model(),
        0.3,
        topic_classifier=FakeTopicClassifier({"Tell me a joke.": 0.99}),
        topic_threshold=0.5,
    )
    out = await target({**ASK, "question": "Tell me a joke."})
    assert out["decline"] == "off_topic" and out["answer"] == OFF_TOPIC_DECLINE
    assert out["trajectory"] == [] and retriever.calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/evals/test_search_step_ran.py tests/unit/evals/test_decline_correctness.py tests/unit/evals/test_targets.py -v`
Expected: the new tests FAIL: the search eval scores 0, the off-topic reference raises `KeyError` or misscores, and `AskTarget` rejects `topic_classifier`.

- [ ] **Step 3: Update `search_step_ran`.** Add `not_applicable` to the `evals.suite` import (`from evals.suite import Suite, not_applicable`). In `search_step_ran`, right after the `"trajectory" not in outputs` check:

```python
    searches = [c for c in outputs["trajectory"] if c["tool"] == "search"]
    if outputs.get("decline") == "off_topic":  # declined before search (spec 2026-10-13); PRD §10.1: answered turns
        if searches:
            return _score(0, "an off-topic decline still searched")
        return not_applicable(KEY, "an off-topic question is declined before search")
```

Remove the now-duplicate `searches = …` line below it. Add to the docstring: "An off-topic decline makes no search and is not applicable."

- [ ] **Step 4: Update `decline_correctness`.** At the top of `correctly_declined`, before `if reference_outputs["covered"]:`:

```python
    if reference_outputs.get("off_topic"):  # declined by the topic check before search (spec 2026-10-13)
        if "decline" not in outputs:
            return {"key": "decline_correctness.correctly_declined", "score": 0, "comment": FAILED}
        if outputs["decline"] == "off_topic":
            return {"key": "decline_correctness.correctly_declined", "score": 1, "comment": "declined (off_topic)"}
        return {
            "key": "decline_correctness.correctly_declined",
            "score": 0,
            "comment": f"not declined as off-topic: {outputs['decline'] or 'answered'}",
        }
```

In the module docstring, add after the first sentence: "An example marked `off_topic` must get the `off_topic` decline, limited or not."

- [ ] **Step 5: Give `AskTarget` the topic check.** In `backend/evals/targets.py`:
  - add the imports `from smart_tutor.apps.agent.topic import topic_classifier, topic_threshold` and `from smart_tutor.tutoring.application import TopicClassifier` (merge with existing imports);
  - extend `AskTarget.__init__`:

```python
    def __init__(
        self,
        learners: Learners,
        retriever_for: Callable[[str], Retriever],
        model: BaseChatModel,
        answer_floor: float,
        answer_max_tokens: int = 1500,
        history_turns: int = 5,
        history_answer_chars: int = 2000,
        topic_classifier: TopicClassifier | None = None,
        topic_threshold: float = 1.0,
        topic_timeout_ms: int = 250,
    ) -> None:
        self._learners, self._retriever_for = learners, retriever_for
        self._model, self._answer_floor, self._answer_max_tokens = model, answer_floor, answer_max_tokens
        self._history_turns, self._history_answer_chars = history_turns, history_answer_chars
        self._topic = (topic_classifier, topic_threshold, topic_timeout_ms)
```

In `_ask`:

```python
        classifier, threshold, timeout_ms = self._topic
        graph = build_graph(
            lambda t: RecordingRetriever(self._retriever_for(t), calls),
            self._model,
            self._answer_floor,
            self._answer_max_tokens,
            topic_classifier=classifier,
            topic_threshold=threshold,
            topic_timeout_ms=timeout_ms,
        )
```

In `ask_target()`:

```python
    classifier = topic_classifier(settings.topic_check)  # off until .env turns it on
    return AskTarget(
        eval_learners,
        lambda token: McpRetriever(settings.mcp_url, token),
        ModelFactory(settings).chat(ChatRole.AGENT),
        settings.answer_floor,
        settings.answer_max_tokens,
        settings.history_turns,
        settings.history_answer_chars,
        topic_classifier=classifier,
        topic_threshold=topic_threshold(settings.topic_check, classifier),
        topic_timeout_ms=settings.topic_check.timeout_ms,
    )
```

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/unit/evals -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/evals backend/tests/unit/evals
git commit -m "Score off-topic declines in the ask evals" -m "With the topic check, an off-topic turn makes no search, so search_step_ran must not fail it; an example marked off_topic must get that decline; and the ask target runs the configured check like the agent does." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: The `topic_check` dataset and its train/eval split

**Files:**
- Create: `backend/evals/datasets/topic_check.yaml`
- Modify: `backend/evals/dataset.py` (`eval_share`, `normalized`, `in_eval_share`)
- Modify: `backend/evals/publish.py` (publish only the held-out share)
- Test: `backend/tests/unit/evals/test_dataset.py`, `backend/tests/unit/evals/test_publish.py`

**Interfaces:**
- Produces:
  - `Dataset.eval_share: float | None = None` (the last field).
  - `normalized(question: str) -> str`.
  - `in_eval_share(question: str, share: float) -> bool`.
  - Dataset key `topic_check`, LangSmith name `smart-tutor-topic-check`, examples `inputs: {question, history?: [{question, answer}]}`, `outputs: {off_topic: bool, kind: str}`.

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/unit/evals/test_dataset.py`; merge `in_eval_share` and `normalized` into its `evals.dataset` import.

```python
KINDS = {
    "subject_concept", "document_question", "follow_up", "study_task",
    "greeting", "entertainment", "personal_task", "live_information",
}


def test_the_topic_check_dataset_labels_both_sides_and_holds_out_a_share() -> None:
    dataset = load_dataset("topic_check")
    assert dataset.name == "smart-tutor-topic-check" and dataset.eval_share == 0.3
    assert all(isinstance(e.outputs["off_topic"], bool) and e.outputs["kind"] in KINDS for e in dataset.examples)
    assert sum(not e.outputs["off_topic"] for e in dataset.examples) >= 15
    assert sum(e.outputs["off_topic"] for e in dataset.examples) >= 12
    follow_ups = [e for e in dataset.examples if e.outputs["kind"] == "follow_up"]
    assert follow_ups and all(e.inputs["history"][-1]["question"] for e in follow_ups)


def test_an_eval_share_outside_0_and_1_is_refused(tmp_path: Path) -> None:
    (tmp_path / "s.yaml").write_text("name: s\neval_share: 1.5\nexamples: [{inputs: {q: a}}]\n", encoding="utf-8")
    with pytest.raises(DatasetError, match="eval_share"):
        load_dataset("s", tmp_path)


def test_the_held_out_share_is_stable_ignores_case_and_spacing_and_is_about_its_size() -> None:
    assert normalized("  What IS  attention? ") == "what is attention?"
    assert in_eval_share("What is attention?", 0.3) == in_eval_share("what is   ATTENTION?", 0.3)
    held = sum(in_eval_share(f"question number {i}", 0.3) for i in range(4000))
    assert 0.27 < held / 4000 < 0.33
```

Append to `backend/tests/unit/evals/test_publish.py`, adding `in_eval_share` to the `evals.dataset` import:

```python
def test_a_dataset_with_an_eval_share_publishes_only_its_held_out_questions() -> None:
    client = FakeLangSmith()
    shared = Dataset("ask", "smart-tutor-ask", "", HAND, eval_share=0.3)
    questions = [f"question {i}" for i in range(40)]
    _accept(client, *questions)
    assert main([], client=client, load=lambda key: shared, keys=["ask"]) == 0
    full = {e.inputs["question"] for e in examples_at(client, shared, "full", "full-v1")}
    assert full == {"hand"} | {q for q in questions if in_eval_share(q, 0.3)}
    assert 1 < len(full) < 41
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/evals/test_dataset.py tests/unit/evals/test_publish.py -v`
Expected: FAIL with `ImportError: cannot import name 'in_eval_share'`.

- [ ] **Step 3: Extend `evals/dataset.py`.** Add `import hashlib`. Add the field `eval_share: float | None = None` as the last field of `Dataset`, with the comment `# a share of generated examples held out for evaluation; the rest train a model (topic_check)`. Replace the `return Dataset(...)` in `load_dataset` with:

```python
    share = raw.get("eval_share")
    if share is not None and not 0 < float(share) < 1:
        raise DatasetError(f"{path.name}: eval_share must be between 0 and 1, not {share}")
    return Dataset(
        key, raw["name"], raw.get("description", ""), examples, pins, None if share is None else float(share)
    )
```

Append:

```python
def normalized(question: str) -> str:
    return " ".join(question.lower().split())


def in_eval_share(question: str, share: float) -> bool:
    """Whether a generated example is held out for evaluation: a stable hash of its normalized question, so it never
    moves between training and evaluation (spec 2026-10-13 §6.1)."""
    digest = hashlib.sha256(normalized(question).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < share
```

- [ ] **Step 4: Publish only the held-out share.** In `evals/publish.py`, add `in_eval_share` to the `evals.dataset` import. In `main`, replace `splits = split_examples(dataset, generated_examples(client, dataset))` with:

```python
            accepted = generated_examples(client, dataset)
            if dataset.eval_share is not None:  # the rest trains a model (evals.topic_check.train), never evaluates it
                accepted = [e for e in accepted if in_eval_share(str(e.inputs["question"]), dataset.eval_share)]
            splits = split_examples(dataset, accepted)
```

- [ ] **Step 5: Write the dataset file** `backend/evals/datasets/topic_check.yaml`

```yaml
# The topic check (spec 2026-10-13 §3, §6): learner messages labeled on-topic (study, understand, research) or
# off-topic. LangSmith dataset `name`. These hand-written examples are in every version of both splits and never train
# the model; generated examples join after a human accepts them (make evals-generate DATASET=topic_check), split by a
# stable hash of the question: `eval_share` of them are published here, the rest train the model
# (make topic-check-train).
#
# inputs:  question; history (follow-ups): the earlier turn, [{question, answer}].
# outputs: off_topic: whether the tutor must decline it before search; kind: one of generators/topic_check.py KINDS.
name: smart-tutor-topic-check
description: Learner messages labeled on-topic or off-topic for the Smart Tutor topic check (backend/evals/datasets/topic_check.yaml).
eval_share: 0.3
examples:
  - {inputs: {question: "What problem does the transformer architecture solve compared with RNNs?"}, outputs: {off_topic: false, kind: subject_concept}}
  - {inputs: {question: "Explain photosynthesis in simple terms."}, outputs: {off_topic: false, kind: subject_concept}}
  - {inputs: {question: "Explain the difference between mitosis and meiosis."}, outputs: {off_topic: false, kind: subject_concept}}
  - {inputs: {question: "How do I calculate the derivative of x squared times sine x?"}, outputs: {off_topic: false, kind: subject_concept}}
  - {inputs: {question: "Can you give me an example of a Bayesian prior?"}, outputs: {off_topic: false, kind: subject_concept}}
  - {inputs: {question: "Summarize the main findings of the paper I uploaded on retrieval-augmented generation."}, outputs: {off_topic: false, kind: document_question}}
  - {inputs: {question: "What caused the fall of the Western Roman Empire according to this book?"}, outputs: {off_topic: false, kind: document_question}}
  - {inputs: {question: "How long should I rest a steak after grilling, according to the cookbook?"}, outputs: {off_topic: false, kind: document_question}}
  - {inputs: {question: "Which team won the match described in the sports article and why?"}, outputs: {off_topic: false, kind: document_question}}
  - {inputs: {question: "What is a SQL injection attack and how does the paper suggest preventing it?"}, outputs: {off_topic: false, kind: document_question}}
  - {inputs: {question: "How does the author define inflation in chapter 3?"}, outputs: {off_topic: false, kind: document_question}}
  - {inputs: {question: "Compare the two studies on intermittent fasting in my library."}, outputs: {off_topic: false, kind: document_question}}
  - {inputs: {question: "What are the limitations of the proposed method?"}, outputs: {off_topic: false, kind: document_question}}
  - {inputs: {question: "What does the magazine article say about electric car battery recycling?"}, outputs: {off_topic: false, kind: document_question}}
  - {inputs: {question: "Who wrote the news story about the election and what were its key claims?"}, outputs: {off_topic: false, kind: document_question}}
  - {inputs: {question: "Explain that more simply.", history: [{question: "What is gradient descent?", answer: ""}]}, outputs: {off_topic: false, kind: follow_up}}
  - {inputs: {question: "And what are its limitations?", history: [{question: "What are the main results of the BERT paper?", answer: ""}]}, outputs: {off_topic: false, kind: follow_up}}
  - {inputs: {question: "Why does it need to be fed every day?", history: [{question: "How does the cookbook make sourdough starter?", answer: ""}]}, outputs: {off_topic: false, kind: follow_up}}
  - {inputs: {question: "Thanks! Can you give me an example?", history: [{question: "What does chapter 2 say about the French Revolution?", answer: ""}]}, outputs: {off_topic: false, kind: follow_up}}
  - {inputs: {question: "Help me plan my study week for the biology exam."}, outputs: {off_topic: false, kind: study_task}}
  - {inputs: {question: "Make me a quiz on the uploaded chemistry chapter."}, outputs: {off_topic: false, kind: study_task}}
  - {inputs: {question: "hi, how are you today?"}, outputs: {off_topic: true, kind: greeting}}
  - {inputs: {question: "What can you do?"}, outputs: {off_topic: true, kind: greeting}}
  - {inputs: {question: "Tell me a joke about cats."}, outputs: {off_topic: true, kind: entertainment}}
  - {inputs: {question: "Let's role-play: you are a pirate captain."}, outputs: {off_topic: true, kind: entertainment}}
  - {inputs: {question: "Write me a love poem for my girlfriend."}, outputs: {off_topic: true, kind: entertainment}}
  - {inputs: {question: "Write an email to my landlord asking to fix the heater."}, outputs: {off_topic: true, kind: personal_task}}
  - {inputs: {question: "Plan a 5-day trip to Japan for me."}, outputs: {off_topic: true, kind: personal_task}}
  - {inputs: {question: "Book a flight to Paris."}, outputs: {off_topic: true, kind: personal_task}}
  - {inputs: {question: "Recommend a good restaurant near me."}, outputs: {off_topic: true, kind: personal_task}}
  - {inputs: {question: "Can you help me fix the bug in my React app's login page?"}, outputs: {off_topic: true, kind: personal_task}}
  - {inputs: {question: "What's the weather in Hanoi tomorrow?"}, outputs: {off_topic: true, kind: live_information}}
  - {inputs: {question: "What is the price of an iPhone 17 right now?"}, outputs: {off_topic: true, kind: live_information}}
  - {inputs: {question: "Who do you think will win the football game tonight? Place a bet for me."}, outputs: {off_topic: true, kind: live_information}}
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && uv run pytest tests/unit/evals -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass. If an existing test iterates over every `datasets/*.yaml` and expects ask-style outputs, scope it to the datasets it was written for (`ask`, `injection`).

- [ ] **Step 7: Commit**

```bash
git add backend/evals/dataset.py backend/evals/publish.py backend/evals/datasets/topic_check.yaml backend/tests/unit/evals
git commit -m "Add the topic_check dataset with a held-out eval share" -m "One review queue feeds both training and evaluation, so accepted examples are split by a stable hash of the question: only the held-out share is published, and the model never trains on what grades it." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Generate `topic_check` candidates

**Files:**
- Create: `backend/evals/generators/topic_check.py`
- Modify: `backend/evals/generate.py` (a `topic_check` choice and the `write_topic` injection point)
- Modify: `Makefile` (the `evals-generate` help text)
- Test: `backend/tests/unit/evals/test_generate_topic_check.py`

**Interfaces:**
- Consumes: `Candidate`, `submit` (`evals/review.py`); the dataset key `topic_check` (Task 8).
- Produces:
  - `Kind(off_topic: bool, description: str, examples: tuple[str, ...])`.
  - `KINDS: dict[str, Kind]`.
  - `Write = Callable[[str, Kind, int], Awaitable[list[str]]]`.
  - `message_writer(model: BaseChatModel) -> Write`.
  - `async write_candidates(per_kind: int, write: Write) -> list[Candidate]`.
  - `RUBRIC: str`.
  - `evals.generate.main(..., write_topic: Write | None = None)`.

- [ ] **Step 1: Write the failing tests** `backend/tests/unit/evals/test_generate_topic_check.py`

```python
"""Generated topic_check candidates (spec 2026-10-13 §6.1): every kind, labeled by its kind, follow-ups with history."""

from collections import Counter

import pytest
from langchain_core.messages import AIMessage

from evals.generate import main
from evals.generators.topic_check import KINDS, Kind, message_writer, write_candidates
from fakes import fake_chat_model
from fakes.langsmith import FakeLangSmith


async def write(kind: str, spec: Kind, count: int) -> list[str]:
    if kind == "follow_up":
        return [f"Earlier {i}? || Why {i}?" for i in range(count)]
    return [f"{kind} message {i}" for i in range(count)]


async def test_every_kind_becomes_candidates_labeled_by_its_kind() -> None:
    candidates = await write_candidates(2, write)
    assert Counter(c.type for c in candidates) == {kind: 2 for kind in KINDS}
    for c in candidates:
        assert c.expected == {"off_topic": KINDS[c.type].off_topic, "kind": c.type}
    follow_up = next(c for c in candidates if c.type == "follow_up")
    assert follow_up.inputs == {"question": "Why 0?", "history": [{"question": "Earlier 0?", "answer": ""}]}


def test_the_kinds_cover_both_sides_of_the_policy() -> None:
    assert {k for k, v in KINDS.items() if not v.off_topic} == {
        "subject_concept", "document_question", "follow_up", "study_task",
    }
    assert {k for k, v in KINDS.items() if v.off_topic} == {
        "greeting", "entertainment", "personal_task", "live_information",
    }


async def test_a_kind_whose_writing_fails_is_dropped_not_the_batch() -> None:
    async def flaky(kind: str, spec: Kind, count: int) -> list[str]:
        if kind == "greeting":
            raise RuntimeError("throttled")
        return await write(kind, spec, count)

    candidates = await write_candidates(1, flaky)
    assert "greeting" not in {c.type for c in candidates} and len(candidates) == len(KINDS) - 1


async def test_blank_duplicate_and_malformed_follow_up_lines_are_dropped() -> None:
    async def messy(kind: str, spec: Kind, count: int) -> list[str]:
        return ["no separator", " || empty earlier"] if kind == "follow_up" else ["a", "a", "  "]

    candidates = await write_candidates(3, messy)
    assert "follow_up" not in {c.type for c in candidates}
    assert all(c.inputs == {"question": "a"} for c in candidates)


async def test_the_writer_reads_one_message_per_line_without_numbering() -> None:
    writer = message_writer(fake_chat_model(AIMessage("1. hi there\n2) hello\n- yo\n\n")))
    assert await writer("greeting", KINDS["greeting"], 3) == ["hi there", "hello", "yo"]


def test_generate_queues_topic_check_candidates(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeLangSmith()
    assert main(["topic_check", "--per-type", "1"], client=client, write_topic=write, model_id="m") == 0
    [queue] = client.queues.values()
    assert len(queue.run_ids) == len(KINDS)
    assert f"{len(KINDS)} candidates" in capsys.readouterr().out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/evals/test_generate_topic_check.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.generators.topic_check'`

- [ ] **Step 3: Write the generator** `backend/evals/generators/topic_check.py`

```python
"""topic_check candidates (spec 2026-10-13 §3, §6.1): the judge model writes learner messages of each kind, labeled
on-topic or off-topic by the kind; a human accepts or rejects each in the annotation queue (evals.review).

Usage: make evals-generate DATASET=topic_check (python -m evals.generate topic_check --per-type N)
"""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage

from evals.review import Candidate

LOG = logging.getLogger(__name__)
MAX_QUESTION_CHARS = 4000  # the API's question limit (routes/threads.py)
FOLLOW_UP_SEPARATOR = " || "


@dataclass(frozen=True)
class Kind:
    off_topic: bool
    description: str
    examples: tuple[str, ...]


KINDS: dict[str, Kind] = {
    "subject_concept": Kind(
        False,
        "a question asking to explain or understand a concept in any school, university, or professional subject; vary "
        "the subjects widely, including cooking, sports, finance, security, art, music, law, and medicine",
        ("Explain photosynthesis in simple terms.", "How do I calculate the derivative of x squared times sine x?"),
    ),
    "document_question": Kind(
        False,
        "a question about a paper, book, chapter, magazine article, or news article the learner uploaded",
        ("How does the author define inflation in chapter 3?", "What does the sports article say about the final?"),
    ),
    "follow_up": Kind(
        False,
        f"a short follow-up to an earlier study question, written as `earlier question{FOLLOW_UP_SEPARATOR}follow-up`",
        (
            f"What is gradient descent?{FOLLOW_UP_SEPARATOR}Explain that more simply.",
            f"How does the cookbook make sourdough starter?{FOLLOW_UP_SEPARATOR}Why does it need to be fed every day?",
        ),
    ),
    "study_task": Kind(
        False,
        "a request for help studying the learner's own material: quizzes, flashcards, summaries, study plans, practice "
        "questions",
        ("Make me a quiz on the uploaded chemistry chapter.", "Help me plan my study week for the biology exam."),
    ),
    "greeting": Kind(
        True,
        "a greeting, small talk, thanks with no question, or a question about the assistant itself",
        ("hi, how are you today?", "What can you do?"),
    ),
    "entertainment": Kind(
        True,
        "a request for jokes, stories, poems, songs, games, or role-play",
        ("Tell me a joke about cats.", "Let's role-play: you are a pirate captain."),
    ),
    "personal_task": Kind(
        True,
        "a personal errand or task that is not studying: emails, messages, trip plans, bookings, shopping, "
        "recommendations, fixing the learner's own code or devices",
        ("Write an email to my landlord asking to fix the heater.", "Can you help me fix the bug in my React app?"),
    ),
    "live_information": Kind(
        True,
        "a request for live or real-time information: weather, prices, scores, traffic, opening hours, today's news",
        ("What's the weather in Hanoi tomorrow?", "What is the price of an iPhone 17 right now?"),
    ),
}

RUBRIC = """\
Each item is a learner message proposed for the topic_check dataset, with its kind (outputs.evidence) and the expected
label (outputs.expected.off_topic). On-topic: anything a learner asks in order to study, understand, or research, in any
subject; questions about their documents; follow-ups; study tasks on their material. Off-topic: greetings and questions
about the tutor itself, entertainment, personal tasks, live information (spec 2026-10-13 §3). Accept (1) only when the
message is realistic and the label is right by that policy. Reject (0) anything ambiguous or that you would need to edit.
"""

WRITER = """You write test messages for an AI study tutor. Learners upload papers, books, magazines, and news articles \
and ask the tutor to help them study and understand them.

Write {count} different messages a learner might type, each of them {description}. Vary the wording, length, tone, \
and subject; make some casual or with small typos. Reply with one message per line and nothing else.

Examples:
{examples}"""

_NUMBERING = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s*")

Write = Callable[[str, Kind, int], Awaitable[list[str]]]


def message_writer(model: BaseChatModel) -> Write:
    """`count` messages of one kind by `model` (the judge model, never the tutor's): one per line of its reply."""

    async def messages(kind: str, spec: Kind, count: int) -> list[str]:
        prompt = WRITER.format(count=count, description=spec.description, examples="\n".join(spec.examples))
        reply = await model.ainvoke([HumanMessage(prompt)])
        lines = (_NUMBERING.sub("", line).strip() for line in reply.text.splitlines())
        return [line for line in lines if line][:count]

    return messages


def _candidate(kind: str, spec: Kind, line: str) -> Candidate | None:
    inputs: dict[str, object]
    if kind == "follow_up":
        earlier, _, question = line.partition(FOLLOW_UP_SEPARATOR.strip())
        earlier, question = earlier.strip(), question.strip()
        if not earlier or not question:
            return None
        inputs = {"question": question, "history": [{"question": earlier, "answer": ""}]}
    else:
        question = line.strip()
        if not question:
            return None
        inputs = {"question": question}
    if len(question) > MAX_QUESTION_CHARS:
        return None
    return Candidate(
        inputs=inputs,
        expected={"off_topic": spec.off_topic, "kind": kind},
        type=kind,
        evidence=({"chunk": f"kind:{kind}", "text": spec.description},),
    )


async def write_candidates(per_kind: int, write: Write) -> list[Candidate]:
    """`per_kind` messages of each kind as review candidates, without duplicates. A kind whose writing fails (a parse
    error or throttling) is dropped, not the batch."""

    async def one(kind: str, spec: Kind) -> list[Candidate]:
        try:
            lines = await write(kind, spec, per_kind)
        except Exception as error:
            LOG.warning("Dropped the %s messages: %s: %s", kind, type(error).__name__, error)
            return []
        seen: set[str] = set()
        out: list[Candidate] = []
        for line in lines:
            candidate = _candidate(kind, spec, line)
            if candidate is not None and (key := str(candidate.inputs)) not in seen:
                seen.add(key)
                out.append(candidate)
        return out

    batches = await asyncio.gather(*(one(kind, spec) for kind, spec in KINDS.items()))
    return [candidate for batch in batches for candidate in batch]
```

- [ ] **Step 4: Wire `evals.generate`.** In `backend/evals/generate.py`:
  - change the import to `from evals.generators import injection, topic_check`;
  - in the module docstring's usage line, add `|topic_check` after `ask|injection`, and add the sentence "topic_check: has the judge model write `--per-type` learner messages of each kind (generators/topic_check.py)";
  - add the keyword `write_topic: topic_check.Write | None = None` to `main`;
  - set `choices=["ask", "injection", "topic_check"]`;
  - replace the `needs_model` line and the model block with:

```python
    writer = {"ask": write, "injection": vary, "topic_check": write_topic}[args.dataset]
    if writer is None or model_id is None:
        from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
        from smart_tutor.shared.config import Settings

        settings = Settings()
        judge = ModelFactory(settings).chat(ChatRole.JUDGE)
        write = write or question_writer(judge)
        vary = vary or injection.variant_writer(judge)
        write_topic = write_topic or topic_check.message_writer(judge)
        model_id = model_id or settings.models.judge.model_id
```

  - Before the `else:` (ask) branch, add:

```python
    elif args.dataset == "topic_check":
        assert write_topic is not None
        rubric, planned = topic_check.RUBRIC, "kinds"
        candidates = asyncio.run(topic_check.write_candidates(args.per_type, write_topic))
        batch = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}"
        dropped = ""
```

In `Makefile`, change the `evals-generate` help to `## propose dataset candidates (DATASET=ask, the default, injection, or topic_check) into the LangSmith annotation queue (AWS profile, LANGSMITH_API_KEY)`.

- [ ] **Step 5: Run tests**

Run: `cd backend && uv run pytest tests/unit/evals -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass, including the existing `test_generate.py`.

- [ ] **Step 6: Commit**

```bash
git add backend/evals/generators/topic_check.py backend/evals/generate.py Makefile backend/tests/unit/evals/test_generate_topic_check.py
git commit -m "Generate topic_check candidates for review" -m "The classifier learns the product's boundary from labeled messages; the judge drafts them per kind of the spec's policy and a reviewer accepts each before it trains or grades anything." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The `topic_check` eval suite, skipped until a model exists

**Files:**
- Modify: `backend/evals/suite.py` (`skip` on `Suite` and `DatasetSuites`)
- Modify: `backend/evals/run.py` (honour `skip`)
- Modify: `backend/evals/targets.py` (`TopicCheckTarget`, `topic_check_target`, `TOPIC_MODEL`)
- Create: `backend/evals/evaluators/topic_check.py`
- Test: `backend/tests/unit/evals/test_suite.py`, `backend/tests/unit/evals/test_run.py`, `backend/tests/unit/evals/test_topic_check_suite.py`

**Interfaces:**
- Consumes: `OnnxSetFitTopicClassifier` (Task 5), `topic_threshold` (Task 6), the `topic_check` dataset (Task 8), `write_topic_model` and `FakeTopicClassifier`.
- Produces:
  - `Suite(dataset, target, evaluators, skip: Callable[[], str | None] | None = None)`; `DatasetSuites` likewise.
  - `TopicCheckTarget(classifier: TopicClassifier, threshold: float)` returning `{"off_topic": bool, "p_off_topic": float, "model": str}`.
  - `TOPIC_MODEL: Path` (`backend/models/topic_check`).
  - Metrics `topic_check.false_rejections` and `topic_check.off_topic_caught`.

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/unit/evals/test_run.py`:

```python
async def test_a_suite_that_is_not_ready_is_skipped_and_its_metrics_stay_not_run(
    capsys: pytest.CaptureFixture[str],
) -> None:
    client = published()
    group = DatasetSuites("ask", make_target, (scored("search_step_ran", 1.0),), skip=lambda: "no model yet")
    scores, links = await run_split(client, [group], "smoke", load=lambda key: ASK)
    assert scores == {} and links == {} and client.experiments == []
    assert "no model yet" in capsys.readouterr().err
```

Append to `backend/tests/unit/evals/test_suite.py`, importing `by_dataset`, `Suite` and `DatasetSuites` if the file doesn't already:

```python
def test_a_datasets_suites_carry_the_first_skip() -> None:
    def target():  # pragma: no cover - never called
        raise AssertionError

    def skip() -> str | None:
        return "not ready"

    [group] = by_dataset([Suite("d", target, ()), Suite("d", target, (), skip=skip)])
    assert group.skip is skip
```

Create `backend/tests/unit/evals/test_topic_check_suite.py`:

```python
"""The topic_check suite (spec 2026-10-13 §6.3): the classifier alone, scored as false rejections and off-topic caught."""

from pathlib import Path

from evals.evaluators.topic_check import SUITE, false_rejections, off_topic_caught
from evals.targets import TopicCheckTarget
from fakes import FakeTopicClassifier, write_topic_model
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier

ON, OFF = {"off_topic": False, "kind": "subject_concept"}, {"off_topic": True, "kind": "entertainment"}


async def test_the_target_reports_the_verdict_with_the_history_given() -> None:
    classifier = FakeTopicClassifier({"Tell me a joke.": 0.9})
    target = TopicCheckTarget(classifier, 0.5)
    out = await target({"question": "Tell me a joke.", "history": [{"question": "Earlier?", "answer": ""}]})
    assert out == {"off_topic": True, "p_off_topic": 0.9, "model": "fake@1"}
    [(question, history)] = classifier.calls
    assert question == "Tell me a joke." and [h.question for h in history] == ["Earlier?"]


async def test_the_target_runs_the_onnx_model(tmp_path: Path) -> None:
    target = TopicCheckTarget(OnnxSetFitTopicClassifier(write_topic_model(tmp_path)), 0.5)
    assert (await target({"question": "Explain photosynthesis"}))["off_topic"] is False


def test_an_on_topic_example_declined_is_a_false_rejection() -> None:
    assert false_rejections({"off_topic": True, "p_off_topic": 0.8}, ON)["score"] == 1
    assert false_rejections({"off_topic": False, "p_off_topic": 0.1}, ON)["score"] == 0
    assert false_rejections({"off_topic": True, "p_off_topic": 0.8}, OFF)["value"] == "n/a"


def test_an_off_topic_example_declined_is_caught() -> None:
    assert off_topic_caught({"off_topic": True, "p_off_topic": 0.8}, OFF)["score"] == 1
    assert off_topic_caught({"off_topic": False, "p_off_topic": 0.2}, OFF)["score"] == 0
    assert off_topic_caught({"off_topic": False, "p_off_topic": 0.2}, ON)["value"] == "n/a"


def test_a_failed_run_counts_against_both() -> None:
    assert false_rejections({}, ON)["score"] == 1
    assert off_topic_caught({}, OFF)["score"] == 0


def test_the_suite_runs_on_topic_check_and_is_skipped_without_a_model() -> None:
    assert SUITE.dataset == "topic_check" and SUITE.skip is not None
    reason = SUITE.skip()
    assert reason is None or "make topic-check-train" in reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/evals/test_run.py tests/unit/evals/test_suite.py tests/unit/evals/test_topic_check_suite.py -v`
Expected: FAIL with `TypeError: ... unexpected keyword argument 'skip'` and `ModuleNotFoundError: evals.evaluators.topic_check`.

- [ ] **Step 3: Add `skip` to suites.** In `backend/evals/suite.py`, add `skip: Callable[[], str | None] | None = None` as the last field of both `Suite` and `DatasetSuites`, with the comment `# a reason the suite can't run yet (e.g. no model): its metrics stay "not run"`. In `by_dataset`:

```python
        if group is None:
            groups[suite.dataset] = DatasetSuites(suite.dataset, suite.target, suite.evaluators, suite.skip)
        elif group.target is not suite.target:
            raise ValueError(f"suites on the {suite.dataset} dataset name different targets")
        else:
            groups[suite.dataset] = DatasetSuites(
                suite.dataset, group.target, group.evaluators + suite.evaluators, group.skip or suite.skip
            )
```

In `backend/evals/run.py` `run_split`, right after `dataset = load(group.dataset)`:

```python
        if group.skip is not None and (why := group.skip()) is not None:  # its metrics stay "not run"
            print(f"{dataset.name} skipped: {why}", file=sys.stderr)
            continue
```

- [ ] **Step 4: Add the target.** In `backend/evals/targets.py`:
  - add `from pathlib import Path` if missing;
  - add `from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier`;
  - make sure `HistoryTurn` and `TopicClassifier` are imported from `smart_tutor.tutoring.application`;
  - append:

```python
TOPIC_MODEL = Path(__file__).parents[1] / "models" / "topic_check"  # backend/models/topic_check


class TopicCheckTarget:
    """The topic check alone (spec 2026-10-13 §6.3): no Bedrock, no MCP."""

    def __init__(self, classifier: TopicClassifier, threshold: float) -> None:
        self._classifier, self._threshold = classifier, threshold

    async def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        history = [HistoryTurn(t["question"], t.get("answer", "")) for t in inputs.get("history") or []]
        verdict = await self._classifier.classify(inputs["question"], history)
        return {
            "off_topic": verdict.is_off_topic(self._threshold),
            "p_off_topic": verdict.p_off_topic,
            "model": verdict.model,
        }


def topic_check_target() -> TopicCheckTarget:
    """The committed model in backend/models/topic_check, at the configured threshold or its own."""
    classifier = OnnxSetFitTopicClassifier(TOPIC_MODEL)
    return TopicCheckTarget(classifier, topic_threshold(Settings().topic_check, classifier))
```

- [ ] **Step 5: Write the evaluators** `backend/evals/evaluators/topic_check.py`

```python
"""Topic check (PRD §10.1, spec 2026-10-13 §6.3, code): the classifier alone on the topic_check dataset's held-out
messages. `false_rejections` scores the on-topic examples (1 = declined, a miss); `off_topic_caught` scores the
off-topic ones (1 = declined). The suite is skipped until backend/models/topic_check holds a model. The `"key"` strings
are literals in the returned dicts: langsmith reads an evaluator's feedback keys from the source, not by running it."""

from typing import Any

from evals.suite import Suite, not_applicable
from evals.targets import TOPIC_MODEL, topic_check_target

FALSE_REJECTIONS = "topic_check.false_rejections"
OFF_TOPIC_CAUGHT = "topic_check.off_topic_caught"
FAILED = "the run failed before it classified"


def false_rejections(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if reference_outputs["off_topic"]:
        return not_applicable(FALSE_REJECTIONS, "an off-topic example: off_topic_caught scores it")
    if "off_topic" not in outputs:
        return {"key": "topic_check.false_rejections", "score": 1, "comment": FAILED}
    rejected = bool(outputs["off_topic"])
    comment = f"{'declined' if rejected else 'passed'} (p_off_topic {outputs['p_off_topic']:.3f})"
    return {"key": "topic_check.false_rejections", "score": int(rejected), "comment": comment}


def off_topic_caught(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not reference_outputs["off_topic"]:
        return not_applicable(OFF_TOPIC_CAUGHT, "an on-topic example: false_rejections scores it")
    if "off_topic" not in outputs:
        return {"key": "topic_check.off_topic_caught", "score": 0, "comment": FAILED}
    caught = bool(outputs["off_topic"])
    comment = f"{'declined' if caught else 'missed'} (p_off_topic {outputs['p_off_topic']:.3f})"
    return {"key": "topic_check.off_topic_caught", "score": int(caught), "comment": comment}


def _no_model() -> str | None:
    if (TOPIC_MODEL / "manifest.json").exists():
        return None
    return "no topic-check model in backend/models/topic_check yet (make topic-check-train)"


SUITE = Suite(
    dataset="topic_check",
    target=topic_check_target,
    evaluators=(false_rejections, off_topic_caught),
    skip=_no_model,
)
```

- [ ] **Step 6: Run tests**

Run: `cd backend && uv run pytest tests/unit/evals -q && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add backend/evals backend/tests/unit/evals
git commit -m "Add the topic_check eval suite" -m "False rejections and off-topic caught gate the classifier on held-out reviewed messages. Until a model is committed the suite is skipped, so publishing the dataset early can't break other runs." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: The training command

**Files:**
- Create: `backend/evals/topic_check/__init__.py`, `backend/evals/topic_check/data.py`, `backend/evals/topic_check/train.py`
- Modify: `backend/pyproject.toml` (extra `train`, CPU torch index), `backend/uv.lock`
- Modify: `Makefile` (`topic-check-train` target, `.PHONY`)
- Test: `backend/tests/unit/evals/test_topic_check_data.py`

**Interfaces:**
- Consumes:
  - `generated_examples` (publish);
  - `load_dataset`, `in_eval_share`, `normalized` (Task 8);
  - `topic_texts` (Task 1);
  - `OnnxSetFitTopicClassifier` (Task 5).
- Produces:
  - `Labeled(question, previous, off_topic)` with `.texts`;
  - `labeled(example) -> Labeled`;
  - `split_train_eval(rows, hand_written, share) -> (train, eval)`;
  - `holdout(rows, share, seed) -> (fit, held)`;
  - `training_rows(rows) -> (texts, labels)`;
  - `pick_threshold(scored, max_false_rejections=0.005) -> float`;
  - `rates(scored, threshold) -> (false_rejection_rate, caught_rate)`;
  - CLI `python -m evals.topic_check.train [--dry-run] [--base …] [--out …] [--epochs N] [--seed N]`.

- [ ] **Step 1: Write the failing tests** `backend/tests/unit/evals/test_topic_check_data.py`

```python
"""Training data for the topic-check model (spec 2026-10-13 §6.2): pure helpers, no torch."""

from evals.dataset import Example, in_eval_share
from evals.topic_check.data import (
    Labeled,
    holdout,
    labeled,
    pick_threshold,
    rates,
    split_train_eval,
    training_rows,
)


def test_an_example_becomes_a_labeled_message_with_its_previous_question() -> None:
    example = Example(
        {"question": "Why?", "history": [{"question": "What is X?", "answer": ""}]},
        {"off_topic": False, "kind": "follow_up"},
    )
    row = labeled(example)
    assert row == Labeled("Why?", "What is X?", False)
    assert row.texts == ["Why?", "Previous question: What is X?\nQuestion: Why?"]


def test_the_held_out_share_evaluates_and_hand_written_questions_never_train() -> None:
    rows = [Labeled(f"question {i}", None, i % 2 == 0) for i in range(200)] + [Labeled("Hand  WRITTEN", None, True)]
    train, evaluation = split_train_eval(rows, ["hand written"], 0.3)
    assert {r.question for r in evaluation} == {r.question for r in rows if in_eval_share(r.question, 0.3)}
    assert not {r.question for r in train} & {r.question for r in evaluation}
    assert "Hand  WRITTEN" not in {r.question for r in train}


def test_each_message_trains_alone_and_with_its_previous_question() -> None:
    texts, labels = training_rows([Labeled("Why?", "What is X?", False), Labeled("Joke!", None, True)])
    assert texts == ["Why?", "Previous question: What is X?\nQuestion: Why?", "Joke!"]
    assert labels == [0, 0, 1]


def test_holdout_is_seeded_and_disjoint() -> None:
    rows = [Labeled(f"q{i}", None, False) for i in range(100)]
    fit, held = holdout(rows, 0.15, seed=7)
    assert len(held) == 15 and len(fit) == 85 and not set(fit) & set(held)
    assert holdout(rows, 0.15, seed=7) == (fit, held)


def test_the_threshold_is_the_lowest_that_keeps_false_rejections_at_most_half_a_percent() -> None:
    on = [(0.1, False)] * 199 + [(0.62, False)]  # one on-topic message at 0.62 = 0.5% of 200
    off = [(0.9, True)] * 50
    assert pick_threshold(on + off) == 0.5  # 1/200 = 0.005 is allowed
    stricter = [(0.1, False)] * 99 + [(0.62, False)]  # 1/100 = 1% is not
    assert pick_threshold(stricter + off) == 0.63


def test_no_threshold_meeting_the_target_gives_0_99() -> None:
    assert pick_threshold([(0.995, False), (0.1, False)]) == 0.99


def test_rates_count_false_rejections_and_caught() -> None:
    scored = [(0.7, False), (0.2, False), (0.9, True), (0.4, True)]
    assert rates(scored, 0.5) == (0.5, 0.5)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/unit/evals/test_topic_check_data.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.topic_check'`

- [ ] **Step 3: Write the helpers.** `backend/evals/topic_check/__init__.py`:

```python
"""Training the topic-check model (spec 2026-10-13 §6.2)."""
```

`backend/evals/topic_check/data.py`:

```python
"""Training data for the topic-check model (spec 2026-10-13 §6.1–6.2): labeled messages, the train/eval split, and
threshold choice. Pure Python, so it is unit-tested without torch."""

import random
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from evals.dataset import Example, in_eval_share, normalized
from smart_tutor.tutoring.application import topic_texts

STEPS = [step / 100 for step in range(50, 100)]  # thresholds tried, lowest first


@dataclass(frozen=True)
class Labeled:
    question: str
    previous: str | None
    off_topic: bool

    @property
    def texts(self) -> list[str]:
        """What the classifier scores (the same texts as the agent's adapter)."""
        return topic_texts(self.question, self.previous)


def labeled(example: Example) -> Labeled:
    history = example.inputs.get("history") or []
    previous = str(history[-1]["question"]) if history else None
    return Labeled(str(example.inputs["question"]), previous, bool(example.outputs["off_topic"]))


def split_train_eval(
    rows: Iterable[Labeled], hand_written: Iterable[str], share: float
) -> tuple[list[Labeled], list[Labeled]]:
    """(train, eval): the held-out share evaluates; a hand-written question never trains."""
    hand = {normalized(q) for q in hand_written}
    train: list[Labeled] = []
    evaluation: list[Labeled] = []
    for row in rows:
        if in_eval_share(row.question, share):
            evaluation.append(row)
        elif normalized(row.question) not in hand:
            train.append(row)
    return train, evaluation


def holdout(rows: Sequence[Labeled], share: float, seed: int) -> tuple[list[Labeled], list[Labeled]]:
    """(fit, held): a seeded shuffle; `held` picks the threshold and checks the export."""
    shuffled = list(rows)
    random.Random(seed).shuffle(shuffled)
    cut = max(1, round(len(shuffled) * share))
    return shuffled[cut:], shuffled[:cut]


def training_rows(rows: Iterable[Labeled]) -> tuple[list[str], list[int]]:
    """Each message alone and with its previous question, labeled 1 when off-topic."""
    texts: list[str] = []
    labels: list[int] = []
    for row in rows:
        for text in row.texts:
            texts.append(text)
            labels.append(int(row.off_topic))
    return texts, labels


def rates(scored: Sequence[tuple[float, bool]], threshold: float) -> tuple[float, float]:
    """(false-rejection rate on on-topic messages, caught rate on off-topic messages) at `threshold`."""
    on = [p for p, off in scored if not off]
    off = [p for p, is_off in scored if is_off]
    rejected = sum(p >= threshold for p in on) / len(on) if on else 0.0
    caught = sum(p >= threshold for p in off) / len(off) if off else 0.0
    return rejected, caught


def pick_threshold(scored: Sequence[tuple[float, bool]], max_false_rejections: float = 0.005) -> float:
    """The lowest threshold (0.50 to 0.99 in steps of 0.01) whose false-rejection rate is at most
    `max_false_rejections`, leaving headroom under the 1% target; 0.99 when none is."""
    for threshold in STEPS:
        if rates(scored, threshold)[0] <= max_false_rejections + 1e-12:
            return threshold
    return STEPS[-1]
```

- [ ] **Step 4: Run the helper tests**

Run: `cd backend && uv run pytest tests/unit/evals/test_topic_check_data.py -v`
Expected: 7 passed.

- [ ] **Step 5: Add the `train` extra.** In `backend/pyproject.toml` `[project.optional-dependencies]`:

```toml
# Training the topic-check model only (evals.topic_check.train): never in an image or a CI install.
train = ["onnx>=1.17", "onnxscript>=0.2", "setfit>=1.1", "torch>=2.5"]
```

After `[build-system]`, add CPU-only torch, so training needs no CUDA download:

```toml
[tool.uv.sources]
torch = [{ index = "pytorch-cpu" }]

[[tool.uv.index]]
name = "pytorch-cpu"
url = "https://download.pytorch.org/whl/cpu"
explicit = true
```

Run: `cd backend && uv lock && uv sync`
Expected: the lock resolves. The default sync does not install the extra, so `uv run python -c "import setfit"` fails with `ModuleNotFoundError`; `uv run --extra train python -c "import setfit, torch"` exits 0.

- [ ] **Step 6: Write the command** `backend/evals/topic_check/train.py`

```python
"""Train the topic-check model (spec 2026-10-13 §6.2) into backend/models/topic_check.

Usage: uv run --env-file ../.env --extra eval --extra train python -m evals.topic_check.train [--dry-run]
    [--base BAAI/bge-small-en-v1.5] [--epochs 1] [--seed 42] [--out ../models/topic_check]

1. Reads the accepted topic_check candidates (the review queue and the newest full version; publishing isn't needed)
   and keeps the training share; the held-out share and the hand-written examples evaluate.
2. Holds out 15% of the training share, trains SetFit on the rest, and picks the threshold on the held-out slice
   (false rejections ≤ 0.5%).
3. Exports the body to ONNX (dynamic shapes), quantizes it to int8, and writes tokenizer.json, head.npz, and
   manifest.json.
4. Checks the exported model against SetFit on the held-out slice (within 0.02) and reports false rejections and
   off-topic caught on the eval share. Exits 1 if the export drifts or the targets (≤ 1%, ≥ 95%) are missed.

--dry-run prints how many on- and off-topic messages each share holds and trains nothing.
"""

import argparse
import json
import sys
import tempfile
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import langsmith
import numpy as np
from langsmith.utils import LangSmithError

from evals.dataset import load_dataset
from evals.publish import generated_examples
from evals.topic_check.data import Labeled, holdout, labeled, pick_threshold, rates, split_train_eval, training_rows
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier

OUT = Path(__file__).parents[2] / "models" / "topic_check"
HOLDOUT_SHARE = 0.15
MIN_TRAIN = 40  # per label
MAX_DRIFT = 0.02
TARGET_FALSE_REJECTIONS, TARGET_CAUGHT = 0.01, 0.95


def _counts(name: str, rows: Sequence[Labeled]) -> str:
    on = sum(not r.off_topic for r in rows)
    return f"{name}: {on} on-topic, {len(rows) - on} off-topic"


def _train(rows: Sequence[Labeled], base: str, epochs: int, seed: int) -> Any:
    from datasets import Dataset as HfDataset
    from setfit import SetFitModel, Trainer, TrainingArguments

    texts, labels = training_rows(rows)
    model = SetFitModel.from_pretrained(base)
    args = TrainingArguments(num_epochs=epochs, batch_size=16, seed=seed)
    Trainer(model=model, args=args, train_dataset=HfDataset.from_dict({"text": texts, "label": labels})).train()
    if list(model.model_head.classes_) != [0, 1]:
        raise ValueError(f"expected a binary head with classes [0, 1], not {list(model.model_head.classes_)}")
    return model


def _setfit_score(model: Any, row: Labeled) -> float:
    return float(min(model.predict_proba(row.texts, as_numpy=True)[:, 1]))


def _pooling(body: Any) -> str:
    config = body[1].get_config_dict()
    pooling = config.get("pooling_mode") or (
        "cls" if config.get("pooling_mode_cls_token") else "mean" if config.get("pooling_mode_mean_tokens") else None
    )
    if pooling not in ("cls", "mean"):
        raise ValueError(f"the topic check supports cls or mean pooling, not {config}")
    return str(pooling)


def _export(model: Any, out: Path, manifest: dict[str, Any]) -> None:
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic

    body = model.model_body
    transformer, tokenizer = body[0].auto_model, body.tokenizer
    sample = tokenizer(["a sample question"], return_tensors="pt")
    names = [n for n in ("input_ids", "attention_mask", "token_type_ids") if n in sample]

    class Body(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.transformer = transformer

        def forward(self, *inputs: Any) -> Any:
            return self.transformer(**dict(zip(names, inputs, strict=True))).last_hidden_state

    transformer.eval()
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        fp32 = Path(tmp) / "body.fp32.onnx"
        torch.onnx.export(
            Body(),
            tuple(sample[n] for n in names),
            str(fp32),
            input_names=names,
            output_names=["last_hidden_state"],
            dynamic_axes={n: {0: "batch", 1: "tokens"} for n in [*names, "last_hidden_state"]},
            opset_version=17,
            dynamo=False,
        )
        quantize_dynamic(str(fp32), str(out / "body.onnx"), weight_type=QuantType.QInt8)
    tokenizer.backend_tokenizer.save(str(out / "tokenizer.json"))
    np.savez(out / "head.npz", coef=model.model_head.coef_, intercept=model.model_head.intercept_)
    full = {
        **manifest,
        "pooling": _pooling(body),
        "normalize": any(type(m).__name__ == "Normalize" for m in body),
        "max_tokens": int(body.max_seq_length),
    }
    (out / "manifest.json").write_text(json.dumps(full, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None, *, client: Any = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="print the shares' sizes; train nothing")
    parser.add_argument("--base", default="BAAI/bge-small-en-v1.5", help="the sentence-transformer body")
    parser.add_argument("--epochs", type=int, default=1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    dataset = load_dataset("topic_check")
    assert dataset.eval_share is not None, "topic_check.yaml must set eval_share"
    try:
        accepted = [labeled(e) for e in generated_examples(client or langsmith.Client(), dataset)]
    except LangSmithError as e:
        print(f"Can't reach LangSmith: {e} (check LANGSMITH_API_KEY)", file=sys.stderr)
        return 1
    hand = [str(e.inputs["question"]) for e in dataset.examples]
    train, evaluation = split_train_eval(accepted, hand, dataset.eval_share)
    evaluation += [labeled(e) for e in dataset.examples]
    print(_counts("train", train))
    print(_counts("eval", evaluation))
    if args.dry_run:
        return 0
    if min(sum(r.off_topic for r in train), sum(not r.off_topic for r in train)) < MIN_TRAIN:
        print(f"Too few accepted messages to train: at least {MIN_TRAIN} of each label.", file=sys.stderr)
        return 1
    fit, held = holdout(train, HOLDOUT_SHARE, args.seed)
    model = _train(fit, args.base, args.epochs, args.seed)
    held_scores = [(_setfit_score(model, r), r.off_topic) for r in held]
    threshold = pick_threshold(held_scores)
    now = datetime.now(UTC)
    manifest = {
        "version": f"setfit-{args.base.rsplit('/', 1)[-1]}-int8@{now:%Y-%m-%d}",
        "base_model": args.base,
        "threshold": threshold,
        "trained_on": {"dataset": dataset.name, "messages": len(fit), "held_out": len(held)},
        "created_at": now.isoformat(timespec="seconds"),
    }
    _export(model, args.out, manifest)
    exported = OnnxSetFitTopicClassifier(args.out)
    drift = max(abs(min(exported.p_off_topic(r.texts)) - p) for r, (p, _) in zip(held, held_scores, strict=True))
    rejected, caught = rates([(min(exported.p_off_topic(r.texts)), r.off_topic) for r in evaluation], threshold)
    print(f"{manifest['version']}: threshold {threshold:.2f}, export drift {drift:.4f}")
    print(f"eval share: false rejections {rejected:.2%} (≤ 1%), off-topic caught {caught:.2%} (≥ 95%)")
    if drift > MAX_DRIFT:
        print(f"The int8 export drifts {drift:.3f} from SetFit (> {MAX_DRIFT}).", file=sys.stderr)
        return 1
    if rejected > TARGET_FALSE_REJECTIONS or caught < TARGET_CAUGHT:
        print("The model misses the topic_check targets: review more data or try another --base.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 7: Add the Makefile target.** In `Makefile`, add `topic-check-train` to `.PHONY`. After `evals-publish`:

```make
topic-check-train: ## train the topic-check model from accepted topic_check candidates into backend/models/topic_check (LANGSMITH_API_KEY; --dry-run counts them)
	$(HOST) --extra eval --extra train python -m evals.topic_check.train
```

- [ ] **Step 8: Smoke-check the CLI without data**

Run: `cd backend && uv run python -m evals.topic_check.train --help`
Expected: the usage text prints; no torch is needed to show it.

- [ ] **Step 9: Run the checks**

Run: `cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add backend/evals/topic_check backend/pyproject.toml backend/uv.lock Makefile backend/tests/unit/evals/test_topic_check_data.py
git commit -m "Add the topic-check training command" -m "One command turns reviewed messages into the int8 ONNX model the agent loads, picks its threshold for at most 0.5% false rejections, and refuses a model whose export drifts or that misses the eval targets." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: PRD, ADR 0018, CONTEXT, and READMEs

**Files:**
- Modify: `sdd/prd.md`
- Create: `sdd/adr/0018-off-topic-questions-local-setfit-classifier.md`
- Modify: `CONTEXT.md`, `backend/src/smart_tutor/tutoring/README.md`, `backend/evals/README.md`

- [ ] **Step 1: Bump the PRD and log the change.** In `sdd/prd.md`:
  - **Status line:** change `Draft v2.58` to `Draft v2.59`.
  - **Change row:** insert this row directly above the `| **Changes from v2.57** |` row:

```markdown
| **Changes from v2.58** | Off-topic questions (spec 2026-10-13, ADR 0018; D5, US-5, §9.2, §9.6, §10.1, glossary): a topic check runs before search. A local SetFit classifier (ONNX, in the agent) scores the question alone and with the previous question; at or above its tuned threshold the tutor declines with `off_topic` and one polite message, with no search, no model call, and no action. On an error, a timeout (250 ms), or with the check off, the question goes on to search. The check is off until a model passes the `topic_check` eval (≤ 1% of study questions declined, ≥ 95% of off-topic questions declined). Replacing SetFit with another decision model (e.g. Jev) is a configuration change after a privacy decision. |
```

- [ ] **Step 2: Replace D5** (line ~157) with:

```markdown
| D5 | **A topic check runs first** (a fixed graph step with a local classifier; spec 2026-10-13, ADR 0018): an off-topic question gets the off-topic decline without a search or a model call. **Every other question searches first**, and uncovered questions get the US-5 decline. | Off-topic questions cost no search and always get the same polite answer; retrieval stays a fixed step, never a model decision. |
```

- [ ] **Step 3: Add the glossary rows** after the `| **Decline log** |` row:

```markdown
| **Off-topic question** | A message that isn't about studying, understanding, or researching something: greetings and questions about the tutor itself, entertainment, personal tasks, live information. Declined before search (D5). |
| **Topic check** | The first step of every ask: a local classifier's P(off-topic) for the question, alone and with the previous question, against a tuned threshold; it fails open (§9.2 step 0). |
```

- [ ] **Step 4: Add the US-5 criterion.** After the line `- Each decline is written to the decline log (§9.6).` under **US-5**:

```markdown
- *When* a question is off-topic (greetings, questions about the tutor, entertainment, personal tasks, live information), *then* the tutor declines it before searching, with one polite message ("I'm Smart Tutor: I help you study and research the papers, books, magazines, and news articles in your library, so I can't help with that. Ask me about your documents or a topic you're learning.") and no action. The turn is kept, adds nothing to Documents used, and can be rated (D5, §9.2 step 0).
```

- [ ] **Step 5: Add §9.2 step 0.** Directly before `1. **Search (fixed step).**`:

```markdown
0. **Topic check (code, before search).** A SetFit classifier in the agent (ONNX on CPU; spec 2026-10-13, ADR 0018) scores the question alone and, in an existing conversation, with the previous question; the verdict is the lower score. At or above its threshold (tuned with the model; configuration may override it) the tutor declines with `off_topic` (US-5) and nothing else runs. An error, a timeout (`timeout_ms`, 250), or the check being off (`SMART_TUTOR_TOPIC_CHECK__PROVIDER=off`, the default until a model passes the `topic_check` eval) lets the question go on to step 1.
```

- [ ] **Step 6: Update §9.6 and §10.1**
  - **§9.6:** change `Every decline (relevance gate or `decline` tool)` to `Every decline (relevance gate, `decline` tool, or topic check, reason `off_topic`)`.
  - **§10.1:** after the `| **Decline correctness** |` row, add:

```markdown
| **Topic check** | Code (labeled) | Study questions wrongly declined as off-topic / off-topic questions declined, on the `topic_check` dataset's held-out share (spec 2026-10-13 §6). | ≤ 1% / ≥ 95% |
```

- [ ] **Step 7: Write the ADR** `sdd/adr/0018-off-topic-questions-local-setfit-classifier.md`

```markdown
# 0018. Off-topic questions are screened by a local SetFit classifier behind a swappable port

- Status: accepted
- Date: 2026-10-13
- Supersedes: PRD D5's "Search always runs first … off-topic and uncovered questions get the same friendly decline"

## Context

Every question searched all of the learner's documents first (D5), so "tell me a joke" ran a search and the answer
model improvised over unrelated chunks. The product owner wants Smart Tutor to cover education and research only and
to decline off-topic questions politely without searching, with an open-source decision model "like Jev", and the
option to switch to TypeSafe's Jev later. The default on-premise host is one t3.large (2 vCPU, 8 GB, no GPU), and the
agent container is capped at 512 MiB (ADR 0012).

## Decision

- A `topic_check` graph step runs before `search` and is a fixed step, not a model's choice. Off-topic means the
  classifier's P(off-topic) is at or above a threshold tuned with the model. The verdict is the lower of the question
  alone and the question with the previous question.
- The check sits behind a `TopicClassifier` port in `tutoring`. Its first adapter runs a **SetFit** model
  (sentence-transformer body plus logistic head) trained on our own reviewed messages, exported to **int8 ONNX** and run
  with onnxruntime, `tokenizers`, and numpy in the agent process. There is no torch in any image, and only the agent
  image gets the `topic` extra.
- It **fails open**: an error, a timeout (250 ms), or the check being off lets the question go on to search.
- The model is committed to git in `backend/models/topic_check/` (about 30 MB) and copied into the agent image.
- The check stays off until the `topic_check` eval passes: at most 1% of study questions declined and at least 95% of
  off-topic ones declined.

## Alternatives rejected (research note `sdd/reviews/2026-10-13-off-topic-model-research.md`)

- **Jev itself:** hosted and closed, so learners' question text would leave our infrastructure.
- **GovTech's off-topic classifier as shipped:** its export pads to 1,024 tokens (about 2.4 s per question on 2 CPU
  threads), and zero-shot it declined real study questions for our broad scope.
- **NemoGuard-TopicControl, Llama Guard, Qwen3Guard, ShieldGemma, Granite Guardian:** need a GPU or can't express a
  custom scope.
- **An LLM call (Nova Micro):** works, but costs a model call per turn; it remains the eval baseline.
- **Bedrock Guardrails denied topics:** a blocklist can't express "only education and research".

## Consequences

- Swapping in another decision model (Jev) means a new adapter, a provider value, and its key in Secrets Manager.
  Because Jev would send question text to a third party, it needs a PRD privacy decision before it is enabled.
- Data upkeep: the model learns the boundary from human-reviewed messages, and each retrain adds about 30 MB to git
  history. Revisit storage after about five versions.
- One more step per turn: about 5–10 ms on CPU in the spike, to be measured on the host before enabling.
```

- [ ] **Step 8: Update `CONTEXT.md`.** Replace the **Decline** entry's definition with `The tutor's refusal to answer a question the learner's documents do not support, or an off-topic question.` After the **Decline log** entry, add:

```markdown
**Off-topic question**:
A message that isn't about studying, understanding, or researching something: greetings, questions about the tutor, entertainment, personal tasks, live information.
_Avoid_: Irrelevant question, spam

**Topic check**:
The first step of every ask: a local classifier decides whether the question is off-topic; it fails open.
_Avoid_: Guardrail, filter
```

- [ ] **Step 9: Update the READMEs**
  - **`backend/src/smart_tutor/tutoring/README.md`:**
    - In **Key classes**, add the port `TopicClassifier` to the ports list.
    - In **Built so far**, append: `The topic check (spec 2026-10-13): the TopicClassifier port (P(off-topic) of a question given its history), TopicVerdict, topic_texts (the question alone and with the previous question, shared with training), OFF_TOPIC_DECLINE, and the OnnxSetFitTopicClassifier adapter (int8 ONNX on onnxruntime; only the agent image installs its topic extra).`
  - **`backend/evals/README.md`:** add a section `## Topic check` after `## Injection eval`:

```markdown
## Topic check

`datasets/topic_check.yaml` labels learner messages on-topic or off-topic (spec 2026-10-13 §3).

1. `make evals-generate DATASET=topic_check` has the judge write messages of each kind (`generators/topic_check.py`)
   into the `smart-tutor-topic-check-candidates` queue. Review them as for `ask`.
2. Accepted messages are split by a stable hash of the question: `eval_share` (30%) of them are published as the
   dataset (`make evals-publish`), and the rest train the model.
3. `make topic-check-train` (or `python -m evals.topic_check.train --dry-run` to count) trains SetFit, picks the
   threshold, writes `backend/models/topic_check/`, and reports the eval share's false rejections and off-topic caught.
4. The `topic_check` suite (classifier only, no Bedrock) gates `topic_check.false_rejections` ≤ 0.01 and
   `topic_check.off_topic_caught` ≥ 0.95. It is skipped until the model is committed.
```

- [ ] **Step 10: Commit**

```bash
git add sdd/prd.md sdd/adr/0018-off-topic-questions-local-setfit-classifier.md CONTEXT.md backend/src/smart_tutor/tutoring/README.md backend/evals/README.md
git commit -m "Record the topic check in the PRD and ADR 0018" -m "D5 changes from 'search always runs first' to 'a topic check runs first', so the product spec, the decision record, and the glossary say what the code now does (PRD v2.59)." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

**PR 1:** run the full checks (Global Constraints) and `helm lint deploy/helm/smart-tutor` (nothing changed there yet). Open the PR into `main`. Its description says the check ships **off**, links the spec, research note and ADR, and notes that the mockup has no off-topic state (the generic decline card is used).

---

## PR 2: data, model, and turning it on

### Task 13: Generate and review the labeled messages (human in the loop)

This task needs people to review data in LangSmith. An agent runs the commands and reports progress, but cannot accept candidates itself.

- [ ] **Step 1: Generate the first round.**
  Run: `cd backend && uv run --env-file ../.env --extra eval --extra ingest python -m evals.generate topic_check --per-type 60`
  Expected: `Queued ~480 candidates … in the smart-tutor-topic-check-candidates annotation queue`.
- [ ] **Step 2: A reviewer accepts or rejects each message** in that queue, using its rubric (spec §3), with particular care for the borderline kinds `study_task` and `personal_task`.
- [ ] **Step 3: Count.**
  Run: `cd backend && uv run --env-file ../.env --extra eval --extra train python -m evals.topic_check.train --dry-run`
  Repeat Steps 1–3 until `eval:` shows at least **300 on-topic and 200 off-topic** messages. At a 30% share, that is about 1,000 on-topic and 670 off-topic accepted messages in all, so plan several review rounds.
- [ ] **Step 4: Report the counts** and the reviewer's hours in PR 2's description.

### Task 14: Train, verify, commit the model, and turn the check on

**Files:**
- Create: `backend/models/topic_check/{body.onnx,tokenizer.json,head.npz,manifest.json}`
- Modify: `backend/evals/thresholds.yaml`, `backend/evals/datasets/ask.yaml`, `.env.example`, `deploy/on-premise/compose.yaml`, `deploy/helm/smart-tutor/charts/agent/values.yaml`, `deploy/helm/smart-tutor/charts/agent/templates/deployment.yaml`

- [ ] **Step 1: Train.**
  Run: `make topic-check-train` (or `cd backend && uv run --env-file ../.env --extra eval --extra train python -m evals.topic_check.train`)
  Expected: exit 0, export drift ≤ 0.02, eval-share false rejections ≤ 1% and off-topic caught ≥ 95%. If it misses:
  - try `--base sentence-transformers/all-MiniLM-L6-v2` or `--epochs 2`;
  - otherwise review more data (Task 13).
  - Don't lower the targets.
- [ ] **Step 2: Check the new model's eval suite locally.**
  Run: `cd backend && uv run pytest tests/unit/evals/test_topic_check_suite.py -v`
  Expected: pass. The suite's `skip` now returns `None`.
- [ ] **Step 3: Add the gate.** In `backend/evals/thresholds.yaml` under `release_1`, after `decline_correctness`:

```yaml
  topic_check:            # spec 2026-10-13 §6.3; classifier only, on the held-out share
    false_rejections:     {type: code,  max: 0.01}
    off_topic_caught:     {type: code,  min: 0.95}
```

- [ ] **Step 4: Add end-to-end off-topic examples** to `backend/evals/datasets/ask.yaml`, after the "Not covered" block:

```yaml
  # Off-topic (spec 2026-10-13): declined by the topic check before search, limited or not.
  - inputs: {question: "Tell me a joke about cats.", learner: learner@example.com, documents: null}
    outputs: {covered: false, sources: [], off_topic: true}
  - inputs: {question: "What's the weather in Hanoi tomorrow?", learner: learner@example.com, documents: [react-2022]}
    outputs: {covered: false, sources: [], off_topic: true}
```

- [ ] **Step 5: Turn the check on everywhere.**
  - **`.env.example`:** uncomment to `SMART_TUTOR_TOPIC_CHECK__PROVIDER=setfit`.
  - **`deploy/on-premise/compose.yaml`:** under the `agent` service's `environment`, after `SMART_TUTOR_MCP_URL`, add `SMART_TUTOR_TOPIC_CHECK__PROVIDER: setfit`.
  - **`deploy/helm/smart-tutor/charts/agent/values.yaml`:** add:

```yaml
# The topic check before search (spec 2026-10-13): setfit runs the model baked into the image; off skips it.
topicCheck:
  provider: setfit
```

  - **`deploy/helm/smart-tutor/charts/agent/templates/deployment.yaml`:** after the `SMART_TUTOR_MCP_URL` env entry, add:

```yaml
            - name: SMART_TUTOR_TOPIC_CHECK__PROVIDER
              value: {{ .Values.topicCheck.provider | quote }}
```

- [ ] **Step 6: Measure on the on-premise host before merging.** With the PR's agent image running on the host:

```bash
docker compose exec agent python -c "
import asyncio, statistics, time
from pathlib import Path
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier
from smart_tutor.tutoring.application import HistoryTurn
c = OnnxSetFitTopicClassifier(Path('/app/models/topic_check'))
qs = ['Explain photosynthesis in simple terms.', 'Tell me a joke about cats.', 'Why does it need to be fed every day?'] * 70
async def run():
    ts = []
    for q in qs:
        t = time.perf_counter(); await c.classify(q, [HistoryTurn('How does the cookbook make sourdough starter?', '')]); ts.append((time.perf_counter() - t) * 1000)
    ts.sort(); print(f'p50 {statistics.median(ts):.1f} ms, p95 {ts[int(len(ts) * 0.95)]:.1f} ms')
asyncio.run(run())
"
docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' | grep agent
```

  Expected: p95 ≤ 300 ms and agent memory below about 450 MiB. If memory is above about 450 MiB:
  - raise `mem_limit` to `768m` in `deploy/on-premise/compose.yaml`;
  - raise `resources.limits.memory` to `768Mi` in the Helm agent values;
  - do both in this PR.

  Record the numbers in the PR description.
- [ ] **Step 7: Run all checks.**
  Run the backend checks (Global Constraints) and `helm lint deploy/helm/smart-tutor`. Run `cd infra && uv run pytest` if any infra test reads the compose file.
- [ ] **Step 8: Commit and open PR 2**

```bash
git add backend/models/topic_check backend/evals/thresholds.yaml backend/evals/datasets/ask.yaml .env.example deploy
git commit -m "Ship the topic-check model and turn the check on" -m "The model meets the topic_check targets on the held-out reviewed messages (numbers in the PR), so off-topic questions are now declined before search in every environment." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 9: After PR 2 merges**, publish the datasets so CI gates on them:
  Run: `make evals-publish` (or `cd backend && uv run --env-file ../.env --extra eval python -m evals.publish --dataset topic_check --dataset ask`)
  Then run `make evals-smoke`. Expected: `topic_check.*` and `decline_correctness.*` pass.

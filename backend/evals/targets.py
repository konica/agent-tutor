"""How an evaluation run invokes the agent (PRD §10): one example in; the answer, citations, decline code, and
trajectory out.
The outputs also name the learner's own documents (`library`) for the injection checks.

The ask target runs the ask graph the way the agent server does (apps/agent/server.py): retrieval through the MCP
server, the eval learner's token in runtime context only (ADR 0007). A recording retriever keeps each MCP `search` call
as the trajectory. Examples name seed documents (manifest ids); the learner's own copies are found by SHA-256.

An example's `history` holds its earlier turns, oldest first: a question alone is asked through the graph and its answer
kept (a generated or hand-written conversation); a question with its answer is kept as written (an injection attack
that spans turns). Each ask gets the turns before it capped like the API caps them (`history_turns`,
`history_answer_chars`); only the last ask is scored.

The description target reads the worker's stored description of a document (title, summary, subject suggestions) through
the API as its owner (#196).
"""

import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

import httpx
from langchain_core.language_models import BaseChatModel

from evals.corpus import SeedDocument, load_manifest
from evals.learners import LEARNERS, LoadError, Tutor, load_learners
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.guards import build_guard
from smart_tutor.apps.agent.state import DECLINE_MESSAGES, AgentContext
from smart_tutor.apps.agent.topic import topic_classifier, topic_threshold
from smart_tutor.shared.adapters.aws.clients import bedrock_runtime_client
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.shared.ports.counter import NoCounter
from smart_tutor.tutoring.adapters.bedrock_question_screen import SCREEN_BOTO_CONFIG, BedrockQuestionScreen, Screening
from smart_tutor.tutoring.adapters.guardrails_guard import GuardrailsGuard
from smart_tutor.tutoring.adapters.mcp_retriever import McpRetriever
from smart_tutor.tutoring.adapters.onnx_topic_classifier import OnnxSetFitTopicClassifier
from smart_tutor.tutoring.application import (
    Guard,
    HistoryTurn,
    RetrievedChunk,
    Retriever,
    TopicClassifier,
    history_turn,
    new_canary,
    system_prompt,
)

Target = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class RecordingRetriever(Retriever):
    """Searches through `inner` and appends each call, with the documents it found, to `calls`."""

    def __init__(self, inner: Retriever, calls: list[dict[str, Any]]) -> None:
        self._inner, self._calls = inner, calls

    async def search(self, query: str, k: int = 5, document_ids: Sequence[str] | None = None) -> list[RetrievedChunk]:
        chunks = await self._inner.search(query, k, document_ids)
        self._calls.append(
            {
                "tool": "search",
                "query": query,
                "k": k,
                "document_ids": None if document_ids is None else list(document_ids),
                "found": [c.document_id for c in chunks],
            }
        )
        return chunks


class Learners(Protocol):
    def token(self, username: str) -> str: ...
    def sign_in_again(self, username: str) -> str: ...
    def document_id(self, username: str, seed_id: str) -> str: ...
    def library(self, username: str) -> list[str]: ...


class EvalLearners:
    """The eval learners' sessions, signed in on first use, and their own copies of the seed documents."""

    def __init__(self, tutors: Mapping[str, Tutor], seeds: Mapping[str, SeedDocument]) -> None:
        self._tutors, self._seeds = dict(tutors), seeds
        self._ids: dict[tuple[str, str], str] = {}
        self._libraries: dict[str, list[str]] = {}

    def _tutor(self, username: str) -> Tutor:
        if username not in self._tutors:
            raise ValueError(f"{username} is not an eval learner (seed_corpus/learners.yaml)")
        return self._tutors[username]

    def token(self, username: str) -> str:
        return self._tutor(username).access_token()

    def sign_in_again(self, username: str) -> str:
        tutor = self._tutor(username)
        tutor.sign_in()
        return tutor.access_token()

    def document_id(self, username: str, seed_id: str) -> str:
        key = (username, seed_id)
        if key not in self._ids:
            check = {"sha256": self._seeds[seed_id].sha256}
            found = self._tutor(username).call("POST", "/documents/duplicate-check", check)["document_id"]
            if not found:
                raise LoadError(f"{username} doesn't hold {seed_id}: load the eval learners (make evals-learners)")
            self._ids[key] = str(found)
        return self._ids[key]

    def library(self, username: str) -> list[str]:
        """The documents the learner can read now: their ready, non-archived documents (GET /documents). Read once
        per learner and run; it includes documents the learner uploaded beyond the seed corpus."""
        if username not in self._libraries:
            listed = self._tutor(username).call("GET", "/documents?state=ready")
            self._libraries[username] = [str(d["document_id"]) for d in listed]
        return list(self._libraries[username])

    def get(self, username: str, path: str) -> Any:
        """A GET through the learner's own session."""
        return self._tutor(username).call("GET", path)

    def check_libraries(self, holdings: Mapping[str, Sequence[str]]) -> None:
        """Raise LoadError unless each learner holds all of their seed documents. Done before the run: inside the
        target, LangSmith would only log the error and the run would go on to a misleading gate table."""
        for username, seed_ids in holdings.items():
            for seed_id in seed_ids:
                self.document_id(username, seed_id)


class AskTarget:
    def __init__(
        self,
        learners: Learners,
        retriever_for: Callable[[str], Retriever],
        model: BaseChatModel,
        answer_floor: float,
        answer_max_tokens: int = 1500,
        history_turns: int = 5,
        history_answer_chars: int = 2000,
        prompt: str | None = None,
        guard: Guard | None = None,
        topic_classifier: TopicClassifier | None = None,
        topic_threshold: float = 1.0,
        topic_timeout_ms: int = 250,
    ) -> None:
        self._learners, self._retriever_for = learners, retriever_for
        self._model, self._answer_floor, self._answer_max_tokens = model, answer_floor, answer_max_tokens
        self._history_turns, self._history_answer_chars = history_turns, history_answer_chars
        self._topic = (topic_classifier, topic_threshold, topic_timeout_ms)
        canary = new_canary()  # one per target, as the agent makes one per process
        self._prompt = prompt or system_prompt(canary)
        self._guard = guard or GuardrailsGuard(self._prompt, canary)

    async def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        username, seeds = inputs["learner"], inputs.get("documents")
        limit = None if seeds is None else [self._learners.document_id(username, s) for s in seeds]
        earlier = inputs.get("history") or []
        try:
            out = await self._conversation(earlier, inputs["question"], limit, self._learners.token(username))
        except UnauthenticatedError:  # the token expired during the run: sign in once more, replay it all
            token = self._learners.sign_in_again(username)
            out = await self._conversation(earlier, inputs["question"], limit, token)
        return {**out, "library": self._learners.library(username)}

    async def _conversation(
        self, earlier: Sequence[str | Mapping[str, str]], question: str, limit: list[str] | None, token: str
    ) -> dict[str, Any]:
        turns: list[HistoryTurn] = []
        for past in earlier:
            if isinstance(past, Mapping):  # a turn as written: its answer is not the agent's
                turns.append(history_turn(past["question"], past["answer"], self._history_answer_chars))
                continue
            state = await self._ask(past, limit, turns, token, [])
            if state.get("decline") != "guard":  # a tripped turn is never history, as in the API
                turns.append(history_turn(past, self._answer(state), self._history_answer_chars))
        calls: list[dict[str, Any]] = []
        state = await self._ask(question, limit, turns, token, calls)
        return {
            "answer": self._answer(state),
            "citations": [
                {
                    "n": c.n,
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "document_title": c.document_title,
                    "page": c.page,
                }
                for c in state.get("citations", [])
            ],
            "decline": state.get("decline"),
            "limit": limit,
            "trajectory": calls,
            "history": [{"question": t.question, "answer": t.answer} for t in self._capped(turns)],
            "chunks": [
                {
                    "chunk_id": c.chunk_id,
                    "document_id": c.document_id,
                    "document_title": c.document_title,
                    "page": c.page,
                    "score": c.score,
                    "text": c.text,
                }
                for c in state.get("chunks", [])
            ],
        }

    async def _ask(
        self,
        question: str,
        limit: list[str] | None,
        turns: Sequence[HistoryTurn],
        token: str,
        calls: list[dict[str, Any]],
    ) -> dict[str, Any]:
        classifier, threshold, timeout_ms = self._topic
        graph = build_graph(
            lambda t: RecordingRetriever(self._retriever_for(t), calls),
            self._model,
            self._answer_floor,
            self._answer_max_tokens,
            guard=self._guard,
            system_prompt=self._prompt,
            topic_classifier=classifier,
            topic_threshold=threshold,
            topic_timeout_ms=timeout_ms,
        )
        return await graph.ainvoke(
            {"question": question, "document_ids": limit, "history": self._capped(turns)},
            context=AgentContext(access_token=token),
        )

    def _capped(self, turns: Sequence[HistoryTurn]) -> list[HistoryTurn]:
        return list(turns[-self._history_turns :]) if self._history_turns else []

    @staticmethod
    def _answer(state: Mapping[str, Any]) -> str:
        decline = state.get("decline")
        return DECLINE_MESSAGES[decline] if decline else state.get("answer", "")


def ask_target() -> AskTarget:
    """The ask target against the local stack: the agent model, the MCP server, Keycloak, and the API."""
    settings, seeds = Settings(), load_manifest()
    learners = load_learners(LEARNERS, seeds)
    tutors = {  # each learner in their own client: Keycloak's session cookie must not carry over
        learner.username: Tutor(httpx.Client(timeout=60), learner.username, learner.password) for learner in learners
    }
    eval_learners = EvalLearners(tutors, seeds)
    eval_learners.check_libraries({learner.username: learner.documents for learner in learners})
    canary = new_canary()
    prompt = system_prompt(canary)
    classifier = topic_classifier(settings.topic_check)  # off until .env turns it on
    return AskTarget(
        eval_learners,
        lambda token: McpRetriever(settings.mcp_url, token),
        ModelFactory(settings).chat(ChatRole.AGENT),
        settings.answer_floor,
        settings.answer_max_tokens,
        settings.history_turns,
        settings.history_answer_chars,
        prompt,
        build_guard(settings, prompt, canary, failures=NoCounter()),  # screened when the question screen is on
        topic_classifier=classifier,
        topic_threshold=topic_threshold(settings.topic_check, classifier),
        topic_timeout_ms=settings.topic_check.timeout_ms,
    )


class Readers(Protocol):
    def document_id(self, username: str, seed_id: str) -> str: ...
    def get(self, username: str, path: str) -> Any: ...


class DescriptionTarget:
    """The description the worker stored for a seed document (#196), read as the learner who owns it."""

    def __init__(self, learners: Readers) -> None:
        self._learners = learners

    async def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        username = inputs["learner"]
        document_id = self._learners.document_id(username, inputs["document"])
        details = self._learners.get(username, f"/documents/{document_id}")
        found = self._learners.get(username, f"/documents/{document_id}/subject-suggestions")
        return {
            "document_id": document_id,
            "title": details.get("title"),
            "extracted_title": details.get("extracted_title"),
            "summary": details.get("summary"),
            "suggestions": [s["name"] for s in found["suggestions"]],
        }


def description_target() -> DescriptionTarget:
    """The stored descriptions of the eval learners' documents, read through the local stack's API."""
    seeds = load_manifest()
    learners = load_learners(LEARNERS, seeds)
    tutors = {
        learner.username: Tutor(httpx.Client(timeout=60), learner.username, learner.password) for learner in learners
    }
    readers = EvalLearners(tutors, seeds)
    readers.check_libraries({learner.username: learner.documents for learner in learners})
    return DescriptionTarget(readers)


class Screen(Protocol):
    async def screen(self, question: str) -> Screening: ...


class QuestionScreenTarget:
    """The question screen alone (#199): one ApplyGuardrail call on the question. `screen` is None when no guardrail
    is configured; the run then reports `screened: False`, which the metrics leave out."""

    def __init__(self, screen: Screen | None) -> None:
        self._screen = screen

    async def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        if self._screen is None:
            return {"screened": False}
        started = time.perf_counter()
        found = await self._screen.screen(inputs["question"])
        return {
            "screened": True,
            "tripped": found.tripped,
            "latency_ms": (time.perf_counter() - started) * 1000,
            "processing_ms": found.processing_ms,
            "text_units": found.text_units,
        }


class _PassThrough(Guard):
    """The screen's inner guard: unused, because the target only calls `screen`."""

    async def check_question(self, question: str) -> None:
        return None

    async def check_answer(self, text: str) -> None:
        return None


def question_screen_target() -> QuestionScreenTarget:
    """The question screen against the configured guardrail (`question_guardrail_id` and `_version`), whether or not
    `question_guard` is on: the eval measures a guardrail before it is turned on."""
    settings = Settings()
    if not (settings.question_guardrail_id and settings.question_guardrail_version):
        return QuestionScreenTarget(None)
    return QuestionScreenTarget(
        BedrockQuestionScreen(
            _PassThrough(),
            bedrock_runtime_client(settings, SCREEN_BOTO_CONFIG),
            settings.question_guardrail_id,
            settings.question_guardrail_version,
            timeout=settings.question_guard_timeout_seconds,
            failures=NoCounter(),
        )
    )


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

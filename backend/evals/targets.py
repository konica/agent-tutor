"""How an evaluation run invokes the agent (PRD §10): one example in; the answer, citations, decline code, and
trajectory out.
An example may carry earlier turns (`history`); the outputs name the learner's own documents (`library`) for the
injection checks.

The ask target runs the ask graph the way the agent server does (apps/agent/server.py): retrieval through the MCP
server, the eval learner's token in runtime context only (ADR 0007). A recording retriever keeps each MCP `search` call
as the trajectory. Examples name seed documents (manifest ids); the learner's own copies are found by SHA-256.
"""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, Protocol

import httpx
from langchain_core.language_models import BaseChatModel

from evals.corpus import SeedDocument, load_manifest
from evals.learners import LEARNERS, LoadError, Tutor, load_learners
from smart_tutor.apps.agent.graph import build_graph
from smart_tutor.apps.agent.state import DECLINE_MESSAGES, AgentContext
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.tutoring.adapters.mcp_retriever import McpRetriever
from smart_tutor.tutoring.application import HistoryTurn, RetrievedChunk, Retriever

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
    ) -> None:
        self._learners, self._retriever_for = learners, retriever_for
        self._model, self._answer_floor, self._answer_max_tokens = model, answer_floor, answer_max_tokens

    async def __call__(self, inputs: dict[str, Any]) -> dict[str, Any]:
        username, seeds = inputs["learner"], inputs.get("documents")
        limit = None if seeds is None else [self._learners.document_id(username, s) for s in seeds]
        history = [HistoryTurn(t["question"], t["answer"]) for t in inputs.get("history") or []]
        try:
            out = await self._ask(inputs["question"], limit, history, self._learners.token(username))
        except UnauthenticatedError:  # the token expired during the run: sign in once more
            out = await self._ask(inputs["question"], limit, history, self._learners.sign_in_again(username))
        return {**out, "library": self._learners.library(username)}

    async def _ask(
        self, question: str, limit: list[str] | None, history: list[HistoryTurn], token: str
    ) -> dict[str, Any]:
        calls: list[dict[str, Any]] = []
        graph = build_graph(
            lambda t: RecordingRetriever(self._retriever_for(t), calls),
            self._model,
            self._answer_floor,
            self._answer_max_tokens,
        )
        state = await graph.ainvoke(
            {"question": question, "document_ids": limit, "history": history},
            context=AgentContext(access_token=token),
        )
        decline = state.get("decline")
        return {
            "answer": DECLINE_MESSAGES[decline] if decline else state.get("answer", ""),
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
            "decline": decline,
            "limit": limit,
            "trajectory": calls,
        }


def ask_target() -> AskTarget:
    """The ask target against the local stack: the agent model, the MCP server, Keycloak, and the API."""
    settings, seeds = Settings(), load_manifest()
    learners = load_learners(LEARNERS, seeds)
    tutors = {  # each learner in their own client: Keycloak's session cookie must not carry over
        learner.username: Tutor(httpx.Client(timeout=60), learner.username, learner.password) for learner in learners
    }
    eval_learners = EvalLearners(tutors, seeds)
    eval_learners.check_libraries({learner.username: learner.documents for learner in learners})
    return AskTarget(
        eval_learners,
        lambda token: McpRetriever(settings.mcp_url, token),
        ModelFactory(settings).chat(ChatRole.AGENT),
        settings.answer_floor,
        settings.answer_max_tokens,
    )

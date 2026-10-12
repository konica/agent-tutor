"""The ask target: the ask graph run as an eval learner, with the MCP search calls as its trajectory."""

from collections.abc import Sequence
from typing import Any

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage

from evals.corpus import SeedDocument
from evals.learners import LoadError
from evals.targets import AskTarget, EvalLearners, RecordingRetriever
from fakes import FakeRetriever, fake_chat_model
from smart_tutor.shared.domain.errors import UnauthenticatedError
from smart_tutor.tutoring.application import NO_DOCUMENTS_DECLINE, Retriever
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

CHUNKS = [
    RetrievedChunk("c1", "d1", "ReAct", 3, "ReAct interleaves thoughts and actions.", 0.9),
    RetrievedChunk("c2", "d2", "CoT", None, "Chains of thought.", 0.5),
]
ASK = {"question": "What is ReAct?", "learner": "learner@example.com", "documents": None}


class FakeLearners:
    def __init__(self, tokens: Sequence[str] = ("t-1",), ids: dict[str, str] | None = None) -> None:
        self._tokens, self.ids = list(tokens), ids or {"react-2022": "d1"}
        self.sign_ins = 0

    def token(self, username: str) -> str:
        return self._tokens[self.sign_ins]

    def sign_in_again(self, username: str) -> str:
        self.sign_ins += 1
        return self._tokens[self.sign_ins]

    def document_id(self, username: str, seed_id: str) -> str:
        return self.ids[seed_id]

    def library(self, username: str) -> list[str]:
        return sorted(self.ids.values())


def _target(
    retriever: Retriever, reply: str | None = "ReAct interleaves reasoning and acting [1].", **kw: Any
) -> AskTarget:
    model = fake_chat_model(AIMessage(reply)) if reply else fake_chat_model()
    return AskTarget(kw.get("learners", FakeLearners()), kw.get("retriever_for", lambda token: retriever), model, 0.3)


async def test_an_answer_comes_with_its_citations_and_the_search_calls() -> None:
    tokens: list[str] = []
    retriever = FakeRetriever(CHUNKS)

    def retriever_for(token: str) -> Retriever:
        tokens.append(token)
        return retriever

    out = await _target(retriever, retriever_for=retriever_for)(ASK)
    assert tokens == ["t-1"]  # the learner's token, through runtime context
    assert out["answer"] == "ReAct interleaves reasoning and acting [1]."
    assert out["citations"] == [{"n": 1, "chunk_id": "c1", "document_id": "d1", "document_title": "ReAct", "page": 3}]
    assert out["decline"] is None and out["limit"] is None
    assert out["trajectory"] == [
        {"tool": "search", "query": "What is ReAct?", "k": 5, "document_ids": None, "found": ["d1", "d2"]}
    ]


async def test_outputs_name_the_learners_own_documents() -> None:
    learners = FakeLearners(ids={"react-2022": "d1", "cot-2022": "d2"})
    out = await _target(FakeRetriever(CHUNKS), learners=learners)(ASK)
    assert out["library"] == ["d1", "d2"]


class _Seen(BaseCallbackHandler):
    def __init__(self) -> None:
        self.messages: list[list[BaseMessage]] = []
        self.params: list[dict[str, Any]] = []

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list[list[BaseMessage]], **kwargs: Any) -> None:
        self.messages.extend(messages)
        self.params.append(kwargs["invocation_params"])


async def test_history_reaches_the_answer_model_as_earlier_turns() -> None:
    seen, model = _Seen(), fake_chat_model(AIMessage("It interleaves them [1]."))
    model.callbacks = [seen]
    target = AskTarget(FakeLearners(), lambda token: FakeRetriever(CHUNKS), model, 0.3)
    history = [{"question": "What is ReAct?", "answer": "A prompting method [1]."}]
    await target({**ASK, "question": "How does it work?", "history": history})
    [sent] = seen.messages
    assert any("What is ReAct?" in str(m.content) for m in sent[:-1])


async def test_a_drift_examples_question_only_history_is_not_replayed() -> None:
    # generators/ask.py keeps a drift example's earlier questions without answers: only its last question is asked
    seen, model = _Seen(), fake_chat_model(AIMessage("It interleaves them [1]."))
    model.callbacks = [seen]
    target = AskTarget(FakeLearners(), lambda token: FakeRetriever(CHUNKS), model, 0.3)
    out = await target({**ASK, "question": "How does it work?", "history": ["What is ReAct?"]})
    [sent] = seen.messages
    assert len(sent) == 2  # the system prompt and the question: no earlier turns
    assert out["trajectory"][0]["query"] == "How does it work?"


async def test_the_answer_is_capped_at_the_configured_tokens() -> None:
    seen, model = _Seen(), fake_chat_model(AIMessage("Short [1]."))
    model.callbacks = [seen]
    target = AskTarget(FakeLearners(), lambda token: FakeRetriever(CHUNKS), model, 0.3, answer_max_tokens=77)
    await target(ASK)
    assert seen.params[0]["max_tokens"] == 77


async def test_a_limited_example_searches_the_learners_own_copies_of_its_seed_documents() -> None:
    retriever = FakeRetriever(CHUNKS[:1])
    out = await _target(retriever)({**ASK, "documents": ["react-2022"]})
    assert retriever.calls == [("What is ReAct?", 5, ["d1"])]
    assert out["limit"] == ["d1"]
    assert out["trajectory"][0]["document_ids"] == ["d1"]


async def test_a_decline_answers_with_the_message_the_learner_reads() -> None:
    out = await _target(FakeRetriever([]), reply=None)(ASK)
    assert out["decline"] == "no_documents"
    assert out["answer"] == NO_DOCUMENTS_DECLINE
    assert out["citations"] == []


async def test_a_refused_token_signs_in_again_and_asks_once_more() -> None:
    learners, retriever = FakeLearners(tokens=("old", "new")), FakeRetriever(CHUNKS)

    def retriever_for(token: str) -> Retriever:
        return FakeRetriever(error=UnauthenticatedError("expired")) if token == "old" else retriever

    out = await _target(retriever, learners=learners, retriever_for=retriever_for)(ASK)
    assert learners.sign_ins == 1
    assert out["answer"].startswith("ReAct")
    assert len(out["trajectory"]) == 1  # only the run that answered


async def test_the_trajectory_never_holds_the_token() -> None:
    out = await _target(FakeRetriever(CHUNKS))(ASK)
    assert "t-1" not in repr(out)


async def test_the_recording_retriever_passes_results_through() -> None:
    calls: list[dict[str, Any]] = []
    found = await RecordingRetriever(FakeRetriever(CHUNKS), calls).search("q", 1, ["d1"])
    assert found == CHUNKS
    assert calls == [{"tool": "search", "query": "q", "k": 1, "document_ids": ["d1"], "found": ["d1", "d2"]}]


class StubTutor:
    def __init__(self, held: dict[str, str], documents: list[str] | None = None) -> None:
        self.held, self.checks, self.token, self.sign_ins = held, 0, "tok", 0
        self.documents, self.listings = documents or [], 0

    def access_token(self) -> str:
        return self.token

    def sign_in(self) -> None:
        self.sign_ins += 1
        self.token = f"tok-{self.sign_ins}"

    def call(self, method: str, path: str, body: Any = None, ok: int = 200) -> Any:
        if (method, path) == ("GET", "/documents?state=ready"):
            self.listings += 1
            return [{"document_id": d, "title": "x"} for d in self.documents]
        assert (method, path) == ("POST", "/documents/duplicate-check")
        self.checks += 1
        return {"document_id": self.held.get(body["sha256"])}


SEEDS = {"react-2022": SeedDocument("react-2022", "https://arxiv.org/pdf/x", "abc", ("LLM agents",), "x.pdf")}


def test_a_seed_document_resolves_to_the_learners_own_copy_once() -> None:
    tutor = StubTutor({"abc": "doc-7"})
    learners = EvalLearners({"learner@example.com": tutor}, SEEDS)
    assert learners.document_id("learner@example.com", "react-2022") == "doc-7"
    assert learners.document_id("learner@example.com", "react-2022") == "doc-7"
    assert tutor.checks == 1


def test_a_seed_document_missing_from_the_library_says_to_load_the_learners() -> None:
    learners = EvalLearners({"learner@example.com": StubTutor({})}, SEEDS)
    with pytest.raises(LoadError, match="make evals-learners"):
        learners.document_id("learner@example.com", "react-2022")


def test_a_learner_missing_a_seed_document_stops_the_run_with_the_load_hint() -> None:
    learners = EvalLearners({"learner@example.com": StubTutor({"abc": "doc-7"})}, SEEDS | {"b": _seed("b", "def")})
    with pytest.raises(LoadError, match="make evals-learners"):
        learners.check_libraries({"learner@example.com": ["react-2022", "b"]})


def test_a_complete_library_passes_the_check() -> None:
    learners = EvalLearners({"learner@example.com": StubTutor({"abc": "doc-7"})}, SEEDS)
    learners.check_libraries({"learner@example.com": ["react-2022"]})
    assert learners.document_id("learner@example.com", "react-2022") == "doc-7"


def _seed(seed_id: str, sha: str) -> SeedDocument:
    return SeedDocument(seed_id, "https://arxiv.org/pdf/y", sha, ("LLM agents",), "y.pdf")


def test_the_library_is_the_learners_ready_documents_including_ones_they_uploaded_themselves() -> None:
    tutor = StubTutor({}, documents=["d-seed", "d-own-upload"])
    learners = EvalLearners({"l@x": tutor}, SEEDS)
    assert learners.library("l@x") == ["d-seed", "d-own-upload"]
    assert learners.library("l@x") == ["d-seed", "d-own-upload"]
    assert tutor.listings == 1  # read once per learner


def test_signing_in_again_gives_a_fresh_token() -> None:
    tutor = StubTutor({})
    learners = EvalLearners({"learner@example.com": tutor}, SEEDS)
    assert learners.token("learner@example.com") == "tok"
    assert learners.sign_in_again("learner@example.com") == "tok-1"


def test_an_unknown_learner_is_refused() -> None:
    with pytest.raises(ValueError, match="nobody@example.com"):
        EvalLearners({}, SEEDS).token("nobody@example.com")

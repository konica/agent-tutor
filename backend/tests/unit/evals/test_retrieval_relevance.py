"""Retrieval relevance (PRD §10.1): the Qwen judge's mean 0–1 score of the chunks the last search found."""

from typing import Any

from evals.evaluators.retrieval_relevance import RUBRIC, judged_by
from evals.suite import NOT_APPLICABLE


class FakeJudge:
    """Scores each chunk by its text, so a test can give each chunk a different score."""

    def __init__(self, scores: dict[str, float]) -> None:
        self.scores = scores
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        text = kwargs["outputs"]["chunk"]["text"]
        return {"key": "retrieval_relevance", "score": self.scores[text], "comment": f"About {text}."}


def _chunk(text: str, title: str = "ReAct") -> dict[str, Any]:
    return {"chunk_id": "c", "document_id": "d", "document_title": title, "page": 1, "score": 0.5, "text": text}


INPUTS = {"question": "What is ReAct?", "learner": "learner@example.com", "documents": None}
COVERED = {"covered": True, "sources": ["react-2022"]}


async def test_the_score_is_the_mean_of_the_chunks_and_the_comment_names_the_lowest() -> None:
    judge = FakeJudge({"a": 1.0, "b": 0.0, "c": 0.5})
    result = await judged_by(lambda: judge)(
        inputs=INPUTS, outputs={"chunks": [_chunk("a"), _chunk("b"), _chunk("c")]}, reference_outputs=COVERED
    )
    assert result["key"] == "retrieval_relevance" and result["score"] == 0.5
    assert result["comment"] == "chunk scores 1.00, 0.00, 0.50; lowest: About b."


async def test_the_judge_sees_each_chunk_with_its_document_and_the_question() -> None:
    judge = FakeJudge({"a": 1.0})
    await judged_by(lambda: judge)(
        inputs=INPUTS, outputs={"chunks": [_chunk("a", title="Reasoning and Acting")]}, reference_outputs=COVERED
    )
    assert judge.calls == [
        {
            "inputs": {"question": "What is ReAct?"},
            "outputs": {"chunk": {"document": "Reasoning and Acting", "text": "a"}},
        }
    ]


async def test_a_follow_up_passes_the_earlier_questions() -> None:
    judge = FakeJudge({"a": 1.0})
    await judged_by(lambda: judge)(
        inputs={**INPUTS, "question": "And its limits?", "history": ["What is ReAct?"]},
        outputs={"chunks": [_chunk("a")]},
        reference_outputs=COVERED,
    )
    assert judge.calls[0]["inputs"] == {"earlier_questions": ["What is ReAct?"], "question": "And its limits?"}


async def test_a_question_the_library_does_not_cover_is_not_applicable() -> None:
    judge = FakeJudge({})
    result = await judged_by(lambda: judge)(
        inputs=INPUTS, outputs={"chunks": [_chunk("a")]}, reference_outputs={"covered": False, "sources": []}
    )
    assert result["score"] is None and result["value"] == NOT_APPLICABLE
    assert judge.calls == []


async def test_a_failed_run_scores_zero_without_calling_the_judge() -> None:
    judge = FakeJudge({})
    result = await judged_by(lambda: judge)(inputs=INPUTS, outputs={}, reference_outputs=COVERED)
    assert result["score"] == 0 and "failed" in result["comment"]
    assert judge.calls == []


async def test_a_search_that_found_nothing_scores_zero_without_calling_the_judge() -> None:
    judge = FakeJudge({})
    result = await judged_by(lambda: judge)(inputs=INPUTS, outputs={"chunks": []}, reference_outputs=COVERED)
    assert result["score"] == 0 and "found nothing" in result["comment"]
    assert judge.calls == []


def test_the_rubric_formats_with_the_judge_inputs_only() -> None:
    text = RUBRIC.read_text(encoding="utf-8")
    formatted = text.format(inputs="<Q>", outputs="<C>", reference_outputs="<R>")  # stray braces would raise
    assert "<Q>" in formatted and "<C>" in formatted
    assert "{reference_outputs}" not in text  # the judge gets no reference

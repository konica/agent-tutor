"""Answer relevance (PRD §10.1): the Qwen judge's 0–1 score of the answer the learner saw."""

from typing import Any

from evals.evaluators.answer_relevance import RUBRIC, judged_by


class FakeJudge:
    def __init__(self, score: float = 0.9) -> None:
        self.score = score
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"key": "answer_relevance", "score": self.score, "comment": "On point."}


async def test_the_judge_sees_the_question_the_answer_and_whether_the_library_covers_it() -> None:
    judge = FakeJudge()
    result = await judged_by(lambda: judge)(
        inputs={"question": "What is ReAct?", "learner": "learner@example.com", "documents": None},
        outputs={"answer": "ReAct interleaves reasoning and acting [1].", "trajectory": [], "limit": None},
        reference_outputs={"covered": True, "sources": ["react-2022"]},
    )
    assert result == {"key": "answer_relevance", "score": 0.9, "comment": "On point."}
    assert judge.calls == [
        {
            "inputs": {"question": "What is ReAct?"},
            "outputs": {"answer": "ReAct interleaves reasoning and acting [1]."},
            "reference_outputs": {"covered": True},
        }
    ]


async def test_a_failed_run_scores_zero_without_calling_the_judge() -> None:
    judge = FakeJudge()
    result = await judged_by(lambda: judge)(inputs={"question": "q"}, outputs={}, reference_outputs={"covered": True})
    assert result["score"] == 0 and "failed" in result["comment"]
    assert judge.calls == []


def test_the_rubric_formats_with_the_three_judge_inputs_only() -> None:
    text = RUBRIC.read_text(encoding="utf-8")
    formatted = text.format(inputs="<Q>", outputs="<A>", reference_outputs="<R>")  # stray braces would raise
    assert "<Q>" in formatted and "<A>" in formatted and "<R>" in formatted
    assert "covered" in text

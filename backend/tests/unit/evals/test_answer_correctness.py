"""Answer correctness (PRD §10.1): the Qwen judge scores the answer against the gold row's reference answer."""

from typing import Any

import pytest

from evals.evaluators.answer_correctness import RUBRIC, judged_by
from evals.suite import NOT_APPLICABLE

REFERENCE = {
    "covered": True,
    "answer": "ReAct interleaves reasoning traces with actions, evaluated on HotpotQA.",
    "evidence": [{"source": "react-2022", "page": 1, "quote": "SECRET QUOTE"}],
}
OUTPUTS = {
    "answer": "ReAct interleaves reasoning and acting [1].",
    "decline": None,
    "citations": [{"n": 1, "chunk_id": "c1"}],
    "chunks": [{"chunk_id": "c1", "text": "CHUNK TEXT"}],
}


class FakeJudge:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.result


async def run(judge: FakeJudge, outputs: dict[str, Any] = OUTPUTS, reference: dict[str, Any] = REFERENCE) -> Any:
    return await judged_by(lambda: judge)(
        inputs={"question": "What is ReAct?"}, outputs=outputs, reference_outputs=reference
    )


async def test_the_judges_score_and_reason_are_the_result() -> None:
    result = await run(FakeJudge({"score": 0.5, "comment": "misses HotpotQA"}))
    assert result["key"] == "answer_correctness" and result["score"] == pytest.approx(0.5)
    assert result["comment"] == "misses HotpotQA"


async def test_a_decline_on_a_covered_row_scores_zero_without_the_judge() -> None:
    judge = FakeJudge({})
    result = await run(judge, {**OUTPUTS, "decline": "not_covered"})
    assert result["score"] == 0 and "declined" in result["comment"]
    assert judge.calls == []


async def test_a_failed_run_scores_zero_without_the_judge() -> None:
    judge = FakeJudge({})
    result = await run(judge, {"error": "boom"})
    assert result["score"] == 0 and "failed" in result["comment"]
    assert judge.calls == []


@pytest.mark.parametrize(
    "reference",
    [{"covered": True}, {"covered": True, "answer": ""}, {"covered": False, "answer": REFERENCE["answer"]}],
)
async def test_a_row_without_a_reference_answer_or_uncovered_is_not_applicable(reference: dict[str, Any]) -> None:
    judge = FakeJudge({})
    result = await run(judge, reference=reference)
    assert result["value"] == NOT_APPLICABLE and result["score"] is None
    assert judge.calls == []


async def test_the_judge_gets_the_question_the_answer_and_the_reference_but_never_quotes_or_chunks() -> None:
    judge = FakeJudge({"score": 1.0, "comment": None})
    await judged_by(lambda: judge)(
        inputs={"question": "And its limits?", "history": ["What is ReAct?"]},
        outputs=OUTPUTS,
        reference_outputs=REFERENCE,
    )
    assert judge.calls == [
        {
            "inputs": {"earlier_questions": ["What is ReAct?"], "question": "And its limits?"},
            "outputs": {"answer": OUTPUTS["answer"]},
            "reference_outputs": {"answer": REFERENCE["answer"]},
        }
    ]
    assert "SECRET QUOTE" not in str(judge.calls) and "CHUNK TEXT" not in str(judge.calls)


def test_the_rubric_formats_with_the_three_judge_inputs_only() -> None:
    formatted = RUBRIC.read_text(encoding="utf-8").format(inputs="<Q>", outputs="<A>", reference_outputs="<R>")
    assert "<Q>" in formatted and "<A>" in formatted and "<R>" in formatted

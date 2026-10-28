"""Answer correctness (PRD §10.1, §7.5): supported nugget recall from the Qwen judge's per-nugget verdicts."""

from typing import Any

import pytest

from evals.evaluators.answer_correctness import RUBRIC, judged_by
from evals.suite import NOT_APPLICABLE

NUGGETS = [
    {"fact": "ReAct interleaves reasoning and acting.", "evidence": [0]},
    {"fact": "It was evaluated on HotpotQA.", "evidence": [1]},
    {"fact": "It reduces hallucination versus chain-of-thought alone.", "evidence": [1]},
]
REFERENCE = {
    "covered": True,
    "nuggets": NUGGETS,
    "evidence": [{"source": "react-2022", "page": 1, "quote": "SECRET QUOTE"}] * 2,
}
OUTPUTS = {
    "answer": "ReAct interleaves reasoning and acting [1].",
    "decline": None,
    "citations": [{"n": 1, "chunk_id": "c1"}, {"n": 2, "chunk_id": "gone"}],
    "chunks": [{"chunk_id": "c1", "text": "ReAct interleaves reasoning traces and actions."}],
}


def verdicts(*flags: tuple[bool, bool]) -> dict[str, Any]:
    return {
        "nuggets": [{"index": i, "stated": s, "supported": p} for i, (s, p) in enumerate(flags)],
        "reasoning": "because",
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


async def test_two_of_three_supported_scores_two_thirds_and_names_the_missed_nugget() -> None:
    result = await run(FakeJudge(verdicts((True, True), (True, True), (False, False))))
    assert result["key"] == "answer_correctness" and result["score"] == pytest.approx(2 / 3)
    assert "#2 It reduces hallucination" in result["comment"] and "because" in result["comment"]
    assert "#0" not in result["comment"]


async def test_stated_but_unsupported_counts_zero() -> None:
    result = await run(FakeJudge(verdicts((True, False), (True, False), (True, False))))
    assert result["score"] == 0 and "#0" in result["comment"]


async def test_a_nugget_the_judge_omitted_is_unsupported() -> None:
    result = await run(FakeJudge({"nuggets": [{"index": 0, "stated": True, "supported": True}]}))
    assert result["score"] == pytest.approx(1 / 3) and "#1" in result["comment"] and "#2" in result["comment"]


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
    [{"covered": True}, {"covered": True, "nuggets": []}, {"covered": False, "nuggets": NUGGETS}],
)
async def test_a_row_without_nuggets_or_uncovered_is_not_applicable(reference: dict[str, Any]) -> None:
    judge = FakeJudge({})
    result = await run(judge, reference=reference)
    assert result["value"] == NOT_APPLICABLE and result["score"] is None
    assert judge.calls == []


async def test_the_judge_gets_facts_and_cited_chunk_text_but_never_the_evidence_quotes() -> None:
    judge = FakeJudge(verdicts((True, True), (True, True), (True, True)))
    await judged_by(lambda: judge)(
        inputs={"question": "And its limits?", "history": ["What is ReAct?"]},
        outputs=OUTPUTS,
        reference_outputs=REFERENCE,
    )
    assert judge.calls == [
        {
            "inputs": {"earlier_questions": ["What is ReAct?"], "question": "And its limits?"},
            "outputs": {
                "answer": OUTPUTS["answer"],
                "cited_chunks": [{"n": 1, "text": "ReAct interleaves reasoning traces and actions."}],
            },
            "reference_outputs": {"nuggets": [{"index": i, "fact": n["fact"]} for i, n in enumerate(NUGGETS)]},
        }
    ]
    assert "SECRET QUOTE" not in str(judge.calls)


def test_the_rubric_formats_with_the_three_judge_inputs_only() -> None:
    formatted = RUBRIC.read_text(encoding="utf-8").format(inputs="<Q>", outputs="<A>", reference_outputs="<R>")
    assert "<Q>" in formatted and "<A>" in formatted and "<R>" in formatted

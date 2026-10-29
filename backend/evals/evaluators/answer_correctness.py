"""Answer correctness (PRD §10.1, LLM-as-judge): how fully the answer states the facts of the gold row's reference
answer without contradicting it. Judge: the `judge` model role with rubrics/answer_correctness.md; a 0–1 score and a
short reason. Extra true facts are not penalized, since a reference answer is never complete. The evidence quotes never
reach the judge."""

from collections.abc import Awaitable, Callable
from functools import cache
from pathlib import Path
from typing import Any

from evals.suite import Evaluator, Suite, not_applicable, scores
from evals.targets import ask_target
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.config import Settings

KEY = "answer_correctness"
RUBRIC = Path(__file__).parent / "rubrics" / "answer_correctness.md"
Judge = Callable[..., Awaitable[dict[str, Any]]]


@cache
def _judge() -> Judge:
    from openevals.llm import create_async_llm_as_judge  # the eval extra: not installed for unit tests

    judge: Judge = create_async_llm_as_judge(
        prompt=RUBRIC.read_text(encoding="utf-8"),
        judge=ModelFactory(Settings()).chat(ChatRole.JUDGE),
        feedback_key=KEY,
        continuous=True,
    )
    return judge


def judged_by(judge: Callable[[], Judge]) -> Evaluator:
    @scores(KEY)
    async def answer_correctness(
        inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
    ) -> dict[str, Any]:
        reference = reference_outputs.get("answer")
        if not reference or not reference_outputs.get("covered"):
            return not_applicable(KEY, "the row has no reference answer")
        if "answer" not in outputs:
            return {"key": KEY, "score": 0.0, "comment": "the run failed before it answered"}
        if outputs.get("decline"):
            return {"key": KEY, "score": 0.0, "comment": f"declined a covered question ({outputs['decline']})"}
        judged = {"question": inputs["question"]}
        if inputs.get("history"):
            judged = {"earlier_questions": inputs["history"], **judged}
        result = await judge()(
            inputs=judged,
            outputs={"answer": outputs["answer"]},
            reference_outputs={"answer": reference},
        )
        return {"key": KEY, "score": float(result["score"]), "comment": result.get("comment")}

    return answer_correctness


answer_correctness = judged_by(_judge)

SUITE = Suite(dataset="ask", target=ask_target, evaluators=(answer_correctness,))

"""Answer relevance (PRD §10.1, LLM-as-judge): how well the answer the learner saw serves their question, given
whether their library covers it. Judge: the `judge` model role (Qwen, temperature 0) with rubrics/answer_relevance.md;
a 0–1 score and a short reason."""

from collections.abc import Awaitable, Callable
from functools import cache
from pathlib import Path
from typing import Any

from evals.suite import Evaluator, Suite, scores
from evals.targets import ask_target
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.config import Settings

KEY = "answer_relevance"
RUBRIC = Path(__file__).parent / "rubrics" / "answer_relevance.md"
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
    async def answer_relevance(
        inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
    ) -> dict[str, Any]:
        if "answer" not in outputs:
            return {"key": KEY, "score": 0.0, "comment": "the run failed before it answered"}
        judged = {"question": inputs["question"]}
        if inputs.get("history"):
            judged = {"earlier_questions": inputs["history"], **judged}
        result = await judge()(
            inputs=judged,
            outputs={"answer": outputs["answer"]},
            reference_outputs={"covered": reference_outputs.get("covered")},
        )
        return {"key": KEY, "score": float(result["score"]), "comment": result.get("comment")}

    return answer_relevance


answer_relevance = judged_by(_judge)

SUITE = Suite(dataset="ask", target=ask_target, evaluators=(answer_relevance,))

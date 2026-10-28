"""Answer correctness (PRD §10.1, LLM-as-judge): supported nugget recall. Each gold row lists the facts a correct answer
must contain; the judge (the `judge` model role, rubrics/answer_correctness.md) marks each as stated and as supported by
a chunk the answer cites. Score = nuggets both stated and supported / nuggets. The evidence quotes never reach the
judge."""

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
VERDICT_SCHEMA: dict[str, Any] = {
    "title": "nugget_verdicts",
    "description": "Whether the answer states each reference nugget and supports it with a cited chunk.",
    "type": "object",
    "properties": {
        "reasoning": {"type": "string", "description": "What was missed or unsupported, briefly."},
        "nuggets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "stated": {"type": "boolean"},
                    "supported": {"type": "boolean"},
                },
                "required": ["index", "stated", "supported"],
            },
        },
    },
    "required": ["nuggets"],
}


@cache
def _judge() -> Judge:
    from openevals.llm import create_async_llm_as_judge  # the eval extra: not installed for unit tests

    judge: Judge = create_async_llm_as_judge(
        prompt=RUBRIC.read_text(encoding="utf-8"),
        judge=ModelFactory(Settings()).chat(ChatRole.JUDGE),
        feedback_key=KEY,
        output_schema=VERDICT_SCHEMA,  # the judge returns this structure, not {score, comment}
    )
    return judge


def _cited_chunks(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    text = {c["chunk_id"]: c["text"] for c in outputs.get("chunks") or []}
    return [{"n": c["n"], "text": text[c["chunk_id"]]} for c in outputs.get("citations") or [] if c["chunk_id"] in text]


def judged_by(judge: Callable[[], Judge]) -> Evaluator:
    @scores(KEY)
    async def answer_correctness(
        inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
    ) -> dict[str, Any]:
        nuggets = reference_outputs.get("nuggets")
        if not nuggets or not reference_outputs.get("covered"):
            return not_applicable(KEY, "the row has no nuggets")
        if "answer" not in outputs:
            return {"key": KEY, "score": 0.0, "comment": "the run failed before it answered"}
        if outputs.get("decline"):
            return {"key": KEY, "score": 0.0, "comment": f"declined a covered question ({outputs['decline']})"}
        judged = {"question": inputs["question"]}
        if inputs.get("history"):
            judged = {"earlier_questions": inputs["history"], **judged}
        result = await judge()(
            inputs=judged,
            outputs={"answer": outputs["answer"], "cited_chunks": _cited_chunks(outputs)},
            reference_outputs={"nuggets": [{"index": i, "fact": n["fact"]} for i, n in enumerate(nuggets)]},
        )
        verdicts = {v["index"]: v for v in result.get("nuggets") or []}
        missed = [
            f"#{i} {n['fact'][:80]}"
            for i, n in enumerate(nuggets)
            if not (verdicts.get(i, {}).get("stated") and verdicts.get(i, {}).get("supported"))
        ]
        notes = [f"missed: {', '.join(missed)}"] if missed else []
        notes += [result["reasoning"]] if result.get("reasoning") else []
        return {"key": KEY, "score": (len(nuggets) - len(missed)) / len(nuggets), "comment": "; ".join(notes) or None}

    return answer_correctness


answer_correctness = judged_by(_judge)

SUITE = Suite(dataset="ask", target=ask_target, evaluators=(answer_correctness,))

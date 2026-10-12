"""Retrieval relevance (PRD §10.1, LLM-as-judge): how well each chunk the last search found serves the question. Judge:
the `judge` model role (Qwen, temperature 0) with rubrics/retrieval_relevance.md, one call per chunk; the score is the
mean of the chunks' 0–1 scores. Not scored when the library doesn't cover the question: nothing there should help."""

import asyncio
from collections.abc import Awaitable, Callable
from functools import cache
from pathlib import Path
from typing import Any

from evals.suite import Evaluator, Suite, not_applicable
from evals.targets import ask_target
from smart_tutor.shared.adapters.model_factory import ChatRole, ModelFactory
from smart_tutor.shared.config import Settings

KEY = "retrieval_relevance"
RUBRIC = Path(__file__).parent / "rubrics" / "retrieval_relevance.md"
Judge = Callable[..., Awaitable[dict[str, Any]]]
MAX_CONCURRENT_JUDGE_CALLS = 4  # the runner has several examples in flight, each with a call per chunk
_gates: dict[asyncio.AbstractEventLoop, asyncio.Semaphore] = {}


def _gate() -> asyncio.Semaphore:
    """The semaphore of the running event loop (a semaphore made in another loop would not work here)."""
    loop = asyncio.get_running_loop()
    if loop not in _gates:
        _gates.clear()  # only the running loop matters; drop closed ones
        _gates[loop] = asyncio.Semaphore(MAX_CONCURRENT_JUDGE_CALLS)
    return _gates[loop]


async def _judge_chunk(judge: Judge, judged: dict[str, Any], chunk: dict[str, Any]) -> dict[str, Any]:
    async with _gate():
        return await judge(
            inputs=judged, outputs={"chunk": {"document": chunk["document_title"], "text": chunk["text"]}}
        )


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
    async def retrieval_relevance(
        inputs: dict[str, Any], outputs: dict[str, Any], reference_outputs: dict[str, Any]
    ) -> dict[str, Any]:
        if not reference_outputs.get("covered"):
            return not_applicable(KEY, "the library doesn't cover the question: decline correctness scores it")
        if "chunks" not in outputs:
            return {"key": KEY, "score": 0.0, "comment": "the run failed before it searched"}
        chunks = outputs["chunks"]
        if not chunks:
            return {"key": KEY, "score": 0.0, "comment": "the search found nothing"}
        judged = {"question": inputs["question"]}
        if inputs.get("history"):
            judged = {"earlier_questions": inputs["history"], **judged}
        results = await asyncio.gather(*(_judge_chunk(judge(), judged, c) for c in chunks))
        scores = [float(r["score"]) for r in results]
        lowest = min(results, key=lambda r: float(r["score"]))
        comment = f"chunk scores {', '.join(f'{s:.2f}' for s in scores)}; lowest: {lowest.get('comment')}"
        return {"key": KEY, "score": sum(scores) / len(scores), "comment": comment}

    return retrieval_relevance


retrieval_relevance = judged_by(_judge)

SUITE = Suite(dataset="ask", target=ask_target, evaluators=(retrieval_relevance,))

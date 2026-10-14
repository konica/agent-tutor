"""Search step ran (PRD §10.1, code): every turn calls MCP `search` over the learner's readable documents, limited to
the conversation's listed documents when its search is limited (US-4c), and a limited search finds only those
documents' chunks. An off-topic decline makes no search and is not applicable.
Scored 1 or 0 from the ask target's trajectory, with the reason."""

from collections.abc import Sequence
from typing import Any

from evals.suite import Suite, not_applicable
from evals.targets import ask_target

KEY = "search_step_ran"


def _score(score: int, comment: str) -> dict[str, Any]:
    return {"key": KEY, "score": score, "comment": comment}


def _same(a: Sequence[str] | None, b: Sequence[str] | None) -> bool:
    return a is None and b is None or a is not None and b is not None and set(a) == set(b)


def search_step_ran(outputs: dict[str, Any]) -> dict[str, Any]:
    if "trajectory" not in outputs:
        return _score(0, "the run failed before it searched")
    searches = [c for c in outputs["trajectory"] if c["tool"] == "search"]
    if outputs.get("decline") == "off_topic":  # declined before search (spec 2026-10-13); PRD §10.1: answered turns
        if searches:
            return _score(0, "an off-topic decline still searched")
        return not_applicable(KEY, "an off-topic question is declined before search")
    limit = outputs["limit"]
    scope = "the listed documents" if limit is not None else "all the learner's documents"
    if not any(_same(c["document_ids"], limit) for c in searches):
        return _score(0, f"no search over {scope}")
    for call in searches:
        if call["document_ids"] is not None and (outside := set(call["found"]) - set(call["document_ids"])):
            return _score(0, f"a limited search found chunks of other documents: {', '.join(sorted(outside))}")
    return _score(1, f"searched {scope}")


SUITE = Suite(dataset="ask", target=ask_target, evaluators=(search_step_ran,))

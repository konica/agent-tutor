"""Gold evidence (design 2026-10-28 §7, code): scores an ask run against the quotes a gold row names.
`retrieved_recall`: the share of gold quotes found in the chunks the search returned. `cited_recall`: the same over
the chunks the answer cited. `gold_rank`: 1 / rank of the first retrieved chunk holding a gold quote, else 0.
`distractor_cited`: 1 when a cited chunk holds a distractor quote and no gold quote.
This reads §7.4 per chunk, not per answer: a cited chunk counts as noise only when it holds a distractor quote and none
of the row's gold quotes. A worker chunk (1,000 characters) can hold a distractor next to a passage that supports the
answer, so distractors are labeled only where they share no chunk with gold (`evals.evidence` fails a row otherwise).
Quotes match by `evidence.contains`. Recall and rank score covered rows with evidence;
`distractor_cited` scores rows with distractors; on an uncovered row there is no gold quote, so any cited chunk
holding a distractor quote scores 1, and a run that failed before it answered cited nothing and scores 0."""

from typing import Any

from evals.evidence import contains
from evals.suite import Suite, not_applicable, scores
from evals.targets import ask_target

RETRIEVED_RECALL = "evidence.retrieved_recall"
CITED_RECALL = "evidence.cited_recall"
GOLD_RANK = "evidence.gold_rank"
DISTRACTOR_CITED = "evidence.distractor_cited"
NO_EVIDENCE = "the row has no gold evidence"
NO_DISTRACTORS = "the row has no distractors"
NOT_SEARCHED = "the run failed before it searched"


def _score(key: str, score: float, comment: str) -> dict[str, Any]:
    return {"key": key, "score": score, "comment": comment}


def _quotes(reference_outputs: dict[str, Any], field: str) -> list[str]:
    return [str(item["quote"]) for item in reference_outputs.get(field) or []]


def _gold(reference_outputs: dict[str, Any]) -> list[str]:
    """The gold quotes of a covered row; [] when the row carries none."""
    return _quotes(reference_outputs, "evidence") if reference_outputs.get("covered") else []


def _cited(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    ids = {c["chunk_id"] for c in outputs["citations"]}
    return [c for c in outputs["chunks"] if c["chunk_id"] in ids]  # an unknown cited id matches no chunk


def _holds(chunk: dict[str, Any], quotes: list[str]) -> bool:
    return any(contains(chunk["text"], q) for q in quotes)


def _recall(key: str, chunks: list[dict[str, Any]], gold: list[str]) -> dict[str, Any]:
    missed = [q for q in gold if not any(contains(c["text"], q) for c in chunks)]
    comment = f"{len(gold) - len(missed)} of {len(gold)} gold quotes"
    if missed:
        comment += "; missed: " + " | ".join(q[:60] for q in missed)
    return _score(key, (len(gold) - len(missed)) / len(gold), comment)


@scores(RETRIEVED_RECALL)
def retrieved_recall(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not (gold := _gold(reference_outputs)):
        return not_applicable(RETRIEVED_RECALL, NO_EVIDENCE)
    if "chunks" not in outputs:
        return _score(RETRIEVED_RECALL, 0, NOT_SEARCHED)
    return _recall(RETRIEVED_RECALL, outputs["chunks"], gold)


@scores(CITED_RECALL)
def cited_recall(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not (gold := _gold(reference_outputs)):
        return not_applicable(CITED_RECALL, NO_EVIDENCE)
    if "chunks" not in outputs or "citations" not in outputs:
        return _score(CITED_RECALL, 0, NOT_SEARCHED)
    return _recall(CITED_RECALL, _cited(outputs), gold)


@scores(GOLD_RANK)
def gold_rank(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not (gold := _gold(reference_outputs)):
        return not_applicable(GOLD_RANK, NO_EVIDENCE)
    if "chunks" not in outputs:
        return _score(GOLD_RANK, 0, NOT_SEARCHED)
    for i, chunk in enumerate(outputs["chunks"]):
        if _holds(chunk, gold):
            return _score(GOLD_RANK, 1 / (i + 1), f"first gold chunk {chunk['chunk_id']} at rank {i + 1}")
    return _score(GOLD_RANK, 0, "no retrieved chunk holds a gold quote")


@scores(DISTRACTOR_CITED)
def distractor_cited(outputs: dict[str, Any], reference_outputs: dict[str, Any]) -> dict[str, Any]:
    if not (distractors := _quotes(reference_outputs, "distractors")):
        return not_applicable(DISTRACTOR_CITED, NO_DISTRACTORS)
    if "chunks" not in outputs or "citations" not in outputs:  # nothing was cited
        return _score(DISTRACTOR_CITED, 0, "the run failed before it answered")
    gold = _gold(reference_outputs)  # [] on an uncovered row, so "no gold quote" holds vacuously
    for chunk in _cited(outputs):
        if _holds(chunk, distractors) and not _holds(chunk, gold):
            return _score(DISTRACTOR_CITED, 1, f"cited chunk {chunk['chunk_id']} holds a distractor quote")
    return _score(DISTRACTOR_CITED, 0, "no cited chunk holds a distractor quote without a gold quote")


SUITE = Suite(
    dataset="ask", target=ask_target, evaluators=(retrieved_recall, cited_recall, gold_rank, distractor_cited)
)

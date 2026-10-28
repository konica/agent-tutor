"""Gold evidence evaluators (design 2026-10-28 §7): retrieved and cited recall, gold rank, distractor citations."""

from typing import Any

from evals.evaluators import gold_evidence as g
from evals.suite import NOT_APPLICABLE, metric_of

QA = "Accuracy on the test set was 91 percent."
QB = "The model has 12 layers in total."
QD = "Accuracy on the dev set was 88 percent."


def _chunk(chunk_id: str, text: str) -> dict[str, Any]:
    return {"chunk_id": chunk_id, "document_id": "d1", "document_title": "T", "page": 1, "score": 0.5, "text": text}


def _run(chunks: list[dict[str, Any]], cited: list[str]) -> dict[str, Any]:
    return {"chunks": chunks, "citations": [{"n": i + 1, "chunk_id": c} for i, c in enumerate(cited)], "answer": "a"}


def _ref(**extra: Any) -> dict[str, Any]:
    gold = [{"source": "s", "page": 1, "quote": QA}, {"source": "s", "page": 2, "quote": QB}]
    return {"covered": True, "sources": ["s"], "evidence": gold, **extra}


def test_recall_rank_and_cited_recall_on_a_partial_hit() -> None:
    out = _run([_chunk("c0", QD), _chunk("cA", "intro " + QA)], ["cA"])
    assert g.retrieved_recall(out, _ref())["score"] == 0.5
    assert g.cited_recall(out, _ref())["score"] == 0.5
    assert g.gold_rank(out, _ref())["score"] == 0.5
    assert QB[:60] in g.retrieved_recall(out, _ref())["comment"]
    assert QB[:60] in g.cited_recall(out, _ref())["comment"]


def test_cited_recall_ignores_retrieved_but_uncited_and_unknown_citations() -> None:
    out = _run([_chunk("cA", QA), _chunk("cB", QB)], ["cA", "nope"])
    assert g.retrieved_recall(out, _ref())["score"] == 1
    assert g.cited_recall(out, _ref())["score"] == 0.5
    assert g.gold_rank(out, _ref())["score"] == 1


def test_no_gold_chunk_retrieved_scores_0() -> None:
    out = _run([_chunk("c0", QD)], [])
    assert g.gold_rank(out, _ref())["score"] == 0
    assert g.retrieved_recall(out, _ref())["score"] == 0


def test_matching_is_normalized() -> None:
    ref = {"covered": True, "sources": ["s"], "evidence": [{"source": "s", "page": 1, "quote": "final score is 86.3%"}]}
    out = _run([_chunk("c", "the ﬁnal\nscore is 86. 3%")], ["c"])
    assert g.retrieved_recall(out, ref)["score"] == 1


def test_distractor_cited_alone_scores_1_and_with_gold_scores_0() -> None:
    ref = _ref(distractors=[{"source": "s", "page": 3, "quote": QD}])
    assert g.distractor_cited(_run([_chunk("cD", QD)], ["cD"]), ref)["score"] == 1
    assert "cD" in g.distractor_cited(_run([_chunk("cD", QD)], ["cD"]), ref)["comment"]
    both = _run([_chunk("cX", QD + " " + QA)], ["cX"])
    assert g.distractor_cited(both, ref)["score"] == 0
    assert g.distractor_cited(_run([_chunk("cD", QD)], []), ref)["score"] == 0


def test_distractor_cited_on_an_uncovered_row() -> None:
    ref = {"covered": False, "sources": [], "distractors": [{"source": "s", "page": 3, "quote": QD}]}
    assert g.distractor_cited(_run([_chunk("cD", QD)], ["cD"]), ref)["score"] == 1
    assert g.distractor_cited(_run([_chunk("cD", QD)], []), ref)["score"] == 0


def test_a_failed_run_scores_0() -> None:
    failed = {"error": "boom"}
    for evaluator in (g.retrieved_recall, g.cited_recall, g.gold_rank):
        assert evaluator(failed, _ref())["score"] == 0
    ref = _ref(distractors=[{"source": "s", "page": 3, "quote": QD}])
    assert g.distractor_cited(failed, ref)["score"] == 0


def test_rows_without_labels_are_not_applicable() -> None:
    plain = {"covered": True, "sources": ["s"]}
    uncovered = {"covered": False, "sources": [], "evidence": [{"source": "s", "page": 1, "quote": QA}]}
    out = _run([_chunk("c", QA)], ["c"])
    for evaluator in (g.retrieved_recall, g.cited_recall, g.gold_rank):
        assert evaluator(out, plain)["value"] == NOT_APPLICABLE
        assert evaluator(out, uncovered)["value"] == NOT_APPLICABLE
        assert evaluator({"error": "x"}, plain)["value"] == NOT_APPLICABLE
    assert g.distractor_cited(out, _ref())["value"] == NOT_APPLICABLE


def test_suite_lists_the_four_evaluators() -> None:
    assert g.SUITE.dataset == "ask"
    keys = {
        "evidence.retrieved_recall",
        "evidence.cited_recall",
        "evidence.gold_rank",
        "evidence.distractor_cited",
    }
    assert {metric_of(e) for e in g.SUITE.evaluators} == keys
    assert {g.RETRIEVED_RECALL, g.CITED_RECALL, g.GOLD_RANK, g.DISTRACTOR_CITED} == keys


def test_a_run_with_chunks_but_no_citations_scores_0() -> None:
    out = {"chunks": [_chunk("cA", QA), _chunk("cD", QD)]}
    assert g.cited_recall(out, _ref())["score"] == 0
    ref = _ref(distractors=[{"source": "s", "page": 3, "quote": QD}])
    assert g.distractor_cited(out, ref)["score"] == 0

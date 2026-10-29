"""The evidence checker's pure parts: quote normalization, gold-row rules, the category x difficulty mix."""

from typing import Any

from evals import evidence
from evals.dataset import Example

QUOTE_A = "If rejected, the system discards the candidate skill modifications and reverts the skill set"
QUOTE_B = "is never rolled back regardless of the acceptance decision; accumulated patterns persist"


def gold(**changes: Any) -> Example:
    """A valid covered single_hop row; `changes` replace top-level outputs keys, or metadata via `metadata=`."""
    outputs: dict[str, Any] = {
        "covered": True,
        "sources": ["wikiskill-2026"],
        "answer": "It discards the candidate skill change and keeps the wiki.",
        "evidence": [
            {"source": "wikiskill-2026", "page": 6, "quote": QUOTE_A},
            {"source": "wikiskill-2026", "page": 6, "quote": QUOTE_B},
        ],
    }
    metadata = {"category": "single_hop", "type": "conceptual", "difficulty": "medium"}
    metadata.update(changes.pop("metadata", {}))
    outputs.update(changes)
    inputs = {"question": "What gets thrown away?", "learner": "learner2@example.com", "documents": None}
    return Example(inputs, outputs, metadata)


def uncovered(**changes: Any) -> Example:
    outputs: dict[str, Any] = {"covered": False, "sources": []}
    metadata = {"category": "unanswerable", "type": "unanswerable", "difficulty": "medium"}
    metadata.update(changes.pop("metadata", {}))
    outputs.update(changes)
    return Example({"question": "q", "learner": "learner2@example.com", "documents": None}, outputs, metadata)


def with_evidence(**quote: Any) -> Example:
    row = gold()
    row.outputs["evidence"][0].update(quote)
    return row


def rows(*pairs: tuple[str, str]) -> list[Example]:
    return [gold(metadata={"category": c, "difficulty": d}) for c, d in pairs]


def test_normalize_drops_case_hyphen_breaks_ligatures_and_math_letters() -> None:
    assert evidence.normalize("Deci-\nsion ﬁne 𝑥 GYM") == "decisionfinexgym"


def test_contains_matches_across_spacing_and_small_caps_splits() -> None:
    assert evidence.contains("the DECI -SION GYM tool", "decision gym")
    assert not evidence.contains("abc", "")
    assert not evidence.contains("abc", " - ")


def test_a_valid_covered_row_has_no_problems() -> None:
    assert evidence.row_problems(gold()) == []


def test_a_row_without_a_category_or_new_fields_is_not_gold() -> None:
    row = Example({"question": "q"}, {"covered": True, "sources": ["react-2022"]})
    assert not evidence.is_gold(row)
    assert evidence.row_problems(row) == []
    assert evidence.is_gold(gold())


def test_evidence_source_must_be_one_of_the_rows_sources() -> None:
    problems = evidence.row_problems(with_evidence(source="jevharness-2026"))
    assert any("sources" in p for p in problems)


def test_a_quote_over_200_characters_fails() -> None:
    problems = evidence.row_problems(with_evidence(quote="x" * 201))
    assert any("200" in p for p in problems)
    assert evidence.row_problems(with_evidence(quote="x" * 200)) == []


def test_a_gold_row_carrying_nuggets_fails() -> None:
    nuggets = [{"fact": "A rejected skill change is discarded.", "evidence": [0]}]
    assert any("nuggets are deferred" in p for p in evidence.row_problems(gold(nuggets=nuggets)))
    assert any("nuggets are deferred" in p for p in evidence.row_problems(uncovered(nuggets=nuggets)))


def test_an_uncovered_row_carries_no_answer_or_evidence() -> None:
    problems = evidence.row_problems(uncovered(answer="a"))
    assert any("answer" in p and "uncovered" in p for p in problems)
    assert evidence.row_problems(uncovered()) == []


def test_a_near_miss_row_needs_distractors() -> None:
    row = gold(metadata={"category": "near_miss", "difficulty": "hard"})
    assert any("distractors" in p for p in evidence.row_problems(row))
    row.outputs["distractors"] = [{"source": "jevharness-2026", "page": 8, "quote": "81.1% lower cost"}]
    assert evidence.row_problems(row) == []


def test_a_distractor_must_not_contain_a_gold_quote() -> None:
    row = gold(distractors=[{"source": "wikiskill-2026", "page": 6, "quote": "x " + QUOTE_A.upper() + " y"}])
    assert any("distractor" in p and "contains" in p for p in evidence.row_problems(row))


def test_a_distractor_sharing_a_chunk_with_the_rows_evidence_fails() -> None:
    evidence_chunks = [["jev:39"], ["jev:40", "jev:41"]]
    problems = evidence.distractor_overlaps(evidence_chunks, [["jev:43"], ["jev:41"], ["jev:40", "jev:41"]])
    assert problems == [
        "distractors[1] (chunks jev:41) shares a chunk with evidence[1] (chunks jev:40 jev:41)",
        "distractors[2] (chunks jev:40 jev:41) shares a chunk with evidence[1] (chunks jev:40 jev:41)",
    ]
    assert evidence.distractor_overlaps(evidence_chunks, [["jev:43"]]) == []
    assert evidence.distractor_overlaps([], [["jev:43"]]) == []  # an uncovered row has no evidence


def test_a_distractor_quote_over_200_characters_fails() -> None:
    row = gold(distractors=[{"source": "wikiskill-2026", "page": 6, "quote": "y" * 201}])
    assert any("distractor" in p and "200" in p for p in evidence.row_problems(row))


def test_unknown_category_type_and_difficulty_fail() -> None:
    assert any("category" in p for p in evidence.row_problems(gold(metadata={"category": "bogus"})))
    assert any("type" in p for p in evidence.row_problems(gold(metadata={"type": "bogus"})))
    assert any("difficulty" in p for p in evidence.row_problems(gold(metadata={"difficulty": "bogus"})))
    assert evidence.row_problems(gold(metadata={"type": "false_premise"})) == []


def test_difficulty_follows_category() -> None:
    multi = evidence.row_problems(gold(metadata={"category": "multi_hop", "difficulty": "medium"}))
    assert any("multi_hop" in p and "hard" in p for p in multi)
    timed = evidence.row_problems(gold(metadata={"category": "time_sensitive", "difficulty": "easy"}))
    assert any("time_sensitive" in p for p in timed)


def test_off_topic_rows_belong_to_the_topic_check() -> None:
    assert any("topic check" in p for p in evidence.row_problems(uncovered(off_topic=True)))
    assert any("topic check" in p for p in evidence.row_problems(gold(off_topic=False)))
    scope = evidence.row_problems(uncovered(metadata={"category": "out_of_scope", "difficulty": "easy"}))
    assert any("unknown category 'out_of_scope'" in p for p in scope)


def test_a_covered_gold_row_needs_evidence_and_answer() -> None:
    for field in ("evidence", "answer"):
        row = gold()
        del row.outputs[field]
        assert any(field in p for p in evidence.row_problems(row)), field


def test_the_mix_flags_too_many_single_hop_rows() -> None:
    mix = rows(
        ("single_hop", "easy"),
        ("single_hop", "medium"),
        ("single_hop", "hard"),
        ("multi_hop", "hard"),
        ("near_miss", "medium"),
    )
    assert any("single_hop" in p for p in evidence.mix_problems(mix))


def test_the_mix_flags_a_difficulty_under_20_percent() -> None:
    mix = rows(("single_hop", "medium"), ("multi_hop", "hard"), ("near_miss", "hard"), ("unanswerable", "medium"))
    assert any("easy" in p for p in evidence.mix_problems(mix))


def test_a_balanced_mix_and_non_gold_rows_pass() -> None:
    mix = rows(
        ("single_hop", "easy"),
        ("single_hop", "medium"),
        ("multi_hop", "hard"),
        ("near_miss", "hard"),
        ("unanswerable", "medium"),
    )
    plain = Example({"question": "q"}, {"covered": True})
    assert evidence.mix_problems([*mix, plain, plain]) == []
    assert evidence.mix_problems([]) == []


def test_word_overlap_counts_the_questions_content_words_found_in_the_quotes() -> None:
    assert evidence.word_overlap("What gets thrown away?", ["discards the candidate"]) == 0.0
    assert evidence.word_overlap("Which skills are retrieved?", ["Skills are retrieved"]) == 1.0
    assert evidence.word_overlap("What is it?", ["anything"]) == 0.0
    assert evidence.word_overlap("candidate skills", ["the candidate", "other"]) == 0.5

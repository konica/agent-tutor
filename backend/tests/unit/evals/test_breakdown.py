"""The gold-evidence breakdown by difficulty and category."""

from evals.breakdown import BreakdownRow, render, render_markdown, rows


def test_scores_group_into_means_per_difficulty_with_counts() -> None:
    labelled = {
        "evidence.cited_recall": [
            (1.0, {"difficulty": "hard"}),
            (0.0, {"difficulty": "hard"}),
            (1.0, {"difficulty": "easy"}),
        ]
    }
    assert rows(labelled) == [
        BreakdownRow("evidence.cited_recall", "difficulty", "easy", 1.0, 1),
        BreakdownRow("evidence.cited_recall", "difficulty", "hard", 0.5, 2),
    ]


def test_other_metrics_and_rows_without_the_dimension_are_ignored_and_none_counts_as_zero() -> None:
    labelled = {
        "search_step_ran": [(1.0, {"difficulty": "hard"})],
        "answer_correctness": [(None, {"category": "a"}), (1.0, {}), (1.0, {"category": "a"})],
    }
    assert rows(labelled) == [BreakdownRow("answer_correctness", "category", "a", 0.5, 2)]


def test_nothing_to_break_down_renders_empty() -> None:
    assert rows({}) == []
    assert render([]) == "" and render_markdown([]) == ""


def test_the_renderings_carry_the_heading_and_the_never_gates_note() -> None:
    found = [BreakdownRow("evidence.distractor_cited", "category", "x", 0.25, 4)]
    assert "### Gold evidence by difficulty and category" in render_markdown(found)
    assert "| evidence.distractor_cited | category | x | 0.250 | 4 |" in render_markdown(found)
    text = render(found)
    assert "Never gates" in text and "lower-is-better" in text and "0.250" in text

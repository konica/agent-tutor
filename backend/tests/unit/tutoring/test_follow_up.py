"""The follow-up search query (PRD §9.2 step 1): the previous question added to the current one, in code."""

from smart_tutor.knowledge.application import MAX_QUERY_CHARS
from smart_tutor.tutoring.application import HistoryTurn, search_query


def test_a_new_conversation_searches_the_question_alone() -> None:
    assert search_query("What is attention?", []) == "What is attention?"


def test_a_follow_up_adds_the_previous_question() -> None:
    history = [HistoryTurn("What is a CNN?", "…"), HistoryTurn("Explain the transformer architecture", "…")]
    query = search_query("What are its limitations?", history)
    assert query == "Explain the transformer architecture\nWhat are its limitations?"


def test_a_declined_previous_turn_still_adds_its_question() -> None:
    history = [HistoryTurn("Explain the transformer architecture", "These documents don't cover this.")]
    assert search_query("And its limits?", history).startswith("Explain the transformer architecture")


def test_two_long_questions_stay_within_the_search_limit_keeping_the_current_one_whole() -> None:
    current = "c" * 3000
    query = search_query(current, [HistoryTurn("p" * 3000, "a")])
    assert len(query) <= MAX_QUERY_CHARS
    assert query.endswith(current) and query.startswith("p")


def test_a_question_at_the_limit_searches_alone() -> None:
    current = "c" * MAX_QUERY_CHARS
    assert search_query(current, [HistoryTurn("previous", "a")]) == current

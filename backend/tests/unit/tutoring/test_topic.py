"""The topic check's domain (spec 2026-10-13 §5.1–5.2): the verdict's threshold rule and the texts a classifier
scores."""

from smart_tutor.tutoring.application import HistoryTurn, TopicVerdict, previous_question, topic_texts


def test_a_verdict_at_or_above_the_threshold_is_off_topic() -> None:
    assert TopicVerdict(0.5, "m").is_off_topic(0.5)
    assert TopicVerdict(0.9, "m").is_off_topic(0.5)
    assert not TopicVerdict(0.49, "m").is_off_topic(0.5)


def test_a_first_question_is_scored_alone() -> None:
    assert topic_texts("Explain photosynthesis") == ["Explain photosynthesis"]


def test_a_later_question_is_also_scored_with_the_previous_question() -> None:
    assert topic_texts("Explain that more simply.", "What is gradient descent?") == [
        "Explain that more simply.",
        "Previous question: What is gradient descent?\nQuestion: Explain that more simply.",
    ]


def test_the_previous_question_is_the_last_turns() -> None:
    assert previous_question([]) is None
    history = [HistoryTurn("First?", "a"), HistoryTurn("Second?", "b")]
    assert previous_question(history) == "Second?"

"""Training data for the topic-check model (spec 2026-10-13 §6.2): pure helpers, no torch."""

from pathlib import Path

from evals.dataset import Example, in_eval_share
from evals.topic_check.data import (
    Labeled,
    holdout,
    labeled,
    pick_threshold,
    publish_model,
    rates,
    split_train_eval,
    training_rows,
)


def test_an_example_becomes_a_labeled_message_with_its_previous_question() -> None:
    example = Example(
        {"question": "Why?", "history": [{"question": "What is X?", "answer": ""}]},
        {"off_topic": False, "kind": "follow_up"},
    )
    row = labeled(example)
    assert row == Labeled("Why?", "What is X?", False)
    assert row.texts == ["Why?", "Previous question: What is X?\nQuestion: Why?"]


def test_the_held_out_share_evaluates_and_hand_written_questions_never_train() -> None:
    rows = [Labeled(f"question {i}", None, i % 2 == 0) for i in range(200)] + [Labeled("Hand  WRITTEN", None, True)]
    train, evaluation = split_train_eval(rows, ["hand written"], 0.3)
    assert {r.question for r in evaluation} == {r.question for r in rows if in_eval_share(r.question, 0.3)}
    assert not {r.question for r in train} & {r.question for r in evaluation}
    assert "Hand  WRITTEN" not in {r.question for r in train}


def test_each_message_trains_alone_and_with_its_previous_question() -> None:
    texts, labels = training_rows([Labeled("Why?", "What is X?", False), Labeled("Joke!", None, True)])
    assert texts == ["Why?", "Previous question: What is X?\nQuestion: Why?", "Joke!"]
    assert labels == [0, 0, 1]


def test_holdout_is_seeded_and_disjoint() -> None:
    rows = [Labeled(f"q{i}", None, False) for i in range(100)]
    fit, held = holdout(rows, 0.15, seed=7)
    assert len(held) == 15 and len(fit) == 85 and not set(fit) & set(held)
    assert holdout(rows, 0.15, seed=7) == (fit, held)


def test_the_threshold_is_the_lowest_that_keeps_false_rejections_at_most_half_a_percent() -> None:
    on = [(0.1, False)] * 199 + [(0.62, False)]  # one on-topic message at 0.62 = 0.5% of 200
    off = [(0.9, True)] * 50
    assert pick_threshold(on + off) == 0.5  # 1/200 = 0.005 is allowed
    stricter = [(0.1, False)] * 99 + [(0.62, False)]  # 1/100 = 1% is not
    assert pick_threshold(stricter + off) == 0.63


def test_no_threshold_meeting_the_target_gives_0_99() -> None:
    assert pick_threshold([(0.995, False), (0.1, False)]) == 0.99


def test_rates_count_false_rejections_and_caught() -> None:
    scored = [(0.7, False), (0.2, False), (0.9, True), (0.4, True)]
    assert rates(scored, 0.5) == (0.5, 0.5)


def test_publishing_a_model_replaces_its_files_and_leaves_other_files_alone(tmp_path: Path) -> None:
    source, out = tmp_path / "checked", tmp_path / "models" / "topic_check"
    source.mkdir()
    (source / "manifest.json").write_text("new", encoding="utf-8")
    (source / "body.onnx").write_bytes(b"new body")
    out.mkdir(parents=True)
    (out / "manifest.json").write_text("old", encoding="utf-8")
    (out / "README.md").write_text("kept", encoding="utf-8")
    publish_model(source, out)
    assert (out / "manifest.json").read_text(encoding="utf-8") == "new"
    assert (out / "body.onnx").read_bytes() == b"new body"
    assert (out / "README.md").read_text(encoding="utf-8") == "kept"


def test_publishing_creates_the_output_folder(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "head.npz").write_bytes(b"h")
    publish_model(tmp_path / "src", tmp_path / "a" / "b")
    assert (tmp_path / "a" / "b" / "head.npz").read_bytes() == b"h"

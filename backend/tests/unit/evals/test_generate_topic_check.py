"""Generated topic_check candidates (spec 2026-10-13 §6.1): every kind, labeled by its kind, follow-ups with history."""

from collections import Counter

import pytest
from langchain_core.messages import AIMessage

from evals.generate import main
from evals.generators.topic_check import KINDS, Kind, message_writer, write_candidates
from fakes import fake_chat_model
from fakes.langsmith import FakeLangSmith


async def write(kind: str, spec: Kind, count: int) -> list[str]:
    if kind == "follow_up":
        return [f"Earlier {i}? || Why {i}?" for i in range(count)]
    return [f"{kind} message {i}" for i in range(count)]


async def test_every_kind_becomes_candidates_labeled_by_its_kind() -> None:
    candidates = await write_candidates(2, write)
    assert Counter(c.type for c in candidates) == {kind: 2 for kind in KINDS}
    for c in candidates:
        assert c.expected == {"off_topic": KINDS[c.type].off_topic, "kind": c.type}
    follow_up = next(c for c in candidates if c.type == "follow_up")
    assert follow_up.inputs == {"question": "Why 0?", "history": [{"question": "Earlier 0?", "answer": ""}]}


def test_the_kinds_cover_both_sides_of_the_policy() -> None:
    assert {k for k, v in KINDS.items() if not v.off_topic} == {
        "subject_concept",
        "document_question",
        "follow_up",
        "study_task",
    }
    assert {k for k, v in KINDS.items() if v.off_topic} == {
        "greeting",
        "entertainment",
        "personal_task",
        "live_information",
    }


async def test_a_kind_whose_writing_fails_is_dropped_not_the_batch() -> None:
    async def flaky(kind: str, spec: Kind, count: int) -> list[str]:
        if kind == "greeting":
            raise RuntimeError("throttled")
        return await write(kind, spec, count)

    candidates = await write_candidates(1, flaky)
    assert "greeting" not in {c.type for c in candidates} and len(candidates) == len(KINDS) - 1


async def test_blank_duplicate_and_malformed_follow_up_lines_are_dropped() -> None:
    async def messy(kind: str, spec: Kind, count: int) -> list[str]:
        return ["no separator", " || empty earlier"] if kind == "follow_up" else ["a", "a", "  "]

    candidates = await write_candidates(3, messy)
    assert "follow_up" not in {c.type for c in candidates}
    assert all(c.inputs == {"question": "a"} for c in candidates)


async def test_the_writer_reads_one_message_per_line_without_numbering() -> None:
    writer = message_writer(fake_chat_model(AIMessage("1. hi there\n2) hello\n- yo\n\n")))
    assert await writer("greeting", KINDS["greeting"], 3) == ["hi there", "hello", "yo"]


def test_generate_queues_topic_check_candidates(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeLangSmith()
    assert main(["topic_check", "--per-type", "1"], client=client, write_topic=write, model_id="m") == 0
    [queue] = client.queues.values()
    assert len(queue.run_ids) == len(KINDS)
    assert f"{len(KINDS)} candidates" in capsys.readouterr().out

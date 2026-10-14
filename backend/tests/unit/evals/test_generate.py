"""make evals-generate: seed chunks → drafts → judge-written questions → the annotation queue."""

from collections.abc import Sequence

import pytest

from evals.chunks import SeedChunk
from evals.generate import main
from evals.langfuse_client import KEYS, LangfuseError
from fakes.langfuse import FakeLangfuse

TEXT = "Agents interleave reasoning traces with actions so that plans can be revised. " * 8
HOLDINGS = {"learner@example.com": ["react-2022", "cot-2022"], "learner2@example.com": ["self-rag-2023"]}
SEEDS = ["react-2022", "cot-2022", "self-rag-2023"]
CHUNKS = {s: [SeedChunk(f"{s}:{i}", s, i, 1, TEXT) for i in range(4)] for s in SEEDS}


async def asks(kind: str, passages: Sequence[SeedChunk]) -> str | None:
    return f"{kind} about {passages[0].id}?"


def test_candidates_of_every_type_reach_the_queue(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeLangfuse()
    code = main(
        ["ask", "--per-type", "2", "--seed", "3"],
        client=client,
        chunks=CHUNKS,
        holdings=HOLDINGS,
        write=asks,
        model_id="qwen.qwen3-32b-v1:0",
    )
    assert code == 0
    [queue] = client.queues.values()
    assert queue.name == "smart-tutor-ask-candidates" and len(queue.trace_ids) == 16
    traces = [client.traces_by_id[i] for i in queue.trace_ids]
    assert all(t.metadata["generator_model"] == "qwen.qwen3-32b-v1:0" for t in traces)
    assert len({t.metadata["batch"] for t in traces}) == 1
    out = capsys.readouterr().out
    assert "16 candidates" in out and "smart-tutor-ask-candidates" in out and "Review them in Langfuse" in out


def test_no_candidate_written_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    async def nothing(kind: str, passages: Sequence[SeedChunk]) -> str | None:
        return None

    client = FakeLangfuse()
    code = main(["ask"], client=client, chunks=CHUNKS, holdings=HOLDINGS, write=nothing, model_id="m")
    assert code == 1 and client.queues == {}
    assert "no candidate" in capsys.readouterr().err.lower()


def test_a_langfuse_error_exits_1_with_a_hint(capsys: pytest.CaptureFixture[str]) -> None:
    class NoKey(FakeLangfuse):
        def queue_id(self, name: str) -> str | None:
            raise LangfuseError("401: Invalid credentials")

    code = main(["ask"], client=NoKey(), chunks=CHUNKS, holdings=HOLDINGS, write=asks, model_id="m")
    err = capsys.readouterr().err
    assert code == 1 and "Can't reach Langfuse: 401" in err and all(key in err for key in KEYS)


def test_missing_langfuse_keys_stop_before_the_judge_writes_anything(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    written: list[str] = []

    async def counted(kind: str, passages: Sequence[SeedChunk]) -> str | None:
        written.append(kind)
        return None

    code = main(["ask"], chunks=CHUNKS, holdings=HOLDINGS, write=counted, model_id="m")
    assert code == 1 and written == [] and "LANGFUSE_PUBLIC_KEY" in capsys.readouterr().err

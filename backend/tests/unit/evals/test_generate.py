"""make evals-generate: seed chunks → drafts → judge-written questions → the annotation queue."""

from collections.abc import Sequence

import pytest
from langsmith.utils import LangSmithError

from evals.chunks import SeedChunk
from evals.generate import main
from fakes.langsmith import FakeLangSmith

TEXT = "Agents interleave reasoning traces with actions so that plans can be revised. " * 8
HOLDINGS = {"learner@example.com": ["react-2022", "cot-2022"], "learner2@example.com": ["self-rag-2023"]}
SEEDS = ["react-2022", "cot-2022", "self-rag-2023"]
CHUNKS = {s: [SeedChunk(f"{s}:{i}", s, i, 1, TEXT) for i in range(4)] for s in SEEDS}


async def asks(kind: str, passages: Sequence[SeedChunk]) -> str | None:
    return f"{kind} about {passages[0].id}?"


def test_candidates_of_every_type_reach_the_queue(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeLangSmith()
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
    assert len(queue.run_ids) == 16
    runs = [client.runs[i] for i in queue.run_ids]
    assert all(r.extra["metadata"]["generator_model"] == "qwen.qwen3-32b-v1:0" for r in runs)
    assert len({r.extra["metadata"]["batch"] for r in runs}) == 1
    assert "16 candidates" in capsys.readouterr().out


def test_no_candidate_written_exits_1(capsys: pytest.CaptureFixture[str]) -> None:
    async def nothing(kind: str, passages: Sequence[SeedChunk]) -> str | None:
        return None

    client = FakeLangSmith()
    code = main(["ask"], client=client, chunks=CHUNKS, holdings=HOLDINGS, write=nothing, model_id="m")
    assert code == 1 and client.queues == {}
    assert "no candidate" in capsys.readouterr().err.lower()


def test_a_langsmith_error_exits_1_with_a_hint(capsys: pytest.CaptureFixture[str]) -> None:
    class NoKey(FakeLangSmith):
        def list_annotation_queues(self, **kwargs: object) -> object:
            raise LangSmithError("Authentication failed")

    code = main(["ask"], client=NoKey(), chunks=CHUNKS, holdings=HOLDINGS, write=asks, model_id="m")
    assert code == 1 and "LANGSMITH_API_KEY" in capsys.readouterr().err

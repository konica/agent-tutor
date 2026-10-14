"""`python -m evals.topic_check.train --dry-run` (spec 2026-10-13 §6.2, #319): the candidates a reviewer accepted in
the Langfuse queue are counted in their share, before anything is published or trained."""

import pytest

from evals.dataset import in_eval_share, load_dataset
from evals.generate import main as generate
from evals.generators.topic_check import KINDS, Kind
from evals.langfuse_client import LangfuseError
from evals.review import ACCEPTED
from evals.topic_check.train import main as train
from fakes.langfuse import FakeLangfuse


async def write(kind: str, spec: Kind, count: int) -> list[str]:
    if kind == "follow_up":
        return [f"Earlier {i}? || Why {i}?" for i in range(count)]
    return [f"{kind} message {i}" for i in range(count)]


def _counts(name: str, off_topic: list[bool]) -> str:
    return f"{name}: {off_topic.count(False)} on-topic, {off_topic.count(True)} off-topic"


def test_accepted_candidates_are_counted_in_the_training_or_eval_share(capsys: pytest.CaptureFixture[str]) -> None:
    client = FakeLangfuse()
    assert generate(["topic_check", "--per-type", "10"], client=client, write_topic=write, model_id="m") == 0
    [queue] = client.queues.values()
    traces = [client.traces_by_id[i] for i in queue.trace_ids]
    accepted = traces[::2]
    for trace in accepted:
        client.score(trace.id, ACCEPTED, 1)
    for trace in traces[1::2][:5]:
        client.score(trace.id, ACCEPTED, 0)  # rejected; the rest are not reviewed yet
    capsys.readouterr()

    assert train(["--dry-run"], client=client) == 0

    dataset = load_dataset("topic_check")
    assert dataset.eval_share is not None
    held_out = [in_eval_share(t.input["question"], dataset.eval_share) for t in accepted]
    labels = [bool(t.output["expected"]["off_topic"]) for t in accepted]
    training = [label for label, out in zip(labels, held_out, strict=True) if not out]
    evaluation = [label for label, out in zip(labels, held_out, strict=True) if out]
    evaluation += [bool(e.outputs["off_topic"]) for e in dataset.examples]
    assert 0 < len(training) < len(accepted) and len(KINDS) * 10 == len(traces)
    out = capsys.readouterr().out.splitlines()
    assert out == [_counts("train", training), _counts("eval", evaluation)]
    assert not client.datasets  # a dry run publishes nothing


def test_a_langfuse_error_exits_1_with_a_hint(capsys: pytest.CaptureFixture[str]) -> None:
    class Off(FakeLangfuse):
        def dataset_names(self) -> list[str]:
            raise LangfuseError("[Errno 111] Connection refused")

    assert train(["--dry-run"], client=Off()) == 1
    assert "Can't reach Langfuse" in capsys.readouterr().err

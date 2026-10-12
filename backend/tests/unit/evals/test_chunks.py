"""Seed chunks: the worker's chunks of a seed PDF, numbered as the worker numbers them (chunks.seq)."""

from evals.chunks import chunks_of_pdf
from evals.highlight_fixture import chunks_of
from fakes.pdfs import make_pdf


def test_seed_chunks_are_the_workers_chunks_numbered_from_0_with_stable_ids() -> None:
    data = make_pdf(["First page. " * 120, "", "Third page. " * 30])
    chunks = chunks_of_pdf("react-2022", data)
    worker = chunks_of(data, 500)
    assert [c.text for c in chunks] == [w["text"] for w in worker]
    assert [c.seq for c in chunks] == list(range(len(worker)))
    assert chunks[0].id == "react-2022:0" and chunks[-1].page == 3

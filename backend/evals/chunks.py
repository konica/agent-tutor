"""Seed-corpus chunks as the worker makes them (PRD §9.2 step 6), with stable ids `<seed id>:<seq>`: `seq` is the
chunk's position in the whole PDF, the worker's `chunks.seq`, so an id names the same passage in every learner's copy.
Needs the ingest extra (pypdf, the text splitter)."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from evals.highlight_fixture import MAX_PAGES, chunks_of


@dataclass(frozen=True)
class SeedChunk:
    id: str
    seed_id: str
    seq: int
    page: int
    text: str


def chunks_of_pdf(seed_id: str, data: bytes) -> list[SeedChunk]:
    return [
        SeedChunk(f"{seed_id}:{seq}", seed_id, seq, piece["page"], piece["text"])
        for seq, piece in enumerate(chunks_of(data, MAX_PAGES))
    ]


def seed_chunks(paths: Mapping[str, Path]) -> dict[str, list[SeedChunk]]:
    """Each seed document's chunks, by seed id, from its downloaded PDF (evals.corpus.download)."""
    return {seed_id: chunks_of_pdf(seed_id, path.read_bytes()) for seed_id, path in paths.items()}

"""Chunks of seed-corpus PDFs, as the worker makes them, for the viewer's highlight test (PRD §10.1).

Usage: uv run --extra ingest python -m evals.highlight_fixture --pages 6 --out chunks.json data/seed_corpus/*.pdf
Writes {"<file stem>": [{"page", "start_index", "text"}, ...]} for the first --pages pages of each PDF.
"""

import argparse
import json
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from smart_tutor.knowledge.adapters.chunking import build_chunker
from smart_tutor.knowledge.adapters.pypdf_extractor import PypdfExtractor
from smart_tutor.knowledge.domain.chunk import start_index_of
from smart_tutor.shared.config import ChunkingConfig

MAX_PAGES = 500  # the worker's page limit (FileLimits default)


def chunks_of(data: bytes, pages: int) -> list[dict[str, Any]]:
    """The worker's chunks of the first `pages` pages: same extractor, same non-blank pages, same chunker."""
    texts = PypdfExtractor().extract_pages(data, MAX_PAGES, first=pages)
    sources = [
        Document(page_content=text, metadata={"page": number})
        for number, text in enumerate(texts, start=1)
        if text.strip()
    ]
    chunker, _ = build_chunker(ChunkingConfig())
    return [
        {
            "page": piece.metadata["page"],
            "start_index": start_index_of(piece.metadata.get("start_index")),
            "text": piece.page_content,
        }
        for piece in chunker.transform_documents(sources)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pages", type=int, default=6)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("pdfs", type=Path, nargs="+")
    args = parser.parse_args()
    fixture = {pdf.stem: chunks_of(pdf.read_bytes(), args.pages) for pdf in args.pdfs}
    with args.out.open("w", encoding="utf-8") as out:
        json.dump(fixture, out, ensure_ascii=False, indent=None)


if __name__ == "__main__":
    main()

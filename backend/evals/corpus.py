"""The seed corpus (PRD §10.3): the documents in seed_corpus/manifest.yaml, downloaded into data/seed_corpus/.

Usage: uv run --extra eval python -m evals.corpus [--dest ../data/seed_corpus]
Fetches each PDF that is missing or changed and refuses bytes whose SHA-256 differs from the manifest's.
"""

import argparse
import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

MANIFEST = Path(__file__).parent / "seed_corpus" / "manifest.yaml"
DOWNLOADS = Path(__file__).parents[2] / "data" / "seed_corpus"  # <repo>/data is git-ignored
FETCH_TIMEOUT = 60


class CorpusError(Exception):
    """A seed document can't be used: an unknown source, or bytes that don't match the manifest."""


@dataclass(frozen=True)
class SeedDocument:
    id: str
    url: str
    sha256: str
    subjects: tuple[str, ...]  # the labeled subjects, chosen for it when it is loaded into a library
    file_name: str  # the file's name in data/seed_corpus/ and the name it is uploaded under


def _seed(entry: dict[str, Any]) -> SeedDocument:
    source = entry["source"]
    if source["type"] == "arxiv":
        url, file_name = f"https://arxiv.org/pdf/{source['ref']}", f"{source['ref']}.pdf"
    elif source["type"] == "url":
        url, file_name = source["ref"], f"{entry['id']}.pdf"
    else:
        raise CorpusError(f"{entry['id']}: unknown source type {source['type']!r}")
    return SeedDocument(entry["id"], url, entry["sha256"], tuple(entry["subjects"]), file_name)


def load_manifest(path: Path = MANIFEST) -> dict[str, SeedDocument]:
    """The manifest's documents by id."""
    entries = yaml.safe_load(path.read_text(encoding="utf-8"))["documents"]
    return {e["id"]: _seed(e) for e in entries}


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fetch_url(url: str) -> bytes:
    response = httpx.get(url, follow_redirects=True, timeout=FETCH_TIMEOUT)
    response.raise_for_status()
    return response.content


def download(
    documents: Iterable[SeedDocument], dest: Path = DOWNLOADS, fetch: Callable[[str], bytes] = fetch_url
) -> dict[str, Path]:
    """Each document's verified PDF in `dest`, by id; fetched only when missing or changed."""
    dest.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for seed in documents:
        path = dest / seed.file_name
        if not path.exists() or sha256_of(path.read_bytes()) != seed.sha256:
            data = fetch(seed.url)
            if sha256_of(data) != seed.sha256:
                raise CorpusError(
                    f"{seed.id}: {seed.url} has SHA-256 {sha256_of(data)}, the manifest says {seed.sha256}"
                )
            path.write_bytes(data)
        paths[seed.id] = path
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=DOWNLOADS)
    args = parser.parse_args()
    for seed_id, path in download(load_manifest().values(), args.dest).items():
        print(f"{seed_id}: {path}")


if __name__ == "__main__":
    main()

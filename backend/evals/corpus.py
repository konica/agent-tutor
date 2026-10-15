"""The seed corpus (PRD §10.3): the documents in seed_corpus/manifest.yaml, downloaded into data/seed_corpus/.

Usage: uv run --extra eval --extra ingest python -m evals.corpus [--dest ../data/seed_corpus]
Fetches each PDF that is missing or changed (a generated one is rendered from its text, evals.pdf) and refuses bytes
whose SHA-256 differs from the manifest's. An adversarial document (#196) is built from its base seed by
evals.adversarial_pdfs and verified the same way.
"""

import argparse
import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import yaml

from evals.pdf import text_pdf

MANIFEST = Path(__file__).parent / "seed_corpus" / "manifest.yaml"
GENERATED = Path(__file__).parent / "seed_corpus" / "generated"
DOWNLOADS = Path(__file__).parents[2] / "data" / "seed_corpus"  # <repo>/data is git-ignored
FETCH_TIMEOUT = 60


class CorpusError(Exception):
    """A seed document can't be used: an unknown source, or bytes that don't match the manifest."""


@dataclass(frozen=True)
class SeedDocument:
    id: str
    url: str | None  # None for a generated document
    sha256: str
    subjects: tuple[str, ...]  # the labeled subjects, chosen for it when it is loaded into a library
    file_name: str  # the file's name in data/seed_corpus/ and the name it is uploaded under
    generated: Path | None = None  # the text a generated document is rendered from (evals.pdf)
    canary: str | None = None  # a string only this document holds: it must never reach another learner (#194)
    base: str | None = None  # an adversarial derivative (#196): built from the base seed by evals.adversarial_pdfs
    plant: str | None = None  # which placement or trick the derivative plants
    adversarial: bool = False
    injection_eval: bool = False  # belongs to the injection eval: the ask generator leaves it out


def _seed(entry: dict[str, Any]) -> SeedDocument:
    source = entry["source"]
    generated = base = plant = None
    if source["type"] == "arxiv":
        url, file_name = f"https://arxiv.org/pdf/{source['ref']}", f"{source['ref']}.pdf"
    elif source["type"] == "url":
        url, file_name = source["ref"], f"{entry['id']}.pdf"
    elif source["type"] == "generated":
        url, file_name, generated = None, f"{entry['id']}.pdf", GENERATED / source["ref"]
    elif source["type"] == "adversarial":
        url, file_name, base, plant = None, f"{entry['id']}.pdf", source["base"], source["plant"]
    else:
        raise CorpusError(f"{entry['id']}: unknown source type {source['type']!r}")
    return SeedDocument(
        entry["id"],
        url,
        entry["sha256"],
        tuple(entry["subjects"]),
        file_name,
        generated=generated,
        canary=entry.get("canary"),
        base=base,
        plant=plant,
        adversarial=bool(entry.get("adversarial", False)),
        injection_eval=bool(entry.get("injection_eval", False)),
    )


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
    documents: Iterable[SeedDocument],
    dest: Path = DOWNLOADS,
    fetch: Callable[[str], bytes] = fetch_url,
    *,
    manifest: Mapping[str, SeedDocument] | None = None,
    spec: Mapping[str, Any] | None = None,
) -> dict[str, Path]:
    """Each document's verified PDF in `dest`, by id; fetched only when missing or changed. An adversarial document
    downloads its base (looked up in `manifest`) and is built with `spec` (the taxonomy's document category)."""
    dest.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}
    for seed in documents:
        path = dest / seed.file_name
        if not path.exists() or sha256_of(path.read_bytes()) != seed.sha256:
            if seed.base is not None:
                from evals.adversarial_pdfs import build_adversarial, document_spec  # needs the ingest extra

                seeds = manifest if manifest is not None else load_manifest()
                base_path = download([seeds[seed.base]], dest, fetch, manifest=seeds)[seed.base]
                assert seed.plant is not None
                data = build_adversarial(
                    base_path.read_bytes(), seed.plant, spec if spec is not None else document_spec()
                )
            elif seed.generated is not None:
                data = text_pdf(seed.generated.read_text(encoding="utf-8"))
            else:
                assert seed.url is not None
                data = fetch(seed.url)
            if sha256_of(data) != seed.sha256:
                if seed.base is not None:
                    raise CorpusError(
                        f"{seed.id}: built from {seed.base} it has SHA-256 {sha256_of(data)}, the manifest says "
                        f"{seed.sha256}; after changing the seeds or pypdf, print the new hashes with "
                        "python -m evals.adversarial_pdfs"
                    )
                origin = seed.url or seed.generated
                raise CorpusError(f"{seed.id}: {origin} has SHA-256 {sha256_of(data)}, the manifest says {seed.sha256}")
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

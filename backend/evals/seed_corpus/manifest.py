"""Load the seed corpus manifest (schema in `manifest.yaml`'s header)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = Path(__file__).resolve().parent / "manifest.yaml"
PDF_DIR = REPO_ROOT / "data" / "seed_corpus"


@dataclass(frozen=True)
class SeedDocument:
    id: str
    source_type: str
    source_ref: str
    license: str
    sha256: str
    subjects: tuple[str, ...]
    title: str

    @property
    def url(self) -> str:
        if self.source_type == "arxiv":
            return f"https://arxiv.org/pdf/{self.source_ref}"
        return self.source_ref

    def pdf_path(self, pdf_dir: Path = PDF_DIR) -> Path:
        return pdf_dir / f"{self.id}.pdf"


def _parse(entry: dict[str, Any]) -> SeedDocument:
    subjects = tuple(entry["subjects"])
    if not 1 <= len(subjects) <= 3:
        raise ValueError(f"{entry['id']}: needs 1-3 subjects, got {len(subjects)}")
    return SeedDocument(
        id=entry["id"],
        source_type=entry["source"]["type"],
        source_ref=entry["source"]["ref"],
        license=entry["license"],
        sha256=entry["sha256"],
        subjects=subjects,
        title=entry["metadata"]["title"],
    )


def load_manifest(path: Path = MANIFEST_PATH) -> list[SeedDocument]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    docs = [_parse(entry) for entry in data.get("documents") or []]
    seen: set[str] = set()
    for doc in docs:
        if doc.id in seen:
            raise ValueError(f"duplicate document id: {doc.id}")
        seen.add(doc.id)
    return docs

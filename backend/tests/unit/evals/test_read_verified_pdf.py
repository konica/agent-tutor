import hashlib
from pathlib import Path

import pytest

from evals.seed_corpus.manifest import SeedDocument
from evals.targets import read_verified_pdf

PDF = b"%PDF-1.7 complete bytes"


def _doc() -> SeedDocument:
    return SeedDocument("doc-a", "arxiv", "1", "CC-BY-4.0", hashlib.sha256(PDF).hexdigest(), ("A",), "Title")


def test_returns_bytes_that_match_the_manifest(tmp_path: Path) -> None:
    (tmp_path / "doc-a.pdf").write_bytes(PDF)
    assert read_verified_pdf(_doc(), tmp_path) == PDF


def test_truncated_pdf_names_the_document_and_the_fix(tmp_path: Path) -> None:
    (tmp_path / "doc-a.pdf").write_bytes(PDF[:10])
    with pytest.raises(ValueError, match=r"doc-a.*re-run.*seed_corpus\.download"):
        read_verified_pdf(_doc(), tmp_path)

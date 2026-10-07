import hashlib
from pathlib import Path

import pytest

from evals.seed_corpus.download import ChecksumError, download_all
from evals.seed_corpus.manifest import SeedDocument, load_manifest

PDF = b"%PDF-1.7 fake bytes"
PDF_SHA = hashlib.sha256(PDF).hexdigest()


def _entry(id_: str, subjects: str = '["A"]', sha: str = PDF_SHA) -> str:
    return (
        f"  - id: {id_}\n"
        '    source: {type: arxiv, ref: "1706.03762v7"}\n'
        '    license: "CC-BY-4.0"\n'
        f'    sha256: "{sha}"\n'
        f"    subjects: {subjects}\n"
        '    metadata: {title: "Title"}\n'
    )


def _write(tmp_path: Path, *entries: str) -> Path:
    path = tmp_path / "manifest.yaml"
    path.write_text("documents:\n" + "".join(entries), encoding="utf-8")
    return path


def _doc(id_: str = "d1", sha: str = PDF_SHA) -> SeedDocument:
    return SeedDocument(id_, "url", "https://example.org/x.pdf", "CC-BY-4.0", sha, ("A",), "T")


def test_loads_fields(tmp_path: Path) -> None:
    [doc] = load_manifest(_write(tmp_path, _entry("attn", '["A", "B"]')))
    assert doc.id == "attn"
    assert doc.source_type == "arxiv"
    assert doc.source_ref == "1706.03762v7"
    assert doc.license == "CC-BY-4.0"
    assert doc.sha256 == PDF_SHA
    assert doc.subjects == ("A", "B")
    assert doc.title == "Title"
    assert doc.url == "https://arxiv.org/pdf/1706.03762v7"
    assert doc.pdf_path(tmp_path) == tmp_path / "attn.pdf"


def test_url_source_uses_ref() -> None:
    assert _doc().url == "https://example.org/x.pdf"


def test_rejects_duplicate_ids(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        load_manifest(_write(tmp_path, _entry("a"), _entry("a")))


@pytest.mark.parametrize("subjects", ['["A", "B", "C", "D"]', "[]"])
def test_rejects_bad_subject_count(tmp_path: Path, subjects: str) -> None:
    with pytest.raises(ValueError, match="subjects"):
        load_manifest(_write(tmp_path, _entry("a", subjects)))


def test_download_writes_verified_pdf(tmp_path: Path) -> None:
    fetched = download_all([_doc()], lambda url: PDF, tmp_path)
    assert fetched == ["d1"]
    assert (tmp_path / "d1.pdf").read_bytes() == PDF


def test_download_skips_existing_good_file(tmp_path: Path) -> None:
    (tmp_path / "d1.pdf").write_bytes(PDF)

    def fetch(url: str) -> bytes:
        raise AssertionError("must not fetch")

    assert download_all([_doc()], fetch, tmp_path) == []


def test_mismatch_raises_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(ChecksumError):
        download_all([_doc()], lambda url: b"tampered", tmp_path)
    assert list(tmp_path.glob("*.pdf")) == []


def test_refetches_corrupt_existing_file(tmp_path: Path) -> None:
    (tmp_path / "d1.pdf").write_bytes(b"corrupt")
    assert download_all([_doc()], lambda url: PDF, tmp_path) == ["d1"]
    assert (tmp_path / "d1.pdf").read_bytes() == PDF

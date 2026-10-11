"""The seed corpus: the manifest's documents and their verified download (PRD §10.3)."""

from pathlib import Path

import pytest

from evals.corpus import CorpusError, SeedDocument, download, load_manifest, sha256_of

PDF = b"%PDF-1.7 seed"


def _seed(data: bytes = PDF) -> SeedDocument:
    return SeedDocument(
        "react-2022", "https://arxiv.org/pdf/2210.03629v3", sha256_of(data), ("LLM agents",), "2210.03629v3.pdf"
    )


def test_the_manifest_lists_each_document_with_its_source_hash_and_subjects() -> None:
    seeds = load_manifest()
    react = seeds["react-2022"]
    assert react.url == "https://arxiv.org/pdf/2210.03629v3"
    assert react.file_name == "2210.03629v3.pdf"
    assert react.sha256 == "f285b0971ae4a790e402fb93966bed3adde2cf0a04977d08b2b40d6ab0cace69"
    assert react.subjects == ("LLM agents",)
    assert seeds["self-rag-2023"].subjects == ("Retrieval-augmented generation", "LLM agents")


def test_a_missing_pdf_is_downloaded_and_verified(tmp_path: Path) -> None:
    fetched: list[str] = []

    def fetch(url: str) -> bytes:
        fetched.append(url)
        return PDF

    paths = download([_seed()], tmp_path, fetch)
    assert fetched == ["https://arxiv.org/pdf/2210.03629v3"]
    assert paths == {"react-2022": tmp_path / "2210.03629v3.pdf"}
    assert paths["react-2022"].read_bytes() == PDF


def test_a_pdf_already_downloaded_is_not_fetched_again(tmp_path: Path) -> None:
    (tmp_path / "2210.03629v3.pdf").write_bytes(PDF)

    def fetch(url: str) -> bytes:
        raise AssertionError("fetched again")

    assert download([_seed()], tmp_path, fetch) == {"react-2022": tmp_path / "2210.03629v3.pdf"}


def test_a_changed_local_pdf_is_downloaded_again(tmp_path: Path) -> None:
    (tmp_path / "2210.03629v3.pdf").write_bytes(b"truncated")
    download([_seed()], tmp_path, lambda url: PDF)
    assert (tmp_path / "2210.03629v3.pdf").read_bytes() == PDF


def test_a_download_with_the_wrong_hash_is_refused(tmp_path: Path) -> None:
    with pytest.raises(CorpusError, match="react-2022"):
        download([_seed()], tmp_path, lambda url: b"something else")
    assert not (tmp_path / "2210.03629v3.pdf").exists()

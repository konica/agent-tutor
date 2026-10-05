import pytest
from langchain_core.documents import Document

from smart_tutor.knowledge.adapters.chunking import build_chunker, clean_page_text
from smart_tutor.shared.config import ChunkingConfig


def test_clean_page_text_folds_ligatures_joins_hyphenation_and_drops_control_characters() -> None:
    assert clean_page_text("ﬁne exam-\nple\x07 A-\nB") == "fine example A-\nB"


def test_clean_page_text_keeps_tabs_and_newlines() -> None:
    assert clean_page_text("a\tb\nc") == "a\tb\nc"


def test_default_chunker_splits_a_page_and_keeps_its_metadata() -> None:
    chunker, chunker_id = build_chunker(ChunkingConfig())
    page = Document(page_content=" ".join(f"word{i}" for i in range(500)), metadata={"page": 7})
    assert len(page.page_content) > 2000

    chunks = chunker.transform_documents([page])

    assert len(chunks) > 1
    assert all(len(c.page_content) <= 1000 for c in chunks)
    assert all(c.metadata["page"] == 7 for c in chunks)
    assert chunker_id == "recursive_character:1000/200:v1"


def test_each_page_is_split_separately() -> None:
    chunker, _ = build_chunker(ChunkingConfig())
    docs = [
        Document(page_content="First page.", metadata={"page": 1}),
        Document(page_content="Second.", metadata={"page": 2}),
    ]

    chunks = chunker.transform_documents(docs)

    assert [(c.page_content, c.metadata["page"]) for c in chunks] == [("First page.", 1), ("Second.", 2)]


def test_chunker_cleans_text_before_splitting() -> None:
    chunker, _ = build_chunker(ChunkingConfig())

    chunks = chunker.transform_documents([Document(page_content="exam-\nple", metadata={"page": 1})])

    assert chunks[0].page_content == "example"


def test_params_set_the_size_and_the_id() -> None:
    chunker, chunker_id = build_chunker(ChunkingConfig(params={"chunk_size": 100, "chunk_overlap": 10}))
    chunks = chunker.transform_documents([Document(page_content="x " * 300, metadata={"page": 1})])

    assert chunker_id == "recursive_character:100/10:v1"
    assert all(len(c.page_content) <= 100 for c in chunks)


def test_unknown_method_raises() -> None:
    with pytest.raises(ValueError, match="semantic"):
        build_chunker(ChunkingConfig(method="semantic"))

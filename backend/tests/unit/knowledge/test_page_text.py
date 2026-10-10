from smart_tutor.knowledge.domain.chunk import start_index_of
from smart_tutor.knowledge.domain.page_text import clean_page_text, locate_chunks


def test_clean_page_text_is_the_chunking_cleanup() -> None:
    assert clean_page_text("ﬁne exam-\nple\x07 A-\nB") == "fine example A-\nB"


def test_locate_chunks_finds_each_chunk_in_order() -> None:
    page = "Alpha beta. Gamma delta. Alpha beta."
    assert locate_chunks(page, ["Alpha beta.", "Gamma delta.", "Alpha beta."]) == [0, 12, 25]


def test_locate_chunks_handles_overlapping_chunks() -> None:
    page = "one two three four five"
    assert locate_chunks(page, ["one two three", "three four five"]) == [0, 8]


def test_locate_chunks_leaves_a_missing_chunk_none_and_goes_on() -> None:
    page = "first part. second part."
    assert locate_chunks(page, ["first part.", "not here", "second part."]) == [0, None, 12]


def test_locate_chunks_falls_back_to_the_whole_page() -> None:
    # Out of order (shouldn't happen, but a chunk is still found rather than left None).
    assert locate_chunks("aaa bbb", ["bbb", "aaa"]) == [4, 0]


def test_start_index_of_keeps_only_a_non_negative_int() -> None:
    assert [start_index_of(v) for v in (0, 7, -1, None, True, "3", 2.0)] == [0, 7, None, None, None, None, None]

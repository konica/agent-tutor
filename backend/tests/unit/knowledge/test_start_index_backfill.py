import json
import logging

import pytest

from fakes import FakeObjectStore, InMemoryLibrary
from fakes.knowledge import fake_chunk_id
from smart_tutor.knowledge.application import BackfillResult, StartIndexBackfill
from smart_tutor.knowledge.domain.chunk import Chunk
from smart_tutor.knowledge.domain.content import Content, pages_key
from smart_tutor.shared.domain.ids import ContentId, UserId

OWNER = UserId("ada")
PAGE_ONE = "ﬁrst para-\ngraph. second"  # cleaned: "first paragraph. second"


class CountingObjectStore(FakeObjectStore):
    def __init__(self) -> None:
        super().__init__()
        self.reads: list[str] = []

    def read(self, key: str) -> bytes:
        self.reads.append(key)
        return super().read(key)


class World:
    def __init__(self) -> None:
        self.library, self.objects = InMemoryLibrary(), CountingObjectStore()
        self.backfill = StartIndexBackfill(self.library.unit_of_work, self.objects)

    def content(
        self, name: str, chunks: list[tuple[int | None, str, int | None]], pages: list[str] | None = None
    ) -> ContentId:
        """A ready content with chunks given as (page, text, start_index); `pages` is saved as its `.pages.json`."""
        content_id = ContentId(name)
        content = Content.first_upload(content_id, "0" * 64, 10, OWNER)
        text_key = pages_key(OWNER, content_id)
        content.ready(pages=1, text_key=text_key, chunker="c", embedding_model="m", embedding_dim=2)
        self.library.state.contents[content_id] = content
        self.library.state.chunks[content_id] = [
            Chunk(content_id, seq, page, text, [0.0, 0.0], start) for seq, (page, text, start) in enumerate(chunks)
        ]
        if pages is not None:
            listing = {"pages": [{"page": n, "text": t} for n, t in enumerate(pages, start=1)]}
            self.objects.objects[text_key] = json.dumps(listing).encode()
        return content_id

    def offsets(self, content_id: ContentId) -> list[int | None]:
        return [c.start_index for c in self.library.state.chunks[content_id]]


def test_existing_chunks_get_their_offsets_in_the_cleaned_page_text() -> None:
    w = World()
    cid = w.content("c1", [(1, "first paragraph.", None), (1, "second", None)], [PAGE_ONE])
    assert w.backfill.run() == BackfillResult(located=2, missing=0)
    assert w.offsets(cid) == [0, 17]


def test_a_chunk_not_on_its_page_stays_null_and_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    w = World()
    cid = w.content(
        "c1", [(1, "first paragraph.", None), (1, "nowhere to be found", None), (1, "second", None)], [PAGE_ONE]
    )
    with caplog.at_level(logging.WARNING):
        assert w.backfill.run() == BackfillResult(located=2, missing=1)
    assert w.offsets(cid) == [0, None, 17]
    [record] = caplog.records
    assert fake_chunk_id(cid, 1) in record.getMessage() and cid in record.getMessage()


def test_a_content_without_saved_page_text_stays_null_and_the_others_are_still_processed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    w = World()
    lost = w.content("a-lost", [(1, "first paragraph.", None), (1, "second", None)])
    kept = w.content("b-kept", [(1, "second", None)], [PAGE_ONE])
    with caplog.at_level(logging.WARNING):
        assert w.backfill.run() == BackfillResult(located=1, missing=2)
    assert w.offsets(lost) == [None, None]
    assert w.offsets(kept) == [17]
    assert any(lost in r.getMessage() for r in caplog.records)


def test_chunks_that_already_have_offsets_are_left_alone_and_their_content_is_not_read() -> None:
    w = World()
    done = w.content("a-done", [(1, "first paragraph.", 5), (1, "second", 9)], [PAGE_ONE])
    todo = w.content("b-todo", [(1, "second", None)], [PAGE_ONE])
    assert w.backfill.run() == BackfillResult(located=1, missing=0)
    assert w.offsets(done) == [5, 9]
    assert w.offsets(todo) == [17]
    assert w.objects.reads == [pages_key(OWNER, todo)]


def test_a_chunk_without_a_page_stays_null_and_counts_as_missing() -> None:
    w = World()
    cid = w.content("c1", [(None, "second", None), (1, "second", None)], [PAGE_ONE])
    assert w.backfill.run() == BackfillResult(located=1, missing=1)
    assert w.offsets(cid) == [None, 17]


def test_chunks_on_a_page_the_saved_text_lacks_stay_null() -> None:
    w = World()
    cid = w.content("c1", [(3, "second", None)], [PAGE_ONE])
    assert w.backfill.run() == BackfillResult(located=0, missing=1)
    assert w.offsets(cid) == [None]


def test_running_twice_changes_nothing_the_second_time() -> None:
    w = World()
    cid = w.content("c1", [(1, "first paragraph.", None), (1, "second", None)], [PAGE_ONE])
    w.backfill.run()
    commits, reads = w.library.commits, len(w.objects.reads)
    assert w.backfill.run() == BackfillResult(located=0, missing=0)
    assert w.offsets(cid) == [0, 17]
    assert (w.library.commits, len(w.objects.reads)) == (commits, reads)

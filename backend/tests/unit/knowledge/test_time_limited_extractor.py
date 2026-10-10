import errno
import multiprocessing
import time
from multiprocessing.connection import Connection
from multiprocessing.context import SpawnContext, SpawnProcess

import pytest

from fakes.extractors import (
    CrashingExtractor,
    PagesExtractor,
    SleepingExtractor,
    TooManyExtractor,
    UnreadableExtractor,
)
from fakes.pdfs import make_pdf
from smart_tutor.knowledge.adapters.pypdf_extractor import PypdfExtractor
from smart_tutor.knowledge.adapters.time_limited_extractor import TimeLimitedExtractor
from smart_tutor.knowledge.ports.pdf_extractor import ExtractionTimeoutError, TooManyPagesError, UnreadablePdfError


def test_returns_the_inner_extractors_pages() -> None:
    extractor = TimeLimitedExtractor(PagesExtractor(), timeout_seconds=30)
    assert extractor.extract_pages(b"first", max_pages=10) == ["first", "second"]


def test_too_many_pages_keeps_its_page_count() -> None:
    with pytest.raises(TooManyPagesError) as raised:
        TimeLimitedExtractor(TooManyExtractor(), timeout_seconds=30).extract_pages(b"x", max_pages=10)
    assert raised.value.pages == 600


def test_unreadable_pdf_passes_through() -> None:
    with pytest.raises(UnreadablePdfError, match="bad bytes"):
        TimeLimitedExtractor(UnreadableExtractor(), timeout_seconds=30).extract_pages(b"x", max_pages=10)


def test_a_slow_parse_is_killed_after_the_timeout() -> None:
    started = time.monotonic()
    with pytest.raises(ExtractionTimeoutError):
        TimeLimitedExtractor(SleepingExtractor(), timeout_seconds=1).extract_pages(b"x", max_pages=10)
    assert time.monotonic() - started < 10
    assert multiprocessing.active_children() == []


def test_a_parser_that_dies_is_unreadable() -> None:
    with pytest.raises(UnreadablePdfError, match="137"):
        TimeLimitedExtractor(CrashingExtractor(), timeout_seconds=30).extract_pages(b"x", max_pages=10)


def test_the_real_extractor_works_through_the_wrapper() -> None:
    extractor = TimeLimitedExtractor(PypdfExtractor(), timeout_seconds=30)
    assert extractor.extract_pages(make_pdf(["hello world"]), max_pages=10) == ["hello world"]


def test_a_child_that_cannot_start_leaks_no_pipe(monkeypatch: pytest.MonkeyPatch) -> None:
    # At the container's process limit, start() fails with EAGAIN; both pipe ends must still close.
    opened: list[Connection] = []
    real_pipe = SpawnContext.Pipe

    def pipe(self: SpawnContext, duplex: bool = True) -> tuple[Connection, Connection]:
        ends = real_pipe(self, duplex)
        opened.extend(ends)
        return ends

    def refuse(self: SpawnProcess) -> None:
        raise BlockingIOError(errno.EAGAIN, "Resource temporarily unavailable")

    monkeypatch.setattr(SpawnContext, "Pipe", pipe)
    monkeypatch.setattr(SpawnProcess, "start", refuse)

    with pytest.raises(BlockingIOError):
        TimeLimitedExtractor(PagesExtractor(), timeout_seconds=30).extract_pages(b"x", max_pages=10)
    assert len(opened) == 2
    assert all(end.closed for end in opened)

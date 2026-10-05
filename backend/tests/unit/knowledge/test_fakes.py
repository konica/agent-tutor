from datetime import UTC, datetime

import pytest

from fakes import InMemoryLibrary
from fakes.processing import FakePdfExtractor
from smart_tutor.knowledge.domain.upload import Upload
from smart_tutor.knowledge.ports.pdf_extractor import TooManyPagesError
from smart_tutor.shared.domain.ids import UploadId, UserId


def test_uncommitted_changes_are_discarded() -> None:
    library = InMemoryLibrary()
    with library.unit_of_work() as tx:
        tx.uploads.add(Upload(UploadId("u1"), UserId("ada"), datetime.now(UTC)))
    assert library.state.uploads == {}
    with library.unit_of_work() as tx:
        tx.uploads.add(Upload(UploadId("u1"), UserId("ada"), datetime.now(UTC)))
        tx.commit()
    assert set(library.state.uploads) == {"u1"}


def test_fake_extractor_first_reads_only_the_first_pages() -> None:
    data = b"%PDF-1.7 a\fb\fc"
    pages = FakePdfExtractor().extract_pages(data, 500, first=2)
    assert pages == ["a", "b"]


def test_fake_extractor_first_still_checks_the_page_limit() -> None:
    data = b"%PDF-1.7 a\fb\fc"
    with pytest.raises(TooManyPagesError):
        FakePdfExtractor().extract_pages(data, 2, first=1)

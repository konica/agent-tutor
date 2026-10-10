from datetime import UTC, datetime, timedelta

import pytest

from fakes import APP_TZ, TEST_LIMITS, TEST_UPLOAD_LIMITS, FakeObjectStore, FixedClock, InMemoryLibrary
from smart_tutor.accounts.application import LimitWindow, UploadLimitReachedError, UploadLimits
from smart_tutor.knowledge.application import FileLimits, InvalidFileNameError, UploadService
from smart_tutor.shared.domain.ids import UserId

UPLOAD = "b5f3c1a2-0d4e-4f6a-9b7c-1e2d3c4b5a69"
DOC = "0a1b2c3d-0000-4000-8000-000000000002"


def make(
    ids: list[str] | None = None, clock: FixedClock | None = None, rate: UploadLimits = TEST_UPLOAD_LIMITS
) -> tuple[UploadService, InMemoryLibrary, FakeObjectStore]:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    it = iter(ids or [UPLOAD, DOC])
    service = UploadService(
        library.unit_of_work,
        objects,
        clock or FixedClock(),
        TEST_LIMITS,
        rate=rate,
        time_zone=APP_TZ,
        new_id=lambda: next(it),
    )
    return service, library, objects


def counting() -> tuple[UploadService, InMemoryLibrary, FakeObjectStore, FixedClock]:
    """Fresh ids for every upload, a small limit (3 per hour, 5 per day), and a clock the test moves."""
    library, objects = InMemoryLibrary(), FakeObjectStore()
    clock = FixedClock(datetime(2026, 10, 10, 3, 0, tzinfo=UTC))
    service = UploadService(
        library.unit_of_work, objects, clock, TEST_LIMITS, rate=UploadLimits(per_hour=3, per_day=5), time_zone=APP_TZ
    )
    return service, library, objects, clock


def test_start_upload_presigns_the_callers_key_with_the_pdf_policy() -> None:
    service, _, objects = make()
    started = service.start_upload(UserId("ada"), "paper.pdf")
    assert started.upload_id == UPLOAD
    assert started.document_id == DOC
    assert started.fields["key"] == f"uploads/ada/{UPLOAD}.pdf"
    assert objects.presigned == [(f"uploads/ada/{UPLOAD}.pdf", "application/pdf", 52_428_800, 600)]


def test_start_upload_records_the_upload_and_a_processing_document() -> None:
    service, library, _ = make()
    service.start_upload(UserId("ada"), "C:\\papers\\paper.pdf")
    doc = library.state.documents[DOC]
    assert (doc.owner_id, doc.upload_id, doc.file_name, doc.state) == ("ada", UPLOAD, "paper.pdf", "processing")
    assert library.state.uploads[UPLOAD].user_id == "ada"


def test_a_blank_name_stores_nothing() -> None:
    service, library, objects = make()
    with pytest.raises(InvalidFileNameError):
        service.start_upload(UserId("ada"), "   ")
    assert library.state.documents == {} and objects.presigned == []


def test_presigns_with_the_configured_size_limit() -> None:
    library, objects = InMemoryLibrary(), FakeObjectStore()
    service = UploadService(
        library.unit_of_work,
        objects,
        FixedClock(),
        FileLimits(max_bytes=1234, max_pages=9),
        rate=TEST_UPLOAD_LIMITS,
        time_zone=APP_TZ,
    )

    service.start_upload(UserId("ada"), "a.pdf")

    assert objects.presigned[-1][2] == 1234


def test_the_upload_over_the_hourly_limit_is_refused_and_stores_nothing() -> None:
    service, library, objects, clock = counting()
    for minute in range(3):
        clock.current = datetime(2026, 10, 10, 3, minute * 10, tzinfo=UTC)
        service.start_upload(UserId("ada"), f"{minute}.pdf")

    clock.current = datetime(2026, 10, 10, 3, 30, tzinfo=UTC)
    with pytest.raises(UploadLimitReachedError) as refused:
        service.start_upload(UserId("ada"), "fourth.pdf")

    assert refused.value.block.window is LimitWindow.HOUR
    assert refused.value.block.retry_at == datetime(2026, 10, 10, 4, 0, tzinfo=UTC)
    assert len(library.state.uploads) == 3 and len(library.state.documents) == 3 and len(objects.presigned) == 3


def test_duplicate_and_failed_uploads_count() -> None:
    service, library, _, clock = counting()
    for n in range(3):
        clock.current = datetime(2026, 10, 10, 3, n, tzinfo=UTC)
        started = service.start_upload(UserId("ada"), f"{n}.pdf")
        library.state.documents.pop(started.document_id)  # a duplicate's placeholder goes away; a failed one stays
    with pytest.raises(UploadLimitReachedError):
        service.start_upload(UserId("ada"), "next.pdf")


def test_the_daily_cap_resets_at_midnight_gmt7() -> None:
    service, _, _, clock = counting()
    # 5 uploads, one every 2 hours from 06:00 to 14:00 GMT+7 on the 10th (23:00 UTC the 9th ... 07:00 UTC the 10th).
    for n in range(5):
        clock.current = datetime(2026, 10, 9, 23, 0, tzinfo=UTC) + timedelta(hours=2 * n)
        service.start_upload(UserId("ada"), f"{n}.pdf")

    clock.current = datetime(2026, 10, 10, 16, 59, tzinfo=UTC)  # 23:59 GMT+7
    with pytest.raises(UploadLimitReachedError) as refused:
        service.start_upload(UserId("ada"), "late.pdf")
    assert refused.value.block.window is LimitWindow.DAY
    assert refused.value.block.retry_at == datetime(2026, 10, 10, 17, 0, tzinfo=UTC)  # 00:00 GMT+7 the 11th

    clock.current = datetime(2026, 10, 10, 17, 0, tzinfo=UTC)  # 00:00 GMT+7
    service.start_upload(UserId("ada"), "tomorrow.pdf")


def test_upload_block_reports_the_callers_state_only() -> None:
    service, _, _, _ = counting()
    for n in range(3):
        service.start_upload(UserId("ada"), f"{n}.pdf")
    assert service.upload_block(UserId("ada")) is not None
    assert service.upload_block(UserId("bob")) is None
    service.start_upload(UserId("bob"), "b.pdf")  # Ada's uploads never count toward Bob's limits


def test_start_upload_locks_the_learner_before_counting() -> None:
    service, library, _ = make()
    service.start_upload(UserId("ada"), "a.pdf")
    assert library.locked_learners == ["ada"]

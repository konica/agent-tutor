from datetime import UTC, datetime

from fakes import InMemoryLibrary
from smart_tutor.knowledge.domain.upload import Upload
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

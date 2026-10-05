"""SqlSubjectRepository against the Compose Postgres (`make up`)."""

import pytest
from sqlalchemy import Engine

from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.adapters.sql_subjects import SqlSubjectRepository
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = Settings().database_url
    upgrade_to_head(url)
    return create_db_engine(url)


def test_general_resolves_to_its_canonical_name(engine: Engine) -> None:
    unknown = SubjectId("00000000-0000-4000-8000-0000000000ff")
    names = SqlSubjectRepository(engine).canonical_names([GENERAL_SUBJECT_ID, unknown])
    assert names == {GENERAL_SUBJECT_ID: "General"}


def test_no_ids_means_no_query(engine: Engine) -> None:
    assert SqlSubjectRepository(engine).canonical_names([]) == {}

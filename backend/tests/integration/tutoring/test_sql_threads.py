"""SqlThreadRepository against the Compose Postgres (scratch database; see the plan's Global Constraints)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, inspect

from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import ThreadId, UserId
from smart_tutor.tutoring.adapters.sql_threads import SqlThreadRepository
from smart_tutor.tutoring.domain.thread import Thread

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = Settings().database_url
    upgrade_to_head(url)
    return create_db_engine(url)


def test_a_thread_round_trips_for_its_owner_only(engine: Engine) -> None:
    repo = SqlThreadRepository(engine)
    owner = UserId(f"ada-{uuid.uuid4()}")
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, datetime.now(UTC))
    repo.add(thread)
    assert repo.get_owned(thread.thread_id, owner) == thread
    assert repo.get_owned(thread.thread_id, UserId("bob")) is None


def test_the_table_has_no_subject_column(engine: Engine) -> None:
    assert "subject_ids" not in {column["name"] for column in inspect(engine).get_columns("threads")}

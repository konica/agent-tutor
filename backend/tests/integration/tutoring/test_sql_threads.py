"""SqlThreadRepository against the Compose Postgres (scratch database; see the plan's Global Constraints)."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import ThreadId, UserId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID
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
    thread = Thread.start(ThreadId(str(uuid.uuid4())), owner, [GENERAL_SUBJECT_ID], datetime.now(UTC))
    repo.add(thread)
    assert repo.get_owned(thread.thread_id, owner) == thread
    assert repo.get_owned(thread.thread_id, UserId("bob")) is None


def test_the_table_refuses_more_than_three_subjects(engine: Engine) -> None:
    four = "{" + ",".join(str(uuid.uuid4()) for _ in range(4)) + "}"
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(
            text("insert into threads (thread_id, user_id, subject_ids) values (:t, 'ada', cast(:s as uuid[]))"),
            {"t": str(uuid.uuid4()), "s": four},
        )

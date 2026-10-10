"""SqlHighlightMisses against the Compose Postgres (`make up`)."""

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy import Engine, text

from smart_tutor.insights.adapters.sql_highlight_misses import SqlHighlightMisses
from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings

pytestmark = pytest.mark.integration

# Far-future days no real count reaches; the test deletes them before and after.
DAY_1 = date(2999, 1, 1)
DAY_2 = date(2999, 1, 2)


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = Settings().database_url
    upgrade_to_head(url)
    return create_db_engine(url)


@pytest.fixture
def clean_days(engine: Engine) -> Iterator[None]:
    def clear() -> None:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM highlight_misses WHERE day IN (:a, :b)"), {"a": DAY_1, "b": DAY_2})

    clear()
    yield
    clear()


def misses(engine: Engine, day: date) -> int | None:
    with engine.connect() as conn:
        return conn.execute(text("SELECT misses FROM highlight_misses WHERE day = :d"), {"d": day}).scalar()


@pytest.mark.usefixtures("clean_days")
def test_counts_per_day(engine: Engine) -> None:
    counter = SqlHighlightMisses(engine)
    assert misses(engine, DAY_1) is None
    counter.increment(DAY_1)
    counter.increment(DAY_1)
    counter.increment(DAY_2)
    assert misses(engine, DAY_1) == 2
    assert misses(engine, DAY_2) == 1

"""Against the Compose Postgres (`make up`)."""

import pytest
from sqlalchemy import create_engine, text

from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings

pytestmark = pytest.mark.integration


def test_upgrade_to_head_reaches_the_library_head_and_is_repeatable() -> None:
    url = Settings().database_url
    upgrade_to_head(url)
    upgrade_to_head(url)  # running twice is a no-op
    with create_engine(url).connect() as conn:
        assert conn.execute(text("select version_num from alembic_version")).scalar_one() == "0002"


def test_general_subject_is_seeded() -> None:
    url = Settings().database_url
    upgrade_to_head(url)
    with create_engine(url).connect() as conn:
        name = conn.execute(text("select canonical_name from subjects where normalized_name = 'general'"))
        assert name.scalar_one() == "General"

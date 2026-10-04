"""Run Alembic migrations from inside the package (no alembic.ini needed in images)."""

from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).parent / "migrations"


def upgrade_to_head(database_url: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")

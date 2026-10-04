"""Alembic environment. Tables arrive with the slices that need them (US-2 onward), using PRD §9.4 names."""

from alembic import context
from sqlalchemy import engine_from_config, pool

from smart_tutor.shared.adapters.postgres.migrate import escape_percent
from smart_tutor.shared.config import Settings

config = context.config
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", escape_percent(Settings().database_url))

target_metadata = None


def run_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_online() -> None:
    engine = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_offline()
else:
    run_online()

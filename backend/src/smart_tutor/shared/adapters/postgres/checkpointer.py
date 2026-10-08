"""The agent's LangGraph checkpointer in PostgreSQL: a question waiting for a subject pick survives restarts."""

from collections.abc import AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.engine import make_url


def psycopg_conninfo(sqlalchemy_url: str) -> str:
    """The SQLAlchemy URL without its ``+psycopg`` driver, which libpq-style connection strings don't take."""
    return make_url(sqlalchemy_url).set(drivername="postgresql").render_as_string(hide_password=False)


def open_checkpointer(database_url: str) -> AbstractAsyncContextManager[AsyncPostgresSaver]:
    return _open(database_url)


@asynccontextmanager
async def _open(database_url: str) -> AsyncIterator[AsyncPostgresSaver]:
    pool = AsyncConnectionPool(
        psycopg_conninfo(database_url),
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    try:
        saver = AsyncPostgresSaver(pool)  # type: ignore[arg-type]
        await saver.setup()  # creates its tables idempotently
        yield saver
    finally:
        await pool.close()

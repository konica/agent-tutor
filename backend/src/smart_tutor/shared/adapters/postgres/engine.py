"""One SQLAlchemy engine per process (psycopg 3)."""

from sqlalchemy import Engine, create_engine


def create_db_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)

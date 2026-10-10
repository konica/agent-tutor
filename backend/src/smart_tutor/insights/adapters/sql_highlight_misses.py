"""The highlight-miss count in Postgres: one row per UTC day, nothing else."""

from datetime import date

from sqlalchemy import Column, Date, Engine, Integer, MetaData, Table
from sqlalchemy.dialects.postgresql import insert

from smart_tutor.insights.ports.highlight_misses import HighlightMissCounter

_highlight_misses = Table(
    "highlight_misses",
    MetaData(),
    Column("day", Date, primary_key=True),
    Column("misses", Integer, nullable=False),
)


class SqlHighlightMisses(HighlightMissCounter):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def increment(self, day: date) -> None:
        stmt = insert(_highlight_misses).values(day=day, misses=1)
        stmt = stmt.on_conflict_do_update(
            index_elements=[_highlight_misses.c.day],
            set_={"misses": _highlight_misses.c.misses + 1},
        )
        with self._engine.begin() as conn:
            conn.execute(stmt)

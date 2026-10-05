"""The shared subject catalog in Postgres."""

from collections.abc import Collection

from sqlalchemy import Column, Engine, MetaData, Table, Text, Uuid, select

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.ports.subject_repository import SubjectRepository

_subjects = Table(
    "subjects",
    MetaData(),
    Column("subject_id", Uuid(as_uuid=False), primary_key=True),
    Column("canonical_name", Text),
)


class SqlSubjectRepository(SubjectRepository):
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def canonical_names(self, subject_ids: Collection[SubjectId]) -> dict[SubjectId, str]:
        if not subject_ids:
            return {}
        stmt = select(_subjects.c.subject_id, _subjects.c.canonical_name).where(
            _subjects.c.subject_id.in_(list(subject_ids))
        )
        with self._engine.connect() as conn:
            return {SubjectId(row.subject_id): row.canonical_name for row in conn.execute(stmt)}

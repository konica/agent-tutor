"""The shared subject catalog in Postgres."""

from collections.abc import Collection, Sequence

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, Engine, MetaData, Table, Text, Uuid, select, update
from sqlalchemy.dialects.postgresql import insert

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.subject import Subject
from smart_tutor.subjects.domain.suggestions import Candidate
from smart_tutor.subjects.ports.subject_repository import SubjectRepository

NAME_EMBEDDING_DIM = 1024  # as chunks.embedding; `subjects` cannot import `knowledge`

_subjects = Table(
    "subjects",
    MetaData(),
    Column("subject_id", Uuid(as_uuid=False), primary_key=True),
    Column("canonical_name", Text),
    Column("normalized_name", Text),
    Column("name_embedding", Vector(NAME_EMBEDDING_DIM)),
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

    def most_similar(self, embedding: Sequence[float], limit: int) -> list[Candidate]:
        distance = _subjects.c.name_embedding.cosine_distance(list(embedding))
        stmt = (
            select(_subjects.c.subject_id, _subjects.c.canonical_name, (1 - distance).label("similarity"))
            .where(_subjects.c.name_embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        with self._engine.connect() as conn:
            return [
                Candidate(Subject(SubjectId(r.subject_id), r.canonical_name), float(r.similarity))
                for r in conn.execute(stmt)
            ]

    def find_by_normalized_names(self, normalized: Collection[str]) -> dict[str, Subject]:
        if not normalized:
            return {}
        stmt = select(_subjects.c.subject_id, _subjects.c.canonical_name, _subjects.c.normalized_name).where(
            _subjects.c.normalized_name.in_(list(normalized))
        )
        with self._engine.connect() as conn:
            return {r.normalized_name: Subject(SubjectId(r.subject_id), r.canonical_name) for r in conn.execute(stmt)}

    def insert_or_get(self, subject: Subject, normalized_name: str, name_embedding: Sequence[float]) -> Subject:
        with self._engine.begin() as conn:
            inserted = conn.execute(
                insert(_subjects)
                .values(
                    subject_id=subject.subject_id,
                    canonical_name=subject.canonical_name,
                    normalized_name=normalized_name,
                    name_embedding=list(name_embedding),
                )
                .on_conflict_do_nothing(index_elements=["normalized_name"])
                .returning(_subjects.c.subject_id)
            ).first()
            if inserted is not None:
                return subject
            # READ COMMITTED: this statement sees the row the concurrent winner committed.
            row = conn.execute(select(_subjects).where(_subjects.c.normalized_name == normalized_name)).one()
            return Subject(SubjectId(row.subject_id), row.canonical_name)

    def missing_name_embeddings(self, limit: int) -> list[Subject]:
        stmt = (
            select(_subjects.c.subject_id, _subjects.c.canonical_name)
            .where(_subjects.c.name_embedding.is_(None))
            .limit(limit)
        )
        with self._engine.connect() as conn:
            return [Subject(SubjectId(r.subject_id), r.canonical_name) for r in conn.execute(stmt)]

    def set_name_embedding(self, subject_id: SubjectId, embedding: Sequence[float]) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                update(_subjects).where(_subjects.c.subject_id == subject_id).values(name_embedding=list(embedding))
            )

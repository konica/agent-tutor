"""SqlSubjectRepository against the Compose Postgres (`make up`)."""

import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Engine, text

from smart_tutor.shared.adapters.postgres.engine import create_db_engine
from smart_tutor.shared.adapters.postgres.migrate import upgrade_to_head
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.adapters.sql_subjects import SqlSubjectRepository
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID
from smart_tutor.subjects.domain.subject import Subject, normalize_subject_name

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine() -> Engine:
    url = Settings().database_url
    upgrade_to_head(url)
    return create_db_engine(url)


def test_general_resolves_to_its_canonical_name(engine: Engine) -> None:
    unknown = SubjectId("00000000-0000-4000-8000-0000000000ff")
    names = SqlSubjectRepository(engine).canonical_names([GENERAL_SUBJECT_ID, unknown])
    assert names == {GENERAL_SUBJECT_ID: "General"}


def test_no_ids_means_no_query(engine: Engine) -> None:
    assert SqlSubjectRepository(engine).canonical_names([]) == {}


def vec(*head: float) -> list[float]:
    return [*head, *([0.0] * (1024 - len(head)))]


def _new_subject(name: str) -> Subject:
    return Subject(SubjectId(str(uuid.uuid4())), name)


def test_insert_or_get_creates_once_and_reuses_by_normalized_name(engine: Engine) -> None:
    repo = SqlSubjectRepository(engine)
    name = f"Topic {uuid.uuid4()}"
    normalized = normalize_subject_name(name)
    first = repo.insert_or_get(_new_subject(name), normalized, vec(1.0))
    again = repo.insert_or_get(_new_subject(name.upper()), normalized, vec(1.0))
    assert again == first
    assert repo.find_by_normalized_names([normalized]) == {normalized: first}


def test_no_names_means_no_query_for_find_by_normalized_names(engine: Engine) -> None:
    assert SqlSubjectRepository(engine).find_by_normalized_names([]) == {}


def test_concurrent_creation_of_one_name_gives_one_row(engine: Engine) -> None:
    repo, name = SqlSubjectRepository(engine), f"Topic {uuid.uuid4()}"
    with ThreadPoolExecutor(8) as pool:
        got = set(
            pool.map(lambda _: repo.insert_or_get(_new_subject(name), normalize_subject_name(name), vec(1.0)), range(8))
        )
    assert len(got) == 1


def test_most_similar_orders_by_cosine_similarity(engine: Engine) -> None:
    repo = SqlSubjectRepository(engine)
    tag = uuid.uuid4().hex  # rows from earlier runs persist: use a direction on two random axes
    axis_a, axis_b = 2 + int(tag[:4], 16) % 1000, 2 + int(tag[4:8], 16) % 1000
    query = [1.0 if i in (axis_a, axis_b) else 0.0 for i in range(1024)]
    near = repo.insert_or_get(_new_subject(f"Near {tag}"), f"near {tag}", query)
    results = repo.most_similar(query, limit=5)
    by_subject = {c.subject: c.similarity for c in results}
    assert abs(by_subject[near] - 1.0) < 1e-6
    similarities = [c.similarity for c in results]
    assert similarities == sorted(similarities, reverse=True)


def test_missing_name_embeddings_are_listed_and_set(engine: Engine) -> None:
    repo = SqlSubjectRepository(engine)
    subject = _new_subject(f"Bare {uuid.uuid4()}")
    with engine.begin() as conn:
        conn.execute(
            text("insert into subjects (subject_id, canonical_name, normalized_name) values (:i, :n, :m)"),
            {"i": subject.subject_id, "n": subject.canonical_name, "m": normalize_subject_name(subject.canonical_name)},
        )
    assert subject in repo.missing_name_embeddings(limit=1000)
    repo.set_name_embedding(subject.subject_id, vec(0.5))
    assert subject not in repo.missing_name_embeddings(limit=1000)


def _subject(repo: SqlSubjectRepository, name: str) -> Subject:
    subject = Subject(SubjectId(str(uuid.uuid4())), name)
    return repo.insert_or_get(subject, normalize_subject_name(name), vec(1.0))


def test_search_matches_contained_names_prefix_first_and_excludes(engine: Engine) -> None:
    repo = SqlSubjectRepository(engine)
    tag = uuid.uuid4().hex[:8]
    inner = _subject(repo, f"Dense {tag} Retrieval")
    prefix = _subject(repo, f"{tag} Retrieval")
    skipped = _subject(repo, f"{tag} Skipped")
    found = repo.search(tag, exclude=[skipped.subject_id], limit=10)
    assert [s.subject_id for s in found] == [prefix.subject_id, inner.subject_id]


def test_search_treats_like_wildcards_literally(engine: Engine) -> None:
    repo = SqlSubjectRepository(engine)
    tag = uuid.uuid4().hex[:8]
    literal = _subject(repo, f"{tag} 100% _done\\")
    _subject(repo, f"{tag} 100 x done")
    assert [s.subject_id for s in repo.search(f"{tag} 100% _done\\", exclude=[], limit=10)] == [literal.subject_id]
    assert repo.search(f"{tag}%", exclude=[], limit=10) == []  # as a wildcard it would match both
    assert repo.search(f"{tag}_100", exclude=[], limit=10) == []

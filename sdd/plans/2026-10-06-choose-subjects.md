# Choose Subjects from 3 Suggestions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a content becomes ready, its waiting documents go to *choose subjects*; the learner picks 1–3 of 3 ranked suggestions in a picker and the document becomes *ready* (GitHub issue #77, parent US-2b #10).

**Architecture:** `subjects` gains the catalog's write side (normalized names, `name_embedding`, get-or-create with insert-or-get on the unique `normalized_name`) and a pure ranking function behind `SubjectSuggester`. `knowledge` replaces the interim "General" step with `awaiting_subjects` and adds `SubjectChoiceService`, which reads the document and content under `can_read`, asks `subjects.application` for suggestions, and saves the choice (ADR 0004). The API exposes `GET /documents/{id}/subject-suggestions` and `PUT /documents/{id}/subjects`; the web Library row gets a "Choose subjects" action that opens a picker dialog.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy Core, pgvector, Alembic, LangChain `Embeddings`; React 19 + TypeScript, Vitest + Testing Library, generated `@hey-api` client.

**Spec:** GitHub issue #77 (`gh issue view 77`), PRD `sdd/prd.md` §8 US-2b, D20, §9.2 step 5, §9.4, §9.5; ADR 0003, 0004; mockup round v0.4 states `picker-default`, `picker-none-selected`, `picker-maximum`, `picker-saved`.

## Global Constraints

- Read `AGENTS.md`, `backend/AGENTS.md`, the module `README.md` files, and `DESIGN.md` (web) before editing. Import rules are enforced by `PYTHONUTF8=1 uv run lint-imports`: `knowledge` may import only `subjects.application`; `apps` is a leaf.
- Store `subject_id`s everywhere; resolve names at read time through `SubjectNames.names_for`.
- Documents have **1–3 distinct** subjects. Only a document in `awaiting_subjects` (or `ready`) accepts subjects.
- Every document read goes through `can_read` (owner only), in code and SQL; another learner's document is a `404`, never a `403`.
- Subject names: trimmed, whitespace collapsed, control characters removed, at most **60** characters. Normalized name = NFKC + casefold + single spaces. Exact normalized match reuses an existing subject.
- Origins are `shared` ("Shared subject"), `yours` ("Your subject"), `new` ("New") — copy from the prototype.
- Required wording (verbatim): "Choose subjects" (row action and dialog title), "Subjects saved." and "*Title* is ready to use." (saved state and live region: "Subjects saved. *Title* is ready to use.").
- Out of scope: typed names / type-ahead, near-duplicate reuse, personal-data/offensive check (#79), needs-action banner / nav badge / step-through (#80), dedupe-linked documents (US-11, #21).
- Embedding vectors are 1024 floats in Postgres (`Vector(1024)`); unit tests use `fake_embeddings(8)`.
- Commit subjects in the imperative mood, body says why; end every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Web: `cd web && npm run build && npm test`.

## Decisions (made while planning; record in the PR)

- **Suggestions are computed when read** (`GET …/subject-suggestions`): one vector query plus name lookups, well under the PRD's 30 s; nothing is stored. Saving is validated statelessly: existing ids must exist; a new name must be one of the content's `proposed_subject_names` (typed names come next slice).
- **Match threshold 0.68, boost 0.05** (cosine). Measured on Nova embeddings: related names score 0.69–0.77 against a two-sentence summary, unrelated ones 0.51–0.64. Both are constructor parameters of `SubjectSuggester`, for the suggestion evals to tune.
- **Proposed names that equal an existing subject** (normalized, or one of the learner's own names) are treated as that subject with a perfect match (score 1.0), not as a new name.
- **Filling order:** matched subjects (by boosted score) → new proposed names → the learner's other subjects (by name) → "General" only if nothing else exists (no description and no subjects), so the picker is never empty.
- **The API embeds new names** (get-or-create in a request), so Compose's `api` gets the same read-only `~/.aws` mount as `worker`. The worker backfills missing `name_embedding`s (the seeded "General") at startup.

## Review Focus

1. A content with no description (describe call failed): no summary embedding, no proposed names → suggestions are the learner's subjects or "General"; never an empty picker, never a 500. (Task 3, Task 5 tests.)
2. Two learners saving the same new name concurrently → one `subjects` row (insert-or-get on `normalized_name`). (Task 2 integration test.)
3. Malformed ids in the path or body (`"abc"` instead of a UUID) → `422`, never a 500 from Postgres. (Task 6 test.)
4. A new name chosen together with the existing subject it resolves to (same subject twice) → `422`, no partial save. (Task 5 test.)
5. Saving for a document still `processing` or `failed` → `409` and the document is unchanged. (Task 5, Task 6 tests.)

---

## File Structure

Backend (`backend/src/smart_tutor/`):
- `subjects/domain/subject.py` — modify: `Subject`, `MAX_SUBJECT_NAME`, `clean_subject_name`, `normalize_subject_name`.
- `subjects/domain/errors.py` — create: `InvalidSubjectNameError`.
- `subjects/domain/suggestions.py` — create: `SuggestionOrigin`, `Suggestion`, `Candidate`, `rank_suggestions`.
- `subjects/ports/subject_repository.py` — modify: write and similarity methods.
- `subjects/adapters/sql_subjects.py` — modify: implement them.
- `subjects/application/catalog.py` — create: `SubjectCatalogService`.
- `subjects/application/suggester.py` — create: `SubjectSuggester`.
- `subjects/application/__init__.py` — modify: exports.
- `shared/adapters/postgres/migrations/versions/0005_subject_name_embedding.py` — create.
- `knowledge/domain/document.py`, `knowledge/domain/errors.py` — modify.
- `knowledge/ports/library.py`, `knowledge/adapters/sql_library.py` — modify: `get_readable`, `subject_ids_readable_by`.
- `knowledge/application/ingestion_service.py` — modify: `awaiting_subjects` instead of "General".
- `knowledge/application/document_service.py` — modify: `document_view` helper.
- `knowledge/application/subject_choice.py` — create: `SubjectChoiceService`, `SubjectSuggestions`.
- `knowledge/application/__init__.py` — modify: exports.
- `apps/api/routes/knowledge.py`, `apps/api/services.py`, `apps/api/deps.py` — modify.
- `apps/worker/main.py` — modify: backfill at startup.
- READMEs of `subjects` and `knowledge`.

Tests (`backend/tests/`): `fakes/subjects.py`, `fakes/knowledge.py`, `unit/subjects/test_names.py`, `unit/subjects/test_ranking.py`, `unit/subjects/test_catalog.py`, `unit/subjects/test_suggester.py`, `unit/knowledge/test_domain.py`, `unit/knowledge/test_processing.py`, `unit/knowledge/test_subject_choice.py`, `unit/apps/api/test_knowledge_routes.py`, `isolation/test_documents.py`, `integration/subjects/test_sql_subjects.py`, `integration/knowledge/test_sql_library.py`.

Web (`web/src/`): `components/SubjectChip/*`, `components/Dialog/*`, `components/Banner/*`, `api/documents.ts` (+ test), `features/library/SubjectPicker.tsx` (+ `.module.css`, `.test.tsx`), `features/library/DocumentTable.tsx`, `features/library/LibraryPage.tsx` (+ test), regenerated `api/openapi.json` and `api/generated/*`.

Other: `compose.yaml` (api `~/.aws` mount), `sdd/prd.md` (v2.18), `AGENTS.md` (PRD version reference).

---

### Task 1: Subject names and suggestion ranking (subjects domain)

**Files:**
- Modify: `backend/src/smart_tutor/subjects/domain/subject.py`
- Create: `backend/src/smart_tutor/subjects/domain/errors.py`, `backend/src/smart_tutor/subjects/domain/suggestions.py`
- Test: `backend/tests/unit/subjects/test_names.py`, `backend/tests/unit/subjects/test_ranking.py`

**Interfaces:**
- Produces:
  - `MAX_SUBJECT_NAME = 60`; `clean_subject_name(raw: str) -> str` (raises `InvalidSubjectNameError`); `normalize_subject_name(name: str) -> str`.
  - `@dataclass(frozen=True) class Subject: subject_id: SubjectId; canonical_name: str`.
  - `class SuggestionOrigin(StrEnum): SHARED = "shared"; YOURS = "yours"; NEW = "new"`.
  - `@dataclass(frozen=True) class Suggestion: name: str; origin: SuggestionOrigin; subject_id: SubjectId | None = None` (`None` only for `NEW`).
  - `@dataclass(frozen=True) class Candidate: subject: Subject; similarity: float`.
  - `SUGGESTIONS = 3`, `MATCH_THRESHOLD = 0.68`, `YOURS_BOOST = 0.05`.
  - `rank_suggestions(*, similar: Sequence[Candidate], proposed_names: Sequence[str], existing_by_name: Mapping[str, Subject], yours: Mapping[SubjectId, str], fallback: Subject, threshold: float = MATCH_THRESHOLD, boost: float = YOURS_BOOST) -> list[Suggestion]`.

- [ ] **Step 1: Write failing tests for names** (`tests/unit/subjects/test_names.py`)

```python
import pytest

from smart_tutor.subjects.domain.errors import InvalidSubjectNameError
from smart_tutor.subjects.domain.subject import clean_subject_name, normalize_subject_name


def test_clean_collapses_whitespace_and_drops_control_characters() -> None:
    assert clean_subject_name("  Deep‮   Learning\n") == "Deep Learning"


@pytest.mark.parametrize("raw", ["", "   ", "\x00", "x" * 61])
def test_clean_rejects_empty_or_too_long(raw: str) -> None:
    with pytest.raises(InvalidSubjectNameError):
        clean_subject_name(raw)


def test_normalize_is_equal_for_one_name_typed_differently() -> None:
    assert normalize_subject_name("Deep  LEARNING") == normalize_subject_name("deep learning") == "deep learning"
    assert normalize_subject_name("Ｄeep Learning") == "deep learning"  # NFKC: full-width letters
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/unit/subjects/test_names.py -q` — expect ImportError.

- [ ] **Step 3: Implement** `subjects/domain/errors.py`:

```python
"""Errors of the subjects module; entrypoints map them to responses."""

from smart_tutor.shared.domain.errors import DomainError


class InvalidSubjectNameError(DomainError):
    """A subject name is empty or longer than 60 characters (PRD US-2b)."""
```

and extend `subjects/domain/subject.py` (keep `GENERAL_SUBJECT_ID`, update its comment: it is now only the last-resort suggestion and stays on documents that already have it):

```python
"""The shared subject catalog (PRD §9.4, D20): stable ids, canonical names, normalized names."""

import re
import unicodedata
from dataclasses import dataclass

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.errors import InvalidSubjectNameError

# Seeded by migration 0002. Documents made ready before US-2b keep it; now it is only the last-resort suggestion.
GENERAL_SUBJECT_ID = SubjectId("00000000-0000-4000-8000-000000000001")
MAX_SUBJECT_NAME = 60
_CONTROL = re.compile("[\\x00-\\x1f\\x7f-\\x9f\\u200e\\u200f\\u202a-\\u202e\\u2066-\\u2069]")


@dataclass(frozen=True)
class Subject:
    subject_id: SubjectId
    canonical_name: str


def clean_subject_name(raw: str) -> str:
    """The name as shown: no control characters, single spaces, 1 to 60 characters."""
    name = " ".join(_CONTROL.sub(" ", raw).split())
    if not name or len(name) > MAX_SUBJECT_NAME:
        raise InvalidSubjectNameError(f"Subject names can be 1 to {MAX_SUBJECT_NAME} characters.")
    return name


def normalize_subject_name(name: str) -> str:
    """NFKC, case-folded, single spaces: the key of `subjects.normalized_name` (unique)."""
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())
```

- [ ] **Step 4: Run** the names tests — PASS.

- [ ] **Step 5: Write failing ranking tests** (`tests/unit/subjects/test_ranking.py`). Use readable ids `SubjectId("s-…")`:

```python
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.subject import Subject
from smart_tutor.subjects.domain.suggestions import Candidate, Suggestion, SuggestionOrigin, rank_suggestions

GENERAL = Subject(SubjectId("s-general"), "General")
NLP = Subject(SubjectId("s-nlp"), "Natural Language Processing")
DL = Subject(SubjectId("s-dl"), "Deep Learning")
LLM = Subject(SubjectId("s-llm"), "Large Language Models")
COOK = Subject(SubjectId("s-cook"), "Cooking")
PROPOSED = ["Deep Learning", "Machine Translation", "Attention Mechanisms"]


def rank(similar=(), proposed=(), existing=None, yours=None):  # type: ignore[no-untyped-def]
    return rank_suggestions(
        similar=list(similar), proposed_names=list(proposed), existing_by_name=existing or {},
        yours=yours or {}, fallback=GENERAL,
    )


def test_matching_shared_subjects_come_first_by_similarity_and_new_names_fill_the_rest() -> None:
    got = rank(similar=[Candidate(DL, 0.70), Candidate(NLP, 0.75), Candidate(COOK, 0.52)],
               proposed=["Machine Translation", "Attention Mechanisms", "Transformers"])
    assert got == [
        Suggestion("Natural Language Processing", SuggestionOrigin.SHARED, NLP.subject_id),
        Suggestion("Deep Learning", SuggestionOrigin.SHARED, DL.subject_id),
        Suggestion("Machine Translation", SuggestionOrigin.NEW),
    ]


def test_the_learners_subjects_are_boosted_above_the_threshold_and_named_their_way() -> None:
    got = rank(similar=[Candidate(NLP, 0.70), Candidate(LLM, 0.66)], proposed=["A", "B", "C"],
               yours={LLM.subject_id: "LLMs"})
    assert got[0] == Suggestion("LLMs", SuggestionOrigin.YOURS, LLM.subject_id)  # 0.66 + 0.05 > 0.70
    assert got[1].subject_id == NLP.subject_id and got[2] == Suggestion("A", SuggestionOrigin.NEW)


def test_a_proposed_name_that_exists_is_that_subject_not_a_new_name() -> None:
    got = rank(proposed=PROPOSED, existing={"deep learning": DL})
    assert got == [
        Suggestion("Deep Learning", SuggestionOrigin.SHARED, DL.subject_id),
        Suggestion("Machine Translation", SuggestionOrigin.NEW),
        Suggestion("Attention Mechanisms", SuggestionOrigin.NEW),
    ]


def test_a_proposed_name_equal_to_a_learners_own_name_is_their_subject() -> None:
    got = rank(proposed=["LLMs", "X", "Y"], yours={LLM.subject_id: "LLMs"})
    assert got[0] == Suggestion("LLMs", SuggestionOrigin.YOURS, LLM.subject_id)


def test_always_three_when_enough_candidates_exist() -> None:
    similar = [Candidate(NLP, 0.9), Candidate(DL, 0.8), Candidate(LLM, 0.7), Candidate(COOK, 0.69)]
    assert len(rank(similar=similar, proposed=PROPOSED)) == 3
    assert [s.origin for s in rank(proposed=PROPOSED)] == [SuggestionOrigin.NEW] * 3


def test_without_a_description_the_learners_subjects_then_general_fill_in() -> None:
    assert rank(yours={NLP.subject_id: "NLP", DL.subject_id: "Deep learning"}) == [
        Suggestion("Deep learning", SuggestionOrigin.YOURS, DL.subject_id),
        Suggestion("NLP", SuggestionOrigin.YOURS, NLP.subject_id),
    ]
    assert rank() == [Suggestion("General", SuggestionOrigin.SHARED, GENERAL.subject_id)]


def test_no_subject_is_suggested_twice() -> None:
    got = rank(similar=[Candidate(DL, 0.8)], proposed=["deep  learning", "Deep Learning", "Z"],
               existing={"deep learning": DL})
    assert [s.name for s in got] == ["Deep Learning", "Z"]
```

- [ ] **Step 6: Run** — expect ImportError.

- [ ] **Step 7: Implement** `subjects/domain/suggestions.py`:

```python
"""Ranking 3 subject suggestions for one learner and one content (PRD §9.2 step 5, D20, US-2b)."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.subject import Subject, normalize_subject_name

SUGGESTIONS = 3
# Cosine similarity of the content summary to a subject name. Nova embeddings put related names at 0.69-0.77 and
# unrelated ones at 0.51-0.64 (measured 2026-10-06); the suggestion evals tune both values.
MATCH_THRESHOLD = 0.68
YOURS_BOOST = 0.05
_EXACT = 1.0  # a proposed name equal to an existing subject's name


class SuggestionOrigin(StrEnum):
    SHARED = "shared"
    YOURS = "yours"
    NEW = "new"


@dataclass(frozen=True)
class Suggestion:
    name: str
    origin: SuggestionOrigin
    subject_id: SubjectId | None = None  # None for a new name


@dataclass(frozen=True)
class Candidate:
    subject: Subject
    similarity: float


def rank_suggestions(
    *,
    similar: Sequence[Candidate],
    proposed_names: Sequence[str],
    existing_by_name: Mapping[str, Subject],
    yours: Mapping[SubjectId, str],
    fallback: Subject,
    threshold: float = MATCH_THRESHOLD,
    boost: float = YOURS_BOOST,
) -> list[Suggestion]:
    """Matching subjects by boosted similarity, then new proposed names, then the learner's other subjects.

    `existing_by_name` maps normalized names to subjects; `yours` maps the learner's subjects to their display
    names (a proposed name equal to one is that subject). `fallback` is used only when nothing else exists.
    """
    names = {c.subject.subject_id: c.subject.canonical_name for c in similar}
    scores: dict[SubjectId, float] = {}
    for c in similar:
        score = c.similarity + (boost if c.subject.subject_id in yours else 0.0)
        if score >= threshold:
            scores[c.subject.subject_id] = max(score, scores.get(c.subject.subject_id, score))
    yours_by_name = {normalize_subject_name(name): sid for sid, name in yours.items()}
    new_names: list[str] = []
    for proposed in proposed_names:
        key = normalize_subject_name(proposed)
        existing = existing_by_name.get(key)
        sid = yours_by_name.get(key) or (existing.subject_id if existing else None)
        if sid is None:
            if key not in {normalize_subject_name(n) for n in new_names}:
                new_names.append(proposed)
            continue
        if existing is not None:
            names.setdefault(sid, existing.canonical_name)
        scores[sid] = max(scores.get(sid, 0.0), _EXACT + (boost if sid in yours else 0.0))

    def suggestion(sid: SubjectId, fallback_name: str) -> Suggestion:
        origin = SuggestionOrigin.YOURS if sid in yours else SuggestionOrigin.SHARED
        return Suggestion(yours.get(sid, fallback_name), origin, sid)

    ranked = sorted(scores, key=lambda sid: (-scores[sid], yours.get(sid, names.get(sid, ""))))
    result = [suggestion(sid, names.get(sid, "")) for sid in ranked[:SUGGESTIONS]]
    result += [Suggestion(name, SuggestionOrigin.NEW) for name in new_names]
    chosen = {s.subject_id for s in result}
    result += [suggestion(sid, name) for sid, name in sorted(yours.items(), key=lambda p: p[1]) if sid not in chosen]
    if not result:
        result = [suggestion(fallback.subject_id, fallback.canonical_name)]
    return result[:SUGGESTIONS]
```

Note: `rank_suggestions` drops `new_names` duplicates that match each other but a proposed name matching an existing subject that is already in `scores` is not duplicated (the score map dedupes). Make sure `test_no_subject_is_suggested_twice` passes (DL appears once; "deep  learning" and "Deep Learning" both map to DL).

- [ ] **Step 8: Run** `uv run pytest tests/unit/subjects -q` — PASS. Run `uv run ruff check src tests && uv run mypy`.

- [ ] **Step 9: Commit**

```bash
git add backend/src/smart_tutor/subjects/domain backend/tests/unit/subjects
git commit -m "Rank 3 subject suggestions in the subjects domain" -m "US-2b: matching shared subjects first, the learner's subjects boosted, new proposed names fill the rest. Pure code so ranking is unit-tested with fake scores." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Catalog persistence: name embeddings, similarity, insert-or-get

**Files:**
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0005_subject_name_embedding.py`
- Modify: `backend/src/smart_tutor/subjects/ports/subject_repository.py`, `backend/src/smart_tutor/subjects/adapters/sql_subjects.py`, `backend/tests/fakes/subjects.py`
- Test: `backend/tests/integration/subjects/test_sql_subjects.py`, `backend/tests/unit/subjects/test_fake_subjects.py`

**Interfaces:**
- Consumes: `Subject`, `Candidate`, `normalize_subject_name` (Task 1).
- Produces (`SubjectRepository` ABC, all implemented by `SqlSubjectRepository` and `InMemorySubjects`):
  - `canonical_names(subject_ids) -> dict[SubjectId, str]` (existing)
  - `most_similar(embedding: Sequence[float], limit: int) -> list[Candidate]` — cosine similarity (`1 - (name_embedding <=> v)`), highest first, only rows with an embedding.
  - `find_by_normalized_names(normalized: Collection[str]) -> dict[str, Subject]` — keyed by normalized name.
  - `insert_or_get(subject: Subject, normalized_name: str, name_embedding: Sequence[float]) -> Subject` — the stored subject for that normalized name (concurrent callers get one row).
  - `missing_name_embeddings(limit: int) -> list[Subject]`
  - `set_name_embedding(subject_id: SubjectId, embedding: Sequence[float]) -> None`
- `InMemorySubjects(names=None, embeddings=None)`: `names: dict[SubjectId, str]` (default General), `embeddings: dict[SubjectId, list[float]]`; `normalized` derived from names.

- [ ] **Step 1: Migration 0005** (revision `"0005"`, down `"0004"`, header style as 0004):

```python
"""Subject name embeddings for suggestion ranking (PRD §9.4 `subjects.name_embedding`, §9.2 step 5).

The seeded "General" row gets its embedding from the worker at startup (no model calls in migrations).
"""
...
EMBEDDING_DIM = 1024  # Nova multimodal embeddings, as chunks.embedding


def upgrade() -> None:
    op.add_column("subjects", sa.Column("name_embedding", Vector(EMBEDDING_DIM)))


def downgrade() -> None:
    op.drop_column("subjects", "name_embedding")
```

No vector index: the catalog is small; add HNSW when it grows (note in the PR). Update `tests/integration/shared/test_migrations.py` only if it pins the head revision name (it currently says "reaches the chunks head"; rename the test to `..._reaches_head_...` if it asserts a revision id — read it first).

- [ ] **Step 2: Write failing integration tests** (append to `tests/integration/subjects/test_sql_subjects.py`; they need Compose Postgres, `docker compose up -d`, run with `uv run --env-file ../.env pytest -m integration tests/integration/subjects`). Use unique names per run (`f"Topic {uuid4()}"`) because the database is shared:

```python
def vec(*head: float) -> list[float]:
    return [*head, *([0.0] * (1024 - len(head)))]


def test_insert_or_get_creates_once_and_reuses_by_normalized_name(engine: Engine) -> None:
    repo = SqlSubjectRepository(engine)
    name = f"Topic {uuid.uuid4()}"
    first = repo.insert_or_get(Subject(SubjectId(str(uuid.uuid4())), name), normalize_subject_name(name), vec(1.0))
    again = repo.insert_or_get(Subject(SubjectId(str(uuid.uuid4())), name.upper()), normalize_subject_name(name), vec(1.0))
    assert again == first
    assert repo.find_by_normalized_names([normalize_subject_name(name)]) == {normalize_subject_name(name): first}


def test_concurrent_creation_of_one_name_gives_one_row(engine: Engine) -> None:
    repo, name = SqlSubjectRepository(engine), f"Topic {uuid.uuid4()}"
    with ThreadPoolExecutor(8) as pool:
        got = set(pool.map(lambda _: repo.insert_or_get(
            Subject(SubjectId(str(uuid.uuid4())), name), normalize_subject_name(name), vec(1.0)), range(8)))
    assert len(got) == 1


def test_most_similar_orders_by_cosine_similarity(engine: Engine) -> None:
    repo = SqlSubjectRepository(engine)
    tag = uuid.uuid4().hex  # a direction no other test row uses: put weight on a random axis
    axis = 2 + int(tag[:4], 16) % 1000
    near = repo.insert_or_get(Subject(SubjectId(str(uuid.uuid4())), f"Near {tag}"), f"near {tag}",
                              [1.0 if i == axis else 0.0 for i in range(1024)])
    query = [1.0 if i == axis else 0.0 for i in range(1024)]
    top = repo.most_similar(query, limit=1)
    assert top[0].subject == near and abs(top[0].similarity - 1.0) < 1e-6


def test_missing_name_embeddings_are_listed_and_set(engine: Engine) -> None:
    repo = SqlSubjectRepository(engine)
    missing = repo.missing_name_embeddings(limit=1000)
    for subject in missing:
        repo.set_name_embedding(subject.subject_id, vec(0.5))
    assert repo.missing_name_embeddings(limit=1000) == []
```

Imports: `uuid`, `ThreadPoolExecutor` from `concurrent.futures`, `Subject`, `normalize_subject_name` from `smart_tutor.subjects.domain.subject` (integration tests may import domain directly, as the knowledge integration tests do).

- [ ] **Step 3: Extend the port** `subjects/ports/subject_repository.py` with the abstract methods listed under Interfaces (docstrings say what each returns; `insert_or_get`: "Insert unless the normalized name exists; concurrent callers get one row").

- [ ] **Step 4: Implement `SqlSubjectRepository`.** Table gains `normalized_name` (Text) and `name_embedding` (`Vector(1024)`; define `NAME_EMBEDDING_DIM = 1024` locally — `subjects` can't import `knowledge`). Pattern for insert-or-get, mirroring `knowledge/adapters/sql_library.py::_Contents.insert_or_get`:

```python
def insert_or_get(self, subject: Subject, normalized_name: str, name_embedding: Sequence[float]) -> Subject:
    with self._engine.begin() as conn:
        inserted = conn.execute(
            insert(_subjects)
            .values(subject_id=subject.subject_id, canonical_name=subject.canonical_name,
                    normalized_name=normalized_name, name_embedding=list(name_embedding))
            .on_conflict_do_nothing(index_elements=["normalized_name"])
            .returning(_subjects.c.subject_id)
        ).first()
        if inserted is not None:
            return subject
        # READ COMMITTED: this statement sees the row the concurrent winner committed.
        row = conn.execute(select(_subjects).where(_subjects.c.normalized_name == normalized_name)).one()
        return Subject(SubjectId(row.subject_id), row.canonical_name)

def most_similar(self, embedding: Sequence[float], limit: int) -> list[Candidate]:
    distance = _subjects.c.name_embedding.cosine_distance(list(embedding))
    stmt = (select(_subjects.c.subject_id, _subjects.c.canonical_name, (1 - distance).label("similarity"))
            .where(_subjects.c.name_embedding.is_not(None)).order_by(distance).limit(limit))
    with self._engine.connect() as conn:
        return [Candidate(Subject(SubjectId(r.subject_id), r.canonical_name), float(r.similarity))
                for r in conn.execute(stmt)]
```

`find_by_normalized_names` returns `{}` for an empty input without querying; `set_name_embedding` uses `engine.begin()`.

- [ ] **Step 5: Extend the fake** `tests/fakes/subjects.py`:

```python
class InMemorySubjects(SubjectRepository):
    """Seeded with General (no embedding, like the migration). Cosine similarity in Python."""

    def __init__(self, names: dict[SubjectId, str] | None = None,
                 embeddings: dict[SubjectId, list[float]] | None = None) -> None:
        self.names = {GENERAL_SUBJECT_ID: "General"} if names is None else dict(names)
        self.embeddings = dict(embeddings or {})
    # canonical_names as before
    # most_similar: cosine over self.embeddings, highest first, [:limit]
    # find_by_normalized_names: {normalize_subject_name(n): Subject(id, n)} filtered
    # insert_or_get: reuse by normalized name, else store names/embeddings
    # missing_name_embeddings / set_name_embedding
```

Fakes import from `smart_tutor.subjects.application` where possible; `Subject`, `Candidate`, `normalize_subject_name` are exported from there in Task 3, so in this task import them from `smart_tutor.subjects.domain...` and switch in Task 3 if you prefer — both are allowed for tests.

Add a unit test `tests/unit/subjects/test_fake_subjects.py` that pins the fake against the same behaviors as the SQL tests (insert-or-get reuse, cosine order, missing embeddings), so unit tests trust it.

- [ ] **Step 6: Run** `uv run pytest tests/unit -q`, then with Compose up `uv run --env-file ../.env pytest -m integration tests/integration/subjects tests/integration/shared/test_migrations.py -q` — PASS. If Compose isn't running, run `docker compose up -d postgres` from the repo root first (port 10400).

- [ ] **Step 7: Commit** ("Store subject name embeddings and get-or-create subjects by normalized name"; body: unique `normalized_name` makes concurrent creation resolve to one row; similarity search feeds suggestions).

---

### Task 3: Subjects application: catalog service and suggester

**Files:**
- Create: `backend/src/smart_tutor/subjects/application/catalog.py`, `backend/src/smart_tutor/subjects/application/suggester.py`
- Modify: `backend/src/smart_tutor/subjects/application/__init__.py`, `backend/src/smart_tutor/subjects/README.md`
- Test: `backend/tests/unit/subjects/test_catalog.py`, `backend/tests/unit/subjects/test_suggester.py`

**Interfaces:**
- Consumes: Task 1 domain, Task 2 port.
- Produces:
  - `SubjectCatalogService(repo: SubjectRepository, embeddings: Embeddings, new_id: Callable[[], str] = lambda: str(uuid.uuid4()))`
    - `get_or_create(name: str) -> SubjectId` — clean (raises `InvalidSubjectNameError`), reuse an exact normalized match without embedding, else embed the cleaned name and `insert_or_get`.
    - `unknown(subject_ids: Collection[SubjectId]) -> set[SubjectId]` — ids not in the catalog.
    - `embed_missing_names(batch: int = 100) -> int` — embeds every subject without `name_embedding`; returns how many.
  - `SubjectSuggester(repo: SubjectRepository, names: SubjectNames, threshold: float = MATCH_THRESHOLD, boost: float = YOURS_BOOST, nearest: int = 10)`
    - `suggest(user_id: UserId, summary_embedding: Sequence[float] | None, proposed_names: Sequence[str], learner_subject_ids: Collection[SubjectId]) -> list[Suggestion]`
  - `subjects.application.__all__` adds: `Suggestion`, `SuggestionOrigin`, `SubjectCatalogService`, `SubjectSuggester`, `InvalidSubjectNameError`, `normalize_subject_name`, `Subject`, `Candidate`.

- [ ] **Step 1: Failing tests** `tests/unit/subjects/test_catalog.py`:

```python
from fakes import InMemorySubjects, fake_embeddings
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.application import GENERAL_SUBJECT_ID, InvalidSubjectNameError, SubjectCatalogService
import pytest


def service(repo: InMemorySubjects) -> SubjectCatalogService:
    ids = iter(f"s{i}" for i in range(100))
    return SubjectCatalogService(repo, fake_embeddings(8), new_id=lambda: next(ids))


def test_a_new_name_creates_one_subject_with_its_embedding_and_is_reused_after() -> None:
    repo = InMemorySubjects()
    created = service(repo).get_or_create("  Machine   Translation ")
    assert repo.names[created] == "Machine Translation" and len(repo.embeddings[created]) == 8
    assert service(repo).get_or_create("machine translation") == created
    assert len(repo.names) == 2  # General + the new one


def test_an_existing_name_is_reused_without_embedding() -> None:
    assert service(InMemorySubjects()).get_or_create("GENERAL") == GENERAL_SUBJECT_ID


def test_an_invalid_name_is_rejected() -> None:
    with pytest.raises(InvalidSubjectNameError):
        service(InMemorySubjects()).get_or_create("x" * 61)


def test_unknown_lists_ids_not_in_the_catalog() -> None:
    assert service(InMemorySubjects()).unknown([GENERAL_SUBJECT_ID, SubjectId("nope")]) == {SubjectId("nope")}


def test_embed_missing_names_backfills_the_seeded_general() -> None:
    repo = InMemorySubjects()
    assert service(repo).embed_missing_names() == 1
    assert len(repo.embeddings[GENERAL_SUBJECT_ID]) == 8 and service(repo).embed_missing_names() == 0
```

`tests/unit/subjects/test_suggester.py` — wire `InMemorySubjects` with embeddings from `fake_embeddings(8)` so a summary equal to a subject name's text gets similarity 1.0 (the fake is deterministic per text):

```python
def test_suggest_uses_similarity_the_learners_subjects_and_new_names() -> None:
    emb = fake_embeddings(8)
    nlp, cook = SubjectId("s-nlp"), SubjectId("s-cook")
    repo = InMemorySubjects({GENERAL_SUBJECT_ID: "General", nlp: "NLP", cook: "Cooking"},
                            {nlp: emb.embed_query("NLP"), cook: emb.embed_query("Cooking")})
    suggester = SubjectSuggester(repo, SubjectNames(repo))
    got = suggester.suggest(UserId("ada"), emb.embed_query("NLP"), ["Cooking", "Machine Translation", "Attention"], [])
    assert got == [
        Suggestion("NLP", SuggestionOrigin.SHARED, nlp),           # similarity 1.0
        Suggestion("Cooking", SuggestionOrigin.SHARED, cook),      # proposed name equals an existing subject
        Suggestion("Machine Translation", SuggestionOrigin.NEW),
    ]


def test_suggest_without_a_summary_offers_the_learners_subjects() -> None:
    repo = InMemorySubjects()
    got = SubjectSuggester(repo, SubjectNames(repo)).suggest(UserId("ada"), None, [], [GENERAL_SUBJECT_ID])
    assert got == [Suggestion("General", SuggestionOrigin.YOURS, GENERAL_SUBJECT_ID)]
```

Note the expected order in the first test: NLP (1.0) and Cooking (exact 1.0) tie; ties sort by name, so "Cooking" would come first. Adjust: make the test summary `emb.embed_query("NLP")`, and assert set membership and the NEW name last, OR change the exact score to tie-break after similarity. Keep `_EXACT = 1.0` and assert `{got[0].subject_id, got[1].subject_id} == {nlp, cook}` and `got[2] == Suggestion("Machine Translation", SuggestionOrigin.NEW)`.

- [ ] **Step 2: Run** — fail (ImportError).

- [ ] **Step 3: Implement** `catalog.py` and `suggester.py`:

```python
class SubjectSuggester:
    def suggest(self, user_id, summary_embedding, proposed_names, learner_subject_ids):  # typed as in Interfaces
        similar = self._repo.most_similar(summary_embedding, self._nearest) if summary_embedding else []
        existing = self._repo.find_by_normalized_names({normalize_subject_name(n) for n in proposed_names})
        yours = self._names.names_for(user_id, learner_subject_ids)
        general = Subject(GENERAL_SUBJECT_ID, self._names.names_for(user_id, [GENERAL_SUBJECT_ID]).get(GENERAL_SUBJECT_ID, "General"))
        return rank_suggestions(similar=similar, proposed_names=proposed_names, existing_by_name=existing,
                                yours=yours, fallback=general, threshold=self._threshold, boost=self._boost)
```

`SubjectCatalogService.get_or_create`: `name = clean_subject_name(raw)`; `key = normalize_subject_name(name)`; `found = repo.find_by_normalized_names([key]).get(key)`; return `found.subject_id` if found; else `[vector] = embeddings.embed_documents([name])`; `return repo.insert_or_get(Subject(SubjectId(new_id()), name), key, vector).subject_id`. `embed_missing_names`: loop `missing_name_embeddings(batch)` until empty; embed canonical names in one `embed_documents` call per batch.

- [ ] **Step 4: Export** from `subjects/application/__init__.py` (keep `GENERAL_SUBJECT_ID`, `SubjectNames`, `SubjectRepository`).

- [ ] **Step 5: README** `subjects/README.md` "Present now": `Subject`, name cleaning/normalization, `rank_suggestions`; services `SubjectCatalogService` (get-or-create, unknown ids, backfill of name embeddings), `SubjectSuggester`; `GENERAL_SUBJECT_ID` is now only the last-resort suggestion. "May use": add that it takes LangChain `Embeddings` (from `ModelFactory`).

- [ ] **Step 6: Run** `uv run pytest tests/unit/subjects -q && uv run mypy && PYTHONUTF8=1 uv run lint-imports` — PASS.

- [ ] **Step 7: Commit** ("Suggest subjects and get-or-create them through subjects.application").

---

### Task 4: Documents wait for subjects instead of getting "General"

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/domain/document.py`, `backend/src/smart_tutor/knowledge/domain/errors.py`, `backend/src/smart_tutor/knowledge/ports/library.py`, `backend/src/smart_tutor/knowledge/adapters/sql_library.py`, `backend/src/smart_tutor/knowledge/application/ingestion_service.py`, `backend/tests/fakes/knowledge.py`
- Test: `backend/tests/unit/knowledge/test_domain.py`, `backend/tests/unit/knowledge/test_processing.py` (and any test using `document.ready(` or asserting General after processing: `grep -rn "GENERAL_SUBJECT_ID\|\.ready(\[" backend/tests`), `backend/tests/integration/knowledge/test_sql_library.py`

**Interfaces:**
- Produces:
  - `Document.await_subjects() -> None` — `processing` with content → `awaiting_subjects`; else `DocumentStateError`.
  - `Document.choose_subjects(subject_ids: list[SubjectId]) -> None` — state must be `awaiting_subjects` or `ready` (else `DocumentStateError("Subjects can be chosen once processing has finished")`); 1–3 distinct (else `InvalidSubjectsError("Choose 1 to 3 different subjects")`); sets subjects and `ready`.
  - `Document.ready(...)` is **removed**.
  - `InvalidSubjectsError(DomainError)`, `DocumentNotFoundError(DomainError)` in `knowledge/domain/errors.py`.
  - `DocumentRepository.get_readable(user_id: UserId, document_id: DocumentId, *, for_update: bool = False) -> Document | None` — `can_read` in storage, non-archived only (US-10: an archived document's subjects can't change), with `content_title` filled (use `with_for_update(of=documents)` so the outer join to `contents` can be locked-for-update on documents only).
  - `DocumentRepository.subject_ids_readable_by(user_id: UserId) -> set[SubjectId]` — distinct subjects of the caller's `ready`, non-archived documents (PRD §9.4 "Learner's subjects").

- [ ] **Step 1: Failing domain tests** (in `test_domain.py`; replace tests that used `document.ready(...)`):

```python
def processed() -> Document:
    doc = Document.start_upload(DocumentId("d1"), UserId("ada"), UploadId("u1"), "a.pdf", NOW)
    doc.link_content(ContentId("c1"))
    return doc


def test_a_processed_document_waits_for_subjects() -> None:
    doc = processed()
    doc.await_subjects()
    assert doc.state is DocumentState.AWAITING_SUBJECTS and doc.subject_ids == []


def test_choosing_1_to_3_distinct_subjects_makes_it_ready() -> None:
    doc = processed()
    doc.await_subjects()
    doc.choose_subjects([SubjectId("s1"), SubjectId("s2")])
    assert (doc.state, doc.subject_ids) == (DocumentState.READY, ["s1", "s2"])
    doc.choose_subjects([SubjectId("s3")])  # a ready document accepts a new choice
    assert doc.subject_ids == ["s3"]


@pytest.mark.parametrize("ids", [[], ["s1", "s2", "s3", "s4"], ["s1", "s1"]])
def test_zero_more_than_three_or_duplicate_subjects_are_rejected(ids: list[str]) -> None:
    doc = processed()
    doc.await_subjects()
    with pytest.raises(InvalidSubjectsError):
        doc.choose_subjects([SubjectId(i) for i in ids])
    assert doc.state is DocumentState.AWAITING_SUBJECTS


def test_only_a_processed_document_accepts_subjects() -> None:
    doc = processed()  # still processing
    with pytest.raises(DocumentStateError):
        doc.choose_subjects([SubjectId("s1")])
    doc.fail("x")
    with pytest.raises(DocumentStateError):
        doc.choose_subjects([SubjectId("s1")])


def test_only_a_processing_document_with_content_can_wait_for_subjects() -> None:
    doc = Document.start_upload(DocumentId("d1"), UserId("ada"), UploadId("u1"), "a.pdf", NOW)
    with pytest.raises(DocumentStateError):
        doc.await_subjects()
```

- [ ] **Step 2: Run** — fail.

- [ ] **Step 3: Implement** the domain changes (keep `MAX_SUBJECTS`); docstring of `await_subjects`: "processing → awaiting_subjects when its content is ready (PRD §9.5); the learner then chooses 1–3 subjects."

- [ ] **Step 4: Ingestion.** In `IngestionService.process_content`, replace `document.ready([GENERAL_SUBJECT_ID])` with `document.await_subjects()`, drop the `GENERAL_SUBJECT_ID` import, and update the docstrings ("make it ready, and the documents waiting on it wait for subjects"). Update `test_processing.py` expectations: documents end `awaiting_subjects` with no subjects. Add one test that a document already `ready` with General (from before this change) is untouched by a later reprocess — not needed: `list_processing_for_content_for_update` only returns processing documents; skip.

- [ ] **Step 5: Ports, fake, SQL.** Add the two repository methods. Fake (`tests/fakes/knowledge.py`): `get_readable` = owner match and not archived (the fake `Document` has no `archived` field; treat all as non-archived) with `content_title` filled like `list_readable_by`; `subject_ids_readable_by` = union of `subject_ids` of the caller's `READY` documents. SQL:

```python
def get_readable(self, user_id, document_id, *, for_update=False):
    stmt = (select(documents, contents.c.title.label("content_title"))
            .select_from(documents.outerjoin(contents, documents.c.content_id == contents.c.content_id))
            .where(documents.c.document_id == document_id, readable_by(user_id), documents.c.archived.is_(False)))
    if for_update:
        stmt = stmt.with_for_update(of=documents)
    row = self._conn.execute(stmt).first()
    return self._load([row])[0] if row else None

def subject_ids_readable_by(self, user_id):
    rows = self._conn.execute(
        select(document_subjects.c.subject_id).distinct()
        .select_from(document_subjects.join(documents, document_subjects.c.document_id == documents.c.document_id))
        .where(readable_by(user_id), documents.c.archived.is_(False), documents.c.state == DocumentState.READY.value))
    return {SubjectId(str(r.subject_id)) for r in rows}
```

Integration tests in `tests/integration/knowledge/test_sql_library.py`: replace the existing "ready with General" flow with `await_subjects` → `choose_subjects([GENERAL_SUBJECT_ID])`; add `get_readable` returns None for another owner and `subject_ids_readable_by` returns only ready documents' subjects. Read the file first and follow its helpers.

- [ ] **Step 6: Run** `uv run pytest -q` (unit) and the knowledge integration tests — PASS. Fix every remaining `document.ready(` usage (`grep -rn "\.ready(\[" backend`).

- [ ] **Step 7: Commit** ("Make processed documents wait for subjects instead of getting General"; body: removes the interim step from #69/US-2; documents that already have General keep it).

---

### Task 5: SubjectChoiceService (knowledge application)

**Files:**
- Create: `backend/src/smart_tutor/knowledge/application/subject_choice.py`
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py`, `backend/src/smart_tutor/knowledge/application/__init__.py`, `backend/src/smart_tutor/knowledge/README.md`
- Test: `backend/tests/unit/knowledge/test_subject_choice.py`

**Interfaces:**
- Consumes: `SubjectSuggester`, `SubjectCatalogService`, `Suggestion`, `normalize_subject_name`, `InvalidSubjectNameError` from `smart_tutor.subjects.application`; Task 4 repository methods and errors.
- Produces:
  - `document_view(d: Document) -> DocumentView` in `document_service.py` (used by `list_documents` too).
  - `@dataclass(frozen=True) class SubjectSuggestions: document_id: DocumentId; title: str; summary: str | None; suggestions: list[Suggestion]`.
  - `SubjectChoiceService(uow: Callable[[], LibraryUnitOfWork], suggester: SubjectSuggester, catalog: SubjectCatalogService)`
    - `suggestions(user_id: UserId, document_id: DocumentId) -> SubjectSuggestions` — raises `DocumentNotFoundError` (not readable), `DocumentStateError` (not `awaiting_subjects`/`ready`).
    - `choose(user_id: UserId, document_id: DocumentId, subject_ids: list[SubjectId], new_names: list[str]) -> DocumentView` — raises `DocumentNotFoundError`, `DocumentStateError`, `InvalidSubjectsError`.
  - `knowledge.application.__all__` adds `SubjectChoiceService`, `SubjectSuggestions`, `DocumentNotFoundError`, `DocumentStateError`, `InvalidSubjectsError`.

- [ ] **Step 1: Failing tests.** Build an awaiting document by running the real `IngestionService` with fakes (see `tests/isolation/test_documents.py::setup` and `tests/unit/knowledge/test_processing.py` for helpers), so the content has `DESCRIPTION_ARGS` (`proposed_subject_names = ["Deep Learning", "Natural Language Processing", "Machine Translation"]`, summary embedded with `fake_embeddings(8)`):

```python
def test_suggestions_offer_three_new_names_on_an_empty_catalog() -> None
    # summary == DESCRIPTION_ARGS["summary"], three NEW suggestions in model order, title == DESCRIPTION_ARGS["title"]

def test_choosing_a_new_name_creates_the_subject_and_makes_the_document_ready() -> None
    # choose(..., [], ["Machine Translation"]) -> view.state == "ready", subject id resolves to "Machine Translation"
    # a second learner's document choosing "machine translation" reuses the same subject id

def test_choosing_an_existing_subject_by_id() -> None
    # choose(..., [GENERAL_SUBJECT_ID], []) -> ready with General

def test_unknown_ids_are_rejected_and_nothing_changes() -> None
    # SubjectId("00000000-0000-4000-8000-0000000000ff") -> InvalidSubjectsError; document still awaiting_subjects

def test_a_name_that_was_not_suggested_is_rejected() -> None
    # new_names=["Cooking"] -> InvalidSubjectsError("Choose from the suggestions"); catalog unchanged

@pytest.mark.parametrize("ids,names", [([], []), (four ids, []), ([G, G], []), ([], ["Deep Learning"] * 2)])
def test_zero_more_than_three_or_duplicates_are_rejected(...) -> None

def test_a_new_name_resolving_to_a_chosen_subject_is_a_duplicate() -> None
    # create "Deep Learning" first via catalog, then choose([dl_id], ["Deep Learning"]) -> InvalidSubjectsError, still awaiting

def test_another_learners_document_is_not_found() -> None
    # suggestions and choose for user "bob" -> DocumentNotFoundError

def test_a_processing_document_has_no_suggestions_and_takes_no_subjects() -> None
    # started upload only -> DocumentStateError for both; state unchanged

def test_without_a_description_the_picker_still_has_a_suggestion() -> None
    # ingestion with a chat model replying without a tool call (see test_first_pages.py for the fake) -> suggestions == [General (shared)]
```

Write each test fully (arrange via the fakes, act, assert); the comments above are the assertions to make.

- [ ] **Step 2: Run** — fail.

- [ ] **Step 3: Implement**:

```python
"""Choose a document's subjects from its suggestions (PRD §8 US-2b, D20, §9.2 step 5; ADR 0004)."""

CHOOSABLE = (DocumentState.AWAITING_SUBJECTS, DocumentState.READY)


class SubjectChoiceService:
    def suggestions(self, user_id, document_id) -> SubjectSuggestions:
        with self._uow() as tx:
            document = self._choosable(tx, user_id, document_id)
            content = tx.contents.get(document.content_id) if document.content_id else None
            yours = tx.documents.subject_ids_readable_by(user_id)
        suggestions = self._suggester.suggest(
            user_id,
            content.summary_embedding if content else None,
            content.proposed_subject_names if content else [],
            yours,
        )
        return SubjectSuggestions(document.document_id, document.title, content.summary if content else None, suggestions)

    def choose(self, user_id, document_id, subject_ids, new_names) -> DocumentView:
        if not 1 <= len(subject_ids) + len(new_names) <= MAX_SUBJECTS:
            raise InvalidSubjectsError("Choose 1 to 3 different subjects")
        with self._uow() as tx:
            document = self._choosable(tx, user_id, document_id)
            content = tx.contents.get(document.content_id) if document.content_id else None
        proposed = {normalize_subject_name(n) for n in (content.proposed_subject_names if content else [])}
        if any(normalize_subject_name(n) not in proposed for n in new_names):
            raise InvalidSubjectsError("Choose from the suggestions")  # typed names come with the next slice
        if self._catalog.unknown(subject_ids):
            raise InvalidSubjectsError("Unknown subject")
        if len({normalize_subject_name(n) for n in new_names}) != len(new_names) or len(set(subject_ids)) != len(subject_ids):
            raise InvalidSubjectsError("Choose 1 to 3 different subjects")  # before creating anything
        try:
            created = [self._catalog.get_or_create(name) for name in new_names]
        except InvalidSubjectNameError as e:
            raise InvalidSubjectsError(str(e)) from None
        with self._uow() as tx:
            document = self._choosable(tx, user_id, document_id, for_update=True)
            document.choose_subjects([*subject_ids, *created])
            tx.documents.save(document)
            tx.commit()
        return document_view(document)

    @staticmethod
    def _choosable(tx, user_id, document_id, *, for_update=False) -> Document:
        document = tx.documents.get_readable(user_id, document_id, for_update=for_update)
        if document is None:
            raise DocumentNotFoundError("This document isn't in your library")
        if document.state not in CHOOSABLE:
            raise DocumentStateError("Subjects can be chosen once processing has finished")
        return document
```

Subjects are created before the document transaction (they live in another module's store; a created subject that ends up unused is harmless — it's a shared name the model proposed). Say so in a comment.

- [ ] **Step 4: README** `knowledge/README.md`: replace the "Interim until US-2b…" sentence with: "When its content becomes `ready`, a processing document goes to `awaiting_subjects`; `SubjectChoiceService` serves its suggestions (from `subjects.application.SubjectSuggester`, with the learner's subjects = their ready, non-archived documents' subjects) and saves 1–3 chosen subjects (existing ids, or proposed names through `SubjectCatalogService.get_or_create`), which makes it `ready` and searchable." Add `SubjectChoiceService` to Key classes.

- [ ] **Step 5: Run** `uv run pytest tests/unit -q && uv run mypy && PYTHONUTF8=1 uv run lint-imports` — PASS.

- [ ] **Step 6: Commit** ("Serve subject suggestions and save the learner's choice").

---

### Task 6: API routes, wiring, worker backfill, isolation tests, API client

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py`, `backend/src/smart_tutor/apps/api/services.py`, `backend/src/smart_tutor/apps/api/deps.py`, `backend/src/smart_tutor/apps/worker/main.py`, `compose.yaml`
- Test: `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/isolation/test_documents.py`, `backend/tests/unit/apps/worker/*` (if `main` wiring is tested), `backend/tests/isolation/README.md` (list the new endpoints if it lists endpoints)
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`

**Interfaces:**
- Consumes: `SubjectChoiceService`, `SubjectSuggestions`, errors (Task 5); `SubjectCatalogService`, `SubjectSuggester` (Task 3).
- Produces (HTTP, generated TS names in parentheses):
  - `GET /documents/{document_id}/subject-suggestions` (`getSubjectSuggestions`) → `SubjectSuggestionsResponse { document_id: str, title: str, summary: str | None, suggestions: [SuggestionResponse { subject_id: str | None, name: str, origin: "shared" | "yours" | "new" }] }`; `404` not readable; `409` not choosable; `422` malformed id.
  - `PUT /documents/{document_id}/subjects` (`chooseSubjects`) body `ChooseSubjectsRequest { subject_ids: list[UUID] (max 3, default []), new_names: list[str 1..60] (max 3, default []) }`, `extra="forbid"` → `DocumentResponse`; `422` invalid choice; `404`; `409`.
  - `ApiServices.subject_choice: SubjectChoiceService`.

- [ ] **Step 1: Failing route tests** in `test_knowledge_routes.py` (read its setup first; extend its `ApiServices` construction with `subject_choice=SubjectChoiceService(library.unit_of_work, SubjectSuggester(subjects, SubjectNames(subjects)), SubjectCatalogService(subjects, fake_embeddings(8)))`). Tests:
  - suggestions for an awaiting document → 200, 3 suggestions with `origin`, `summary`.
  - PUT with one suggestion → 200, `state == "ready"`, subjects named; then `GET /documents` shows it ready.
  - PUT `{"subject_ids": [], "new_names": []}` → 422; four ids → 422; duplicate ids → 422; unknown id → 422; `{"subject_ids": ["abc"]}` → 422; path `/documents/abc/subjects` → 422; extra field → 422.
  - PUT for a processing document → 409.
  - suggestions/PUT for a random UUID → 404.
- [ ] **Step 2: Run** — fail (404 route not found).
- [ ] **Step 3: Implement routes** (path parameter typed `UUID`, converted with `DocumentId(str(document_id))`; error mapping: `DocumentNotFoundError`→404, `DocumentStateError`→409, `InvalidSubjectsError`→422, all with `detail=str(e)`). The PUT response reuses the `DocumentResponse` shape: build it through a small helper shared with `list_documents` (`_document_response(view, names)`). Update the module docstring.
- [ ] **Step 4: Wiring.** `services.py`: build `subjects = SqlSubjectRepository(engine)`, `names = SubjectNames(subjects)`, `embeddings = ModelFactory(settings).embedding()`, `subject_choice = SubjectChoiceService(library, SubjectSuggester(subjects, names), SubjectCatalogService(subjects, embeddings))`. `deps.py`: `SubjectChoice = Annotated[SubjectChoiceService, Depends(_subject_choice)]`.
- [ ] **Step 5: Worker backfill.** In `apps/worker/main.py::main`, after building `models`: `backfilled = SubjectCatalogService(SqlSubjectRepository(engine), models.embedding()).embed_missing_names(); logger.info("embedded %d subject names", backfilled)` (reuse the one `models.embedding()` instance for tools and catalog).
- [ ] **Step 6: Compose.** Give `api` the same Bedrock access as `worker`: copy the worker's `HOME`/`AWS_PROFILE`-related `environment` entries and `volumes: ["~/.aws:/home/app/.aws:ro"]` with its comment (read `compose.yaml` lines ~151–172 first).
- [ ] **Step 7: Isolation tests** in `tests/isolation/test_documents.py`: extend `setup()` services with `subject_choice`; update `test_b_never_sees_the_subjects_of_a_document` (A's document is now `awaiting_subjects`: A chooses `General` via PUT, then B sees nothing); add:

```python
def test_b_cannot_read_a_suggestions_or_set_a_subjects() -> None:
    client, objects, ingestion = setup()
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])
    doc = stored["document_id"]

    assert client.get(f"/documents/{doc}/subject-suggestions", headers=B).status_code == 404
    put = client.put(f"/documents/{doc}/subjects", json={"new_names": ["Deep Learning"]}, headers=B)
    assert put.status_code == 404
    [mine] = client.get("/documents", headers=A).json()
    assert (mine["state"], mine["subjects"]) == ("awaiting_subjects", [])
    assert client.get(f"/documents/{doc}/subject-suggestions", headers=A).status_code == 200
```

- [ ] **Step 8: Regenerate the client:** `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Confirm `sdk.gen.ts` exports `getSubjectSuggestions` and `chooseSubjects`.
- [ ] **Step 9: Run** the full backend checks (Global Constraints) — PASS, including `test_openapi_snapshot`.
- [ ] **Step 10: Commit** ("Expose subject suggestions and saving in the API").

---

### Task 7: Web building blocks: SubjectChip, Dialog, Banner, API wrappers

**Files:**
- Create: `web/src/components/SubjectChip/SubjectChip.tsx`, `.module.css`, `.test.tsx`; `web/src/components/Dialog/Dialog.tsx`, `.module.css`, `.test.tsx`; `web/src/components/Banner/Banner.tsx`, `.module.css`
- Modify: `web/src/api/documents.ts`, `web/src/api/documents.test.ts`

**Interfaces:**
- Produces:
  - `SubjectChip({ name, hueKey, size?: "sm" | "md", origin?: string, pressed?: boolean, disabled?: boolean, onToggle?: () => void })` — without `onToggle` renders a `<span>` chip; with it, a `<button type="button" aria-pressed>` with a check icon when pressed and the origin as `· {origin}` after the name. Hue: `subjectHue(hueKey)` maps a stable hash of `hueKey` (subject id, or the name for a new subject) onto `["llm","agents","rag","rl","tool","other"]` → `var(--subj-…)` for the dot only; chip text stays `--text` (prototype: "Chip text always uses the main text colour").
  - `Dialog({ title, kicker?, onClose, children, footer })` — scrim + `role="dialog" aria-modal="true" aria-labelledby`, focuses the first focusable element (or `[data-autofocus]`) on mount, `Escape` and the close icon button (`aria-label="Close"`) call `onClose`, restores focus to the previously focused element on unmount, Tab cycles inside.
  - `Banner({ variant: "success", title, children })` — `role` left to the caller.
  - `api/documents.ts`: `export type SubjectSuggestions = SubjectSuggestionsResponse; export type Suggestion = SuggestionResponse;` `loadSubjectSuggestions(documentId: string, apiClient?) : Promise<SubjectSuggestions>`; `saveSubjects(documentId: string, choice: { subject_ids: string[]; new_names: string[] }, apiClient?): Promise<DocumentResponse>` — both throw `SessionExpiredError` on 401 like the others, and `Error` with the server's `detail` when present.

- [ ] **Step 1: Failing tests**: SubjectChip renders name and origin; toggle has `aria-pressed` and calls `onToggle`; disabled button doesn't call it; same `hueKey` → same hue. Dialog: labelled by its title, Escape calls `onClose`, close button calls `onClose`, focus moves inside on open. `documents.test.ts`: follow the existing tests' fake-client pattern for `loadSubjectSuggestions` (200 → data; 401 → SessionExpiredError) and `saveSubjects` (sends the body to `PUT /documents/d1/subjects`; 422 → Error).
- [ ] **Step 2: Run** `cd web && npx vitest run src/components src/api` — fail.
- [ ] **Step 3: Implement** with tokens only (DESIGN.md → Tokens). Port the look from the prototype classes `.schip`, `.dialog`, `.dialog-scrim`, `.banner-success` (read them in `git show design-v0.4:sdd/design/prototype/styles.css`), never copy the prototype's HTML or CSS verbatim; scrim colour and dialog shadow must be tokens (add to `tokens.css` in both themes if missing). Icons from `lucide-react` with `strokeWidth={1.5}`.
- [ ] **Step 4: Run** tests and `npm run build` — PASS.
- [ ] **Step 5: Commit** ("Add SubjectChip, Dialog and Banner components and subject API calls").

---

### Task 8: The picker and the Library row action

**Files:**
- Create: `web/src/features/library/SubjectPicker.tsx`, `SubjectPicker.module.css`, `SubjectPicker.test.tsx`
- Modify: `web/src/features/library/DocumentTable.tsx`, `DocumentTable.module.css`, `LibraryPage.tsx`, `LibraryPage.test.tsx`

**Interfaces:**
- Consumes: Task 7 components and API functions.
- Produces: `SubjectPicker({ document: DocumentResponse, load?: (id) => Promise<SubjectSuggestions>, save?: (id, choice) => Promise<DocumentResponse>, onClose: () => void, onSaved: (doc: DocumentResponse) => void })`; `DocumentTable({ documents, onChooseSubjects?: (doc) => void })`; `LibraryPage` props gain `loadSuggestions?` and `saveSubjects?` (defaults to the API functions) for tests.

Behavior (match `picker-default`, `picker-none-selected`, `picker-maximum`, `picker-saved`):
- Kicker "Processing finished" (for a `ready` document: "Ready document"), title **"Choose subjects"**.
- Summary card: document title (display font), then `summary` when present.
- Fieldset legend "Suggested subjects" with a polite counter: "`n` of 3 selected", or "3 of 3 selected · the maximum".
- One `SubjectChip` toggle per suggestion with origin label ("Shared subject" / "Your subject" / "New"); **the first suggestion is pre-selected**; when 3 are selected, unselected chips are disabled and a helper reads "You've chosen 3 subjects, the maximum. Remove one to add another."
- Footer: Cancel (secondary), Save (primary). **Save is disabled with nothing selected**, `aria-describedby` a visually hidden "Choose at least one subject to save."
- Save sends `subject_ids` (selected suggestions with an id) and `new_names` (selected `new` suggestions' names). While saving, Save is disabled. On error: an inline error "Couldn't save subjects. Try again." (422/409 detail shown after it when present).
- Saved state: success `Banner` titled **"Subjects saved."** with "*Title* is ready to use." (title in `<em>`), the saved subjects as chips, and a **Done** button (autofocused) that closes. `onSaved(doc)` is called once.
- Loading state: "Loading suggestions…"; load failure: "Couldn't load suggestions. Try again." with a Retry button.
- `DocumentTable`: add a last column (header visually hidden "Actions"); `awaiting_subjects` rows get `<Button size="sm" variant="primary">Choose subjects</Button>` (button name includes the title for screen readers via `aria-label={`Choose subjects for ${doc.title}`}`). Other rows: empty cell. Keep the existing processing hint.
- `LibraryPage`: holds `picking: DocumentResponse | null`; renders `SubjectPicker` when set; `onSaved` → `setStatus(`Subjects saved. ${doc.title} is ready to use.`)` and `await refresh()`; mark the doc's state in `seen` as `ready` so the poll doesn't announce "is ready." again.

- [ ] **Step 1: Failing tests** `SubjectPicker.test.tsx` (fake `load`/`save` with `vi.fn`):

```tsx
const suggestions: SubjectSuggestions = {
  document_id: "d1", title: "Toolformer", summary: "Teaches a language model to call tools.",
  suggestions: [
    { subject_id: "s-agents", name: "AI Agents", origin: "yours" },
    { subject_id: "s-llm", name: "LLMs", origin: "shared" },
    { subject_id: null, name: "Tool Use", origin: "new" },
  ],
};
// default: title, summary, three chips with origins, first pressed, counter "1 of 3 selected", Save enabled
// none selected: unpress the first → "0 of 3 selected", Save disabled
// maximum: press the other two → "3 of 3 selected · the maximum", helper shown; with 4 suggestions the 4th is disabled
// saved: Save → save called with ("d1", { subject_ids: ["s-agents"], new_names: ["Tool Use"] }) when those are pressed;
//        banner "Subjects saved." and "Toolformer is ready to use."; onSaved called; Done calls onClose
// save failure → "Couldn't save subjects. Try again."; picker stays open with the selection
```

`LibraryPage.test.tsx`: an `awaiting_subjects` row shows a "Choose subjects for <title>" button and the "Choose subjects" badge; a `processing` row has no such button; clicking opens the dialog (`getByRole("dialog", { name: "Choose subjects" })`); after saving, the status region reads "Subjects saved. <title> is ready to use." and `load` was called again.

- [ ] **Step 2: Run** `npx vitest run src/features/library` — fail.
- [ ] **Step 3: Implement** the picker, table column and page wiring.
- [ ] **Step 4: Run** `npm test && npm run build` — PASS.
- [ ] **Step 5: Look at it.** Start the stack (`docker compose up -d`, `make migrate`, run api/worker/web on the host per README "Run the app", or `docker compose --profile app up -d --build`), upload a PDF as `learner@example.com`, wait for *Choose subjects*, open the picker, compare with `.design-shots/v0.4/picker-*.png` in light and dark, then save. This is also acceptance criterion 1 ("In Compose, an uploaded PDF reaches *choose subjects*…"). Record what you verified.
- [ ] **Step 6: Commit** ("Choose subjects from the Library with a picker").

---

### Task 9: PRD and docs

**Files:**
- Modify: `sdd/prd.md`, `AGENTS.md`

- [ ] **Step 1:** `sdd/prd.md`: status line `Draft v2.17` → `Draft v2.18`; add the row `| **Changes from v2.17** | US-2b first slice (#77): when its content becomes ready, a document goes to *choose subjects* (`awaiting_subjects`) with 3 suggestions; the interim "General" step is removed (documents that already have "General" keep it). |` above the v2.16 row; in §9.5 delete the line "Interim until US-2b (#10): …".
- [ ] **Step 2:** `AGENTS.md`: `sdd/prd.md` (v2.17) → (v2.18).
- [ ] **Step 3:** `grep -rn "Interim until US-2b\|General\" and goes straight" sdd backend/src` — nothing left except history rows in the PRD change log.
- [ ] **Step 4: Commit** ("PRD v2.18: documents wait for subjects; remove the interim General step").

---

## Final verification (before the PR)

- Backend checks, web `npm run build && npm test`, `cd web && npm run test:design` unaffected.
- Acceptance criteria of #77 each mapped to a test or the manual Compose run (Task 8 Step 5).
- PR into `main` closing #77; description lists the Decisions above, the Compose `api` `~/.aws` mount, and any mockup/PRD differences.

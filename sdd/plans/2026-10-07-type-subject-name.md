# Type a subject name with type-ahead (#78) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the Choose subjects picker, the learner can type a subject name: type-ahead searches the shared catalog (their own subjects first), picking a result adds it, and an unmatched name (trimmed, ≤ 60 characters) is saved through the existing get-or-create.

**Architecture:** `subjects` gains a catalog search (repository `search` + pure ranking in the domain + `SubjectSearch` service). `knowledge.SubjectChoiceService` gains `search(user_id, query)` (it owns the learner's subject ids) and stops rejecting typed names in `choose`. A new `GET /subjects/search?q=` route serves it; the web picker gets an "Add your own" combobox.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy Core + Postgres, pytest; React + TypeScript + Vite, Vitest + Testing Library.

**Spec:** GitHub issue #78; PRD `sdd/prd.md` §8 US-2b, D20, D21, §9.4 (subject names resolved at read time); mockups v0.4 `picker-typeahead`, `picker-too-long`.

## Global Constraints

- Store and send `subject_id`s; names are resolved at read time through `SubjectNames.names_for` (personal name later, US-10b; canonical name now).
- Max subject name: **60 characters** after trimming (`MAX_SUBJECT_NAME` in `subjects/domain/subject.py`). 61+ → API `422`.
- Normalization = `normalize_subject_name` (NFKC, casefold, single spaces). An exact normalized match reuses the subject (`SubjectCatalogService.get_or_create`).
- 1–3 subjects per document in total (suggestions + typed names).
- The search response contains only `subject_id`, `name`, `origin` (`"yours"` | `"shared"`): never a creator, user id, or another learner's personal name. Shared results use the **canonical** name.
- `subjects` must not import `knowledge` (import-linter). `knowledge` imports only `smart_tutor.subjects.application`.
- Copy (from the mockups): label "Add your own"; hint "Subject names are visible to everyone. Don't include personal information."; counter `n/60`; error "Subject names can be up to 60 characters."; options labelled "Your subject", "Shared subject", and `Create "<name>"` with "New subject, visible to everyone".
- Out of scope: near-duplicate reuse and the personal-data/offensive check (#79).
- Mockup vs ticket: the ticket says Save is blocked while the typed name is over 60; the mockup leaves Save enabled. Follow the ticket (record it in the PR description).

## Review Focus

1. LIKE wildcards in the query (`%`, `_`, `\`) must match literally, not everything → integration test in Task 1.
2. A query that is blank after trimming returns `[]` without a database call → unit test in Task 1.
3. A typed name that equals (after normalization) an existing subject, or one of the chips already shown, must not create a duplicate → backend test in Task 2, web test in Task 4.
4. Stale type-ahead responses arriving out of order must not overwrite the newer results → web test in Task 4.
5. Escape in the open results list closes the list, not the dialog → web test in Task 4.

---

### Task 1: Catalog search in `subjects`

**Files:**
- Create: `backend/src/smart_tutor/subjects/domain/search.py`
- Create: `backend/src/smart_tutor/subjects/application/search.py`
- Modify: `backend/src/smart_tutor/subjects/ports/subject_repository.py`
- Modify: `backend/src/smart_tutor/subjects/adapters/sql_subjects.py`
- Modify: `backend/src/smart_tutor/subjects/application/__init__.py`
- Modify: `backend/tests/fakes/subjects.py`
- Test: `backend/tests/unit/subjects/test_search.py`, `backend/tests/integration/subjects/test_sql_subjects.py`

**Interfaces:**
- Produces:
  - `SubjectRepository.search(normalized_query: str, exclude: Collection[SubjectId], limit: int) -> list[Subject]` — subjects whose `normalized_name` contains the query, prefix matches first, then shorter names, then by name; `exclude` ids left out.
  - `smart_tutor.subjects.domain.search`: `SEARCH_LIMIT = 8`, `@dataclass(frozen=True) CatalogMatch(subject_id: SubjectId, name: str, origin: SuggestionOrigin)`, `rank_matches(query: str, yours: Mapping[SubjectId, str], shared: Sequence[Subject], limit: int = SEARCH_LIMIT) -> list[CatalogMatch]`.
  - `SubjectSearch(repo, names: SubjectNames)` with `.search(user_id: UserId, query: str, learner_subject_ids: Collection[SubjectId]) -> list[CatalogMatch]`.
  - Exported from `smart_tutor.subjects.application`: `CatalogMatch`, `SubjectSearch`, `SEARCH_LIMIT`.

- [ ] **Step 1: Write the failing unit tests** in `backend/tests/unit/subjects/test_search.py`:

```python
"""US-2b type-ahead: the learner's subjects first (by their names), then shared ones (canonical names)."""

from fakes import InMemorySubjects
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.subjects.application import CatalogMatch, SubjectNames, SubjectSearch, SuggestionOrigin
from smart_tutor.subjects.domain.search import rank_matches
from smart_tutor.subjects.domain.subject import Subject

RAG, IR, RL = SubjectId("s-rag"), SubjectId("s-ir"), SubjectId("s-rl")
ADA = UserId("ada")
YOURS, SHARED = SuggestionOrigin.YOURS, SuggestionOrigin.SHARED


def test_yours_come_first_then_shared_prefix_matches_first() -> None:
    matches = rank_matches(
        "retriev",
        yours={RAG: "Retrieval-Augmented Generation", RL: "Reinforcement Learning"},
        shared=[Subject(IR, "Information Retrieval")],
    )
    assert matches == [
        CatalogMatch(RAG, "Retrieval-Augmented Generation", YOURS),
        CatalogMatch(IR, "Information Retrieval", SHARED),
    ]


def test_your_matches_are_compared_after_normalization_and_ordered_prefix_first() -> None:
    yours = {RAG: "Retrieval-Augmented Generation", IR: "Dense  RETRIEVAL"}
    assert [m.subject_id for m in rank_matches("  RETRIEVAL ", yours=yours, shared=[])] == [RAG, IR]


def test_a_shared_subject_the_learner_has_is_shown_once_as_theirs() -> None:
    matches = rank_matches("rag", yours={RAG: "RAG"}, shared=[Subject(RAG, "RAG")])
    assert matches == [CatalogMatch(RAG, "RAG", YOURS)]


def test_results_are_limited() -> None:
    shared = [Subject(SubjectId(f"s{i}"), f"Topic {i}") for i in range(20)]
    assert len(rank_matches("topic", yours={}, shared=shared, limit=8)) == 8


def test_blank_query_finds_nothing_without_asking_the_catalog() -> None:
    class Exploding(InMemorySubjects):
        def search(self, normalized_query, exclude, limit):  # type: ignore[no-untyped-def]
            raise AssertionError("no query expected")

    assert SubjectSearch(Exploding(), SubjectNames(Exploding())).search(ADA, "   ", set()) == []


def test_search_uses_the_catalog_and_the_learners_subjects() -> None:
    catalog = InMemorySubjects({RAG: "Retrieval-Augmented Generation", IR: "Information Retrieval", RL: "RL"})
    found = SubjectSearch(catalog, SubjectNames(catalog)).search(ADA, "retriev", {RAG})
    assert found == [
        CatalogMatch(RAG, "Retrieval-Augmented Generation", YOURS),
        CatalogMatch(IR, "Information Retrieval", SHARED),
    ]
```

- [ ] **Step 2: Run** `cd backend && uv run pytest tests/unit/subjects/test_search.py -q` → FAIL (ImportError).

- [ ] **Step 3: Implement the domain ranking** `backend/src/smart_tutor/subjects/domain/search.py`:

```python
"""Type-ahead over the shared subject catalog (PRD §8 US-2b): the learner's subjects first, then shared ones."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.subjects.domain.subject import Subject, normalize_subject_name
from smart_tutor.subjects.domain.suggestions import SuggestionOrigin

SEARCH_LIMIT = 8


@dataclass(frozen=True)
class CatalogMatch:
    subject_id: SubjectId
    name: str
    origin: SuggestionOrigin  # YOURS or SHARED


def rank_matches(
    query: str, yours: Mapping[SubjectId, str], shared: Sequence[Subject], limit: int = SEARCH_LIMIT
) -> list[CatalogMatch]:
    """`yours` maps the learner's subjects to their display names; `shared` is already ordered by the catalog.

    Shared subjects the learner has are shown once, as theirs (by their name, never another learner's).
    """
    key = normalize_subject_name(query)
    if not key:
        return []
    mine = [(sid, name) for sid, name in yours.items() if key in normalize_subject_name(name)]
    mine.sort(key=lambda p: (not normalize_subject_name(p[1]).startswith(key), len(p[1]), p[1]))
    matches = [CatalogMatch(sid, name, SuggestionOrigin.YOURS) for sid, name in mine]
    matches += [CatalogMatch(s.subject_id, s.canonical_name, SuggestionOrigin.SHARED) for s in shared if s.subject_id not in yours]
    return matches[:limit]
```

(Wrap lines at the repo's ruff line length; run `uv run ruff format`.)

- [ ] **Step 4: Add the port method** to `SubjectRepository`:

```python
    @abstractmethod
    def search(self, normalized_query: str, exclude: Collection[SubjectId], limit: int) -> list[Subject]:
        """Subjects whose normalized name contains the query (matched literally): prefix matches first, then shorter
        names, then by name. Ids in `exclude` are left out."""
```

- [ ] **Step 5: Implement the service** `backend/src/smart_tutor/subjects/application/search.py`:

```python
"""Catalog search for the subject picker's type-ahead (PRD §8 US-2b, D20)."""

from collections.abc import Collection

from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.subjects.application.subject_names import SubjectNames
from smart_tutor.subjects.domain.search import SEARCH_LIMIT, CatalogMatch, rank_matches
from smart_tutor.subjects.domain.subject import normalize_subject_name
from smart_tutor.subjects.ports.subject_repository import SubjectRepository


class SubjectSearch:
    def __init__(self, repo: SubjectRepository, names: SubjectNames, limit: int = SEARCH_LIMIT) -> None:
        self._repo = repo
        self._names = names
        self._limit = limit

    def search(self, user_id: UserId, query: str, learner_subject_ids: Collection[SubjectId]) -> list[CatalogMatch]:
        key = normalize_subject_name(query)
        if not key:
            return []
        yours = self._names.names_for(user_id, learner_subject_ids)
        shared = self._repo.search(key, exclude=yours.keys(), limit=self._limit)
        return rank_matches(key, yours, shared, self._limit)
```

Export `CatalogMatch`, `SEARCH_LIMIT` (from `subjects.domain.search`) and `SubjectSearch` in `subjects/application/__init__.py` (keep `__all__` sorted).

- [ ] **Step 6: Implement the fake** in `backend/tests/fakes/subjects.py`:

```python
    def search(self, normalized_query: str, exclude: Collection[SubjectId], limit: int) -> list[Subject]:
        skip = set(exclude)
        found = [
            Subject(sid, name)
            for sid, name in self.names.items()
            if sid not in skip and normalized_query in normalize_subject_name(name)
        ]
        found.sort(key=lambda s: (not normalize_subject_name(s.canonical_name).startswith(normalized_query),
                                  len(s.canonical_name), s.canonical_name))
        return found[:limit]
```

- [ ] **Step 7: Run unit tests** → PASS.

- [ ] **Step 8: Write the failing integration tests** in `backend/tests/integration/subjects/test_sql_subjects.py` (append; reuse the module's `engine` fixture and `vec`; create subjects with unique names via `insert_or_get` and a uuid suffix so reruns don't collide):

```python
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
```

- [ ] **Step 9: Run** `cd backend && uv run --env-file ../.env pytest tests/integration/subjects -q -m integration` → FAIL (abstract method / missing).

- [ ] **Step 10: Implement** in `SqlSubjectRepository` (add `func` to the sqlalchemy import):

```python
    def search(self, normalized_query: str, exclude: Collection[SubjectId], limit: int) -> list[Subject]:
        name = _subjects.c.normalized_name
        stmt = select(_subjects.c.subject_id, _subjects.c.canonical_name).where(
            name.contains(normalized_query, autoescape=True)
        )
        if exclude:
            stmt = stmt.where(_subjects.c.subject_id.not_in(list(exclude)))
        stmt = stmt.order_by(
            name.startswith(normalized_query, autoescape=True).desc(),
            func.length(_subjects.c.canonical_name),
            _subjects.c.canonical_name,
        ).limit(limit)
        with self._engine.connect() as conn:
            return [Subject(SubjectId(r.subject_id), r.canonical_name) for r in conn.execute(stmt)]
```

- [ ] **Step 11: Run** unit + integration tests, `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports` → PASS.

- [ ] **Step 12: Commit** — `git commit -m "Search the subject catalog, the learner's subjects first"` (body: why — US-2b type-ahead; the shared list shows canonical names only).

---

### Task 2: Search and typed names in `SubjectChoiceService`

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/application/subject_choice.py`
- Test: `backend/tests/unit/knowledge/test_subject_choice.py`

**Interfaces:**
- Consumes: `SubjectSearch.search(user_id, query, learner_subject_ids) -> list[CatalogMatch]` (Task 1).
- Produces: `SubjectChoiceService(uow, suggester, catalog, search: SubjectSearch, max_attempts)` — **new positional/keyword parameter `search` before `max_attempts`**; `SubjectChoiceService.search(user_id: UserId, query: str) -> list[CatalogMatch]`. `choose` accepts any typed name (no longer limited to the content's proposed names).

- [ ] **Step 1: Update tests.** In `World.__init__` build `SubjectSearch(self.subjects, SubjectNames(self.subjects))` and pass it as `search=`. Replace `test_a_name_that_was_not_suggested_is_rejected` with:

```python
def test_a_typed_name_creates_a_shared_subject() -> None:
    world = World()
    doc = world.upload()
    world.choice.choose(ADA, doc, [], ["  Tool   Use  "])
    [(state, (sid,))] = world.state()
    assert state == "ready" and world.subjects.names[sid] == "Tool Use"


def test_a_typed_name_equal_to_an_existing_subject_after_normalization_reuses_it() -> None:
    world = World()
    existing = world.catalog.get_or_create("Information Retrieval")
    doc = world.upload()
    world.choice.choose(ADA, doc, [], ["ＩＮＦＯＲＭＡＴＩＯＮ  retrieval "])  # NFKC full-width, case, spaces
    assert world.state() == [("ready", (existing,))]


def test_a_typed_name_over_60_characters_is_rejected_and_nothing_changes() -> None:
    world = World()
    doc = world.upload()
    with pytest.raises(InvalidSubjectsError, match="60"):
        world.choice.choose(ADA, doc, [], ["x" * 61])
    assert world.state() == [("awaiting_subjects", ())]


def test_search_puts_the_learners_subjects_first() -> None:
    world = World()
    mine = world.catalog.get_or_create("Retrieval-Augmented Generation")
    shared = world.catalog.get_or_create("Information Retrieval")
    doc = world.upload()
    world.choice.choose(ADA, doc, [mine], [])
    assert [(m.subject_id, m.origin) for m in world.choice.search(ADA, "retriev")] == [
        (mine, SuggestionOrigin.YOURS),
        (shared, SuggestionOrigin.SHARED),
    ]
    assert [m.origin for m in world.choice.search(BOB, "retriev")] == [SuggestionOrigin.SHARED] * 2
```

(Check `world.state()` returns `tuple` subject ids as the existing tests show; adjust only the assertion shape to match.)

- [ ] **Step 2: Run** `uv run pytest tests/unit/knowledge/test_subject_choice.py -q` → FAIL.

- [ ] **Step 3: Implement.** In `subject_choice.py`: import `CatalogMatch, SubjectSearch` from `smart_tutor.subjects.application`; add `search: SubjectSearch` to `__init__` (stored as `self._search`); add

```python
    def search(self, user_id: UserId, query: str) -> list[CatalogMatch]:
        """Type-ahead over the shared catalog: the learner's subjects (ready documents) first."""
        with self._uow() as tx:
            yours = tx.documents.subject_ids_readable_by(user_id)
        return self._search.search(user_id, query, yours)
```

In `choose`, delete the `content` read after `_choosable` that only fed the proposed-name check, and delete the `proposed` set and the `"Choose from the suggestions"` check. Keep the `_choosable` call (404/409 before creating anything), the unknown-id check, the duplicate check, and the `InvalidSubjectNameError → InvalidSubjectsError` mapping. Update the comment above `get_or_create` to: "One that ends up unused is harmless: it is a shared name." Update the module docstring to "from its suggestions or typed names".

- [ ] **Step 4: Fix other constructors** of `SubjectChoiceService` so the suite still runs: `backend/tests/fakes/api.py` and `backend/src/smart_tutor/apps/api/services.py` (pass `SubjectSearch(repo, names)`); `grep -rn "SubjectChoiceService(" backend` to find any others.

- [ ] **Step 5: Run** the full backend checks → PASS.

- [ ] **Step 6: Commit** — `git commit -m "Accept typed subject names and search the catalog when choosing subjects"`.

---

### Task 3: API route, request limits, isolation test, client

**Files:**
- Create: `backend/src/smart_tutor/apps/api/routes/subjects.py`
- Modify: `backend/src/smart_tutor/apps/api/main.py` (include the router)
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py` (`ChooseSubjectsRequest.new_names` strips)
- Modify: `backend/tests/fakes/api.py` (`names: SubjectNames | None = None` parameter)
- Test: `backend/tests/unit/apps/api/test_subject_routes.py`, `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/isolation/test_subjects.py`
- Regenerate: `web/src/api/openapi.json`, `web/src/api/generated/*`

**Interfaces:**
- Consumes: `SubjectChoiceService.search(user_id, query) -> list[CatalogMatch]` (Task 2).
- Produces: `GET /subjects/search?q=<1..100 chars>` → `200 list[SubjectMatchResponse]`, `SubjectMatchResponse = {subject_id: str, name: str, origin: "yours" | "shared"}`, `operation_id="search_subjects"`. Generated web SDK function `searchSubjects` and type `SubjectMatchResponse`.

- [ ] **Step 1: Write failing route tests** `backend/tests/unit/apps/api/test_subject_routes.py`, following the `client` fixture and token setup of `test_knowledge_routes.py` (copy its fixture; use `api_services(catalog=InMemorySubjects({...}))`):

```python
def test_search_returns_matches_with_only_id_name_origin(client: TestClient) -> None:
    response = client.get("/subjects/search", params={"q": "retriev"}, headers=AUTH)
    assert response.status_code == 200
    assert response.json() == [{"subject_id": IR, "name": "Information Retrieval", "origin": "shared"}]


@pytest.mark.parametrize("q", ["", "x" * 101])
def test_search_refuses_an_empty_or_huge_query(client: TestClient, q: str) -> None:
    assert client.get("/subjects/search", params={"q": q}, headers=AUTH).status_code == 422


def test_search_needs_a_token(client: TestClient) -> None:
    assert client.get("/subjects/search", params={"q": "x"}).status_code == 401
```

In `test_knowledge_routes.py`, add to the `test_choosing_refuses_an_invalid_request` parametrize a body `{"new_names": ["x" * 61]}`, and add:

```python
def test_a_typed_name_is_trimmed_and_may_be_60_characters_with_padding(client: TestClient) -> None:
    doc = <awaiting document id, as in test_choosing_a_suggestion_makes_the_document_ready>
    name = "y" * 60
    response = client.put(f"/documents/{doc}/subjects", json={"new_names": [f"  {name}  "]}, headers=AUTH)
    assert response.status_code == 200
    assert [s["name"] for s in response.json()["subjects"]] == [name]
```

Add `"search_subjects"` to `test_openapi_names_the_operations` if it lists all operations.

- [ ] **Step 2: Write the failing isolation test** `backend/tests/isolation/test_subjects.py` (setup as in `test_documents.py`). Learner A gets a personal name through a `SubjectNames` subclass (personal names arrive with US-10b; the subclass stands in for them):

```python
"""US-12: catalog search never shows who has a subject or another learner's personal names (US-2b, D21)."""

class PersonalNames(SubjectNames):
    """Learner A calls "Information Retrieval" "My secret IR notes"."""

    def names_for(self, user_id: UserId, subject_ids: Collection[SubjectId]) -> dict[SubjectId, str]:
        names = super().names_for(user_id, subject_ids)
        if user_id == "learner-a" and IR in names:
            names[IR] = "My secret IR notes"
        return names

# setup(): catalog = InMemorySubjects({IR: "Information Retrieval"}); names = PersonalNames(catalog)
# api_services(library, objects, catalog=catalog, names=names, queue=FakeQueue())
# A uploads + ingests a document and chooses subject_ids [IR] (as in test_b_never_sees_the_subjects_of_a_document).

def test_b_sees_a_subject_as_shared_by_its_canonical_name() -> None:
    client = setup_with_a_holding_ir()
    a = client.get("/subjects/search", params={"q": "secret"}, headers=A).json()
    assert a == [{"subject_id": IR, "name": "My secret IR notes", "origin": "yours"}]
    assert client.get("/subjects/search", params={"q": "secret"}, headers=B).json() == []
    b = client.get("/subjects/search", params={"q": "retrieval"}, headers=B).json()
    assert b == [{"subject_id": IR, "name": "Information Retrieval", "origin": "shared"}]
    assert client.get("/subjects/search", params={"q": "retrieval", "user_id": "learner-a"}, headers=B).json() == b
```

- [ ] **Step 3: Run** both test files → FAIL (404 route).

- [ ] **Step 4: Implement.** `fakes/api.py`: add `names: SubjectNames | None = None`; `names = names or SubjectNames(catalog)`; use it for `"subjects"`, the suggester, and `SubjectSearch(catalog, names)`.

`routes/subjects.py`:

```python
"""Subject routes (subjects module): search the shared catalog for the picker's type-ahead (PRD §8 US-2b)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel

from smart_tutor.apps.api.deps import CurrentPrincipal, SubjectChoice

router = APIRouter(tags=["subjects"])


class SubjectMatchResponse(BaseModel):
    # Only what the learner may see: no creator, no other learner's personal name (D20, D21).
    subject_id: str
    name: str
    origin: Literal["yours", "shared"]


@router.get("/subjects/search", operation_id="search_subjects")
def search_subjects(
    q: Annotated[str, Query(min_length=1, max_length=100)], principal: CurrentPrincipal, choice: SubjectChoice
) -> list[SubjectMatchResponse]:
    """The caller's subjects matching `q` (by their names), then other shared subjects (canonical names)."""
    return [
        SubjectMatchResponse(subject_id=m.subject_id, name=m.name, origin=m.origin.value)
        for m in choice.search(principal.user_id, q)
    ]
```

Mypy may need `origin=m.origin.value` typed as the Literal — if it complains, use `cast(Literal["yours", "shared"], m.origin.value)`. Include it in `main.py` with `include_protected(app, subjects.router)` (import alongside the others).

`routes/knowledge.py`: change `new_names` items to `Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]` (import `StringConstraints` from pydantic) and update the request comment: "Ids of existing subjects and typed or suggested names; a name equal to an existing subject reuses it (PRD D20)."

- [ ] **Step 5: Run** the backend checks (ruff, format, mypy, lint-imports, pytest) → PASS.

- [ ] **Step 6: Regenerate the client** from the worktree root: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`. Confirm `searchSubjects` appears in `web/src/api/generated/sdk.gen.ts`, then `npm run build`.

- [ ] **Step 7: Commit** — `git commit -m "Serve catalog search for the subject picker"`.

---

### Task 4: Type-ahead in the web picker

**Files:**
- Create: `web/src/api/subjects.ts`, `web/src/api/subjects.test.ts`
- Modify: `web/src/features/library/SubjectPicker.tsx`, `SubjectPicker.module.css`, `SubjectPicker.test.tsx`

Read `DESIGN.md` (tokens, accessibility) and look at `.design-shots/v0.4/picker-typeahead.light.png` and `picker-too-long.light.png` (render with `cd web && npm run design:shots -- --states "picker-typeahead,picker-too-long" --round v0.4 --theme both`). Rebuild with existing components (`Button`, `SubjectChip`) and tokens; do not copy prototype HTML/CSS.

**Interfaces:**
- Consumes: generated `searchSubjects`, `SubjectMatchResponse` (Task 3).
- Produces: `searchCatalog(query: string, apiClient?: Client): Promise<SubjectMatch[]>` and `export type SubjectMatch = SubjectMatchResponse` in `web/src/api/subjects.ts`; `SubjectPicker` prop `search?: (query: string) => Promise<SubjectMatch[]>`.

- [ ] **Step 1: API wrapper + test.** `web/src/api/subjects.ts`, mirroring `loadSubjectSuggestions` in `documents.ts` (copy `sessionOver` and `failure` there into a shared spot only if trivial; otherwise import nothing private — export them from `documents.ts` is acceptable):

```ts
// The shared catalog for the picker's type-ahead: the learner's subjects first (PRD §8 US-2b).
export async function searchCatalog(query: string, apiClient: Client = client): Promise<SubjectMatch[]> {
  const { data, error, response } = await searchSubjects({ client: apiClient, query: { q: query }, throwOnError: false });
  if (sessionOver(error, response)) throw new SessionExpiredError();
  if (!data) throw failure(error);
  return data;
}
```

Test it like `documents.test.ts` tests `loadSubjectSuggestions` (success returns data and sends `q`; 401 throws `SessionExpiredError`).

- [ ] **Step 2: Write failing picker tests** (append to `SubjectPicker.test.tsx`; `setup` gains `search: vi.fn(async () => matches)`):

```tsx
const matches = [
  { subject_id: "s-rag", name: "Retrieval-Augmented Generation", origin: "yours" as const },
  { subject_id: "s-ir", name: "Information Retrieval", origin: "shared" as const },
];
const input = () => screen.getByRole("combobox", { name: "Add your own" });

it("searches the catalog as the learner types and adds a picked subject", async () => {
  const props = setup();
  await chip(/AI Agents/);
  await userEvent.type(input(), "retriev");
  const list = await screen.findByRole("listbox");
  const options = within(list).getAllByRole("option");
  expect(options.map((o) => o.textContent)).toEqual([
    expect.stringContaining("Your subject"),
    expect.stringContaining("Shared subject"),
    expect.stringContaining('Create "retriev"'),
  ]);
  expect(props.search).toHaveBeenLastCalledWith("retriev");
  await userEvent.click(options[1]);
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(input()).toHaveValue("");
  expect(screen.getByRole("button", { name: /Information Retrieval/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByText("2 of 3 selected")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(props.save).toHaveBeenCalledWith("d1", { subject_ids: ["s-agents", "s-ir"], new_names: [] });
});

it("adds a typed name with Add and sends it as a new name", async () => {
  const props = setup({ search: vi.fn(async () => []) });
  await chip(/AI Agents/);
  await userEvent.type(input(), "  Tool Calling ");
  await userEvent.click(screen.getByRole("button", { name: "Add" }));
  expect(screen.getByRole("button", { name: /Tool Calling/ })).toHaveAttribute("aria-pressed", "true");
  await userEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(props.save).toHaveBeenCalledWith("d1", { subject_ids: ["s-agents"], new_names: ["Tool Calling"] });
});

it("selects an existing chip instead of adding a duplicate", async () => {
  setup({ search: vi.fn(async () => []) });
  await userEvent.click(await chip(/AI Agents/)); // deselect
  await userEvent.type(input(), "ai  AGENTS{Enter}");
  expect(screen.getAllByRole("button", { name: /AI Agents/ })).toHaveLength(1);
  expect(screen.getByRole("button", { name: /AI Agents/ })).toHaveAttribute("aria-pressed", "true");
});

it("picks the active option with the keyboard and closes the list on Escape without closing the dialog", async () => {
  const props = setup();
  await chip(/AI Agents/);
  await userEvent.type(input(), "retriev");
  await screen.findByRole("listbox");
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(props.onClose).not.toHaveBeenCalled();
  await userEvent.keyboard("{ArrowDown}");
  await screen.findByRole("listbox");
  expect(input()).toHaveAttribute("aria-activedescendant", expect.stringMatching(/.+/));
  await userEvent.keyboard("{Enter}");
  expect(screen.getByRole("button", { name: /Retrieval-Augmented Generation/ })).toHaveAttribute("aria-pressed", "true");
});

it("ignores a slower, older search response", async () => {
  let resolveOld: (m: typeof matches) => void = () => {};
  const search = vi.fn((q: string) =>
    q === "re" ? new Promise<typeof matches>((r) => { resolveOld = r; }) : Promise.resolve([matches[1]]),
  );
  setup({ search });
  await chip(/AI Agents/);
  await userEvent.type(input(), "re");
  await waitFor(() => expect(search).toHaveBeenCalledWith("re"));
  await userEvent.type(input(), "triev");
  await screen.findByRole("option", { name: /Information Retrieval/ });
  resolveOld(matches);
  await new Promise((r) => setTimeout(r, 0));
  expect(screen.queryByRole("option", { name: /Retrieval-Augmented/ })).not.toBeInTheDocument();
});

it("blocks a name over 60 characters with a counter and an error", async () => {
  const props = setup();
  await chip(/AI Agents/);
  await userEvent.type(input(), "x".repeat(61));
  expect(screen.getByText("61/60")).toBeVisible();
  expect(input()).toHaveAttribute("aria-invalid", "true");
  expect(input()).toHaveAccessibleDescription(expect.stringContaining("Subject names can be up to 60 characters."));
  expect(screen.getByRole("button", { name: "Add" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  expect(props.search).not.toHaveBeenCalledWith("x".repeat(61));
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

it("shows the counter and the visibility hint", async () => {
  setup();
  await chip(/AI Agents/);
  await userEvent.type(input(), "retriev");
  expect(screen.getByText("7/60")).toBeVisible();
  expect(screen.getByText("Subject names are visible to everyone. Don't include personal information.")).toBeVisible();
});

it("cannot add a fourth subject", async () => {
  setup({ search: vi.fn(async () => []) });
  await userEvent.click(await chip(/LLMs/));
  await userEvent.click(await chip(/Tool Use/));
  expect(input()).toBeDisabled();
});
```

Add `waitFor` to the Testing Library import. Existing tests must keep passing (they don't pass `search`; the default calls the real API only after typing, which they never do).

- [ ] **Step 3: Run** `cd web && npx vitest run src/features/library/SubjectPicker.test.tsx` → FAIL.

- [ ] **Step 4: Implement in `SubjectPicker.tsx`.** Design:
  - State: `added: Suggestion[]` (chips appended after the suggestions; `chips = [...suggestions, ...added]`, indices in `selected` refer to `chips`, so suggestion indices stay stable); `query: string`; `results: SubjectMatch[]`; `open: boolean`; `active: number` (−1 = none).
  - `const MAX_NAME = 60; const typed = query.trim().replace(/\s+/g, " "); const tooLong = typed.length > MAX_NAME;`
  - `normalize = (s: string) => s.normalize("NFKC").toLowerCase().trim().replace(/\s+/g, " ")` — mirrors the server's key closely enough to avoid duplicate chips; the server is authoritative.
  - Search effect: when `typed` is non-empty, not `tooLong`, and not `atMax`, wait 200 ms (`setTimeout`, cleared on change), then call `search(typed)`; keep a `requestRef` counter and apply the result only if it is still the latest request and `alive.current`; on error, show no results (type-ahead is optional — Add still works). Empty `typed` → `results = []`, `open = false`.
  - Options = `results` then, when no result's normalized name equals `normalize(typed)`, a create option `Create "<typed>"` with the right-side note "New subject, visible to everyone". Results show right-side "Your subject" / "Shared subject".
  - `addChoice(item: Suggestion)`: if a chip has the same `subject_id` (non-null) or the same normalized name, select that chip index; otherwise append to `added` and select its new index. Then clear `query`, close the list, refocus the input.
  - Picking a result → `addChoice({ subject_id, name, origin })`. Picking create or pressing **Add** → if a result's normalized name equals `normalize(typed)`, add that result, else `addChoice({ subject_id: null, name: typed, origin: "new" })`.
  - Keyboard on the input: ArrowDown/ArrowUp move `active` (opening the list if closed and there are options); Enter → picks the active option, else behaves like Add (call `preventDefault`); Escape with the list open → `event.stopPropagation()` + close list (the Dialog listens for Escape on its panel via bubbling); Escape with it closed → let it bubble (dialog closes).
  - ARIA (combobox pattern): `<label htmlFor="picker-add">Add your own</label>`; input `id="picker-add" role="combobox" aria-expanded={open} aria-controls="picker-results" aria-autocomplete="list" aria-activedescendant={open && active >= 0 ? \`picker-option-${active}\` : undefined} aria-invalid={tooLong || undefined} aria-describedby="picker-add-hint picker-add-error"` (include the error id only when `tooLong`); `<ul id="picker-results" role="listbox">` with `<li role="option" id=… aria-selected={i === active}>` and `onMouseDown={(e) => e.preventDefault()}` + `onClick` so the input keeps focus.
  - Under the input row: hint text (`id="picker-add-hint"`) left, counter `{typed.length}/{MAX_NAME}` right (styled `.max`-like danger when `tooLong`); when `tooLong`, an error line `id="picker-add-error"` "Subject names can be up to 60 characters." (with `role="alert"` is not needed — the description and `aria-invalid` carry it; keep it plain text).
  - Disable the input and Add when `atMax` (the existing max helper explains); disable Add when `!typed || tooLong`.
  - Save is disabled also when `tooLong`; extend its `aria-describedby` to `picker-add-error` in that case.
  - `onSave`: build the choice from `chips` filtered by `selected` (unchanged logic, now over `chips`).
  - The new section sits below the suggestions fieldset, only when `loaded`.
- CSS in `SubjectPicker.module.css` with tokens only (look at existing classes; follow the mockup: label bold 14px, input full width with Add button on the right, list as an absolutely-positioned popover under the input with `--surface`, border, `--r-md`, shadow token if one exists in DESIGN.md; active option uses the accent-soft background; meta labels `--fs-12`/`--text-2`). Check both themes in a dev render if possible.

- [ ] **Step 5: Run** the picker tests, then `cd web && npm run build && npx vitest run` → PASS (also `npm run lint` if the package defines it).

- [ ] **Step 6: Commit** — `git commit -m "Type a subject name with type-ahead in the picker"`.

---

### Task 5: PRD and module docs

**Files:**
- Modify: `sdd/prd.md` (status line version → v2.19; a "Changes from v2.18" row at the top of the change table; §8 US-2b note)
- Modify: `backend/src/smart_tutor/subjects/README.md` (catalog search)
- Modify: `AGENTS.md` (PRD version in the sources table: `v2.19`)

- [ ] **Step 1:** Add the change row: "US-2b typed names (#78): the picker's *Add your own* field searches the shared catalog (`GET /subjects/search`), the learner's subjects first by their names, then shared subjects by canonical name; a typed name is trimmed, at most 60 characters (Save is blocked while it is longer), reuses a subject whose normalized name matches exactly, and otherwise creates a shared subject. Near-duplicate reuse and the name check follow in #79." Bump the version in the status line and in `AGENTS.md`.
- [ ] **Step 2:** In `subjects/README.md`, add a line for `SubjectSearch` next to the other services, matching the README's style.
- [ ] **Step 3: Commit** — `git commit -m "PRD v2.19: typed subject names with catalog type-ahead"`.

---

## Final verification

```bash
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest
cd backend && uv run --env-file ../.env pytest -m integration tests/integration/subjects
cd web && npm run build && npx vitest run
```

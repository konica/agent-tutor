# First Question Picks 1–3 Subjects Implementation Plan (#84)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a new thread's first question, the agent detects 1–3 of the learner's subjects (PRD §9.2 step 1), the API persists them in `threads.subject_ids`, the answer searches only those subjects, and the chat header shows them as chips by the learner's names.

**Architecture:** Search hits now carry `subject_ids` (which of the requested subjects the hit's document has). A pure `DetectionPolicy` in `tutoring.domain` turns per-subject best scores into bound subjects or "unsure"; `SubjectDetector` in `tutoring.application` runs one search (k = 20) over all of the learner's subjects through the `Retriever` port and applies the policy (unsure falls back to the best subject until the "ask the learner" slice). The agent graph gains a `resolve_subjects` node before `search` and streams a `subjects` event first; the API, which now sends **all** of the learner's subjects to the agent, starts and persists the thread when that event arrives and replaces it with the existing `thread` event. Thresholds are SSM parameters read once at agent startup.

**Tech Stack:** Python 3.13, FastAPI, LangGraph, MCP 2.x, SQLAlchemy + pgvector, pytest; React + TypeScript + Vite, Vitest; AWS CDK (Python).

**Spec:** Ticket #84 (`gh issue view 84`), PRD `sdd/prd.md` §8 US-3 criterion 2, §9.2 Ask path step 1, §9.3; design round v0.7 (tag `design-v0.7`) states `chat-subjects-detected`, `chat-subjects-detected-multi`.

## Global Constraints

- Read `AGENTS.md`, `backend/AGENTS.md`, and the README of each module you edit before editing it.
- Import rules (`PYTHONUTF8=1 uv run lint-imports`): `domain` has no I/O; other modules only through their `application` package; `apps` is a leaf; tutoring never reads chunk tables.
- Checks before every commit (from `backend/`): `uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Web: `cd web && npm run build && npx vitest run`. Infra: `cd infra && uv run pytest`.
- Integration tests (`-m integration`) need the Compose stack, which is running on this machine (Postgres on :10400): `cd backend && uv run pytest -m integration tests/integration/knowledge -q`.
- The learner's token never goes in a prompt, state, log, or trace. Store `subject_id`s; resolve names at read time.
- SSM names and starting values: `/smart-tutor/detect-threshold` = `0.35`, `/smart-tutor/detect-margin` = `0.05`, `/smart-tutor/multi-margin` = `0.03`. Starting values only; the eval slice tunes them.
- Detection: k = 20 (`DETECTION_K`); search accepts 1–100 subject ids (`MAX_SUBJECTS = 100` in `SearchService`); a thread holds 1–3 subjects.
- Commit subjects in the imperative mood, body says why, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Windows Git Bash: `MSYS_NO_PATHCONV=1` for commands taking `/smart-tutor/...` paths.

## Detection rule (exact)

Given `scores: Mapping[SubjectId, float]` (each scored subject's best chunk similarity; subjects without a hit among the top 20 are absent):

1. Rank subjects by score, highest first; ties by subject id ascending.
2. Empty, or best score < `detect_threshold` → unsure.
3. `bound` = the ranked subjects with score ≥ `detect_threshold` **and** `best − score ≤ multi_margin`, first 3 only. (Always a prefix of the ranking, and always includes the best.)
4. Runner-up = the first ranked subject **not** in `bound`. If it exists and `best − runner_up < detect_margin` → unsure.
5. Otherwise → `bound`.

"Runner-up" is the best subject that was not bound: read as "second-best overall", a second subject within `multi_margin` but not `detect_margin` would make detection unsure while one further away would bind both. Task 3 records this in the PRD.

## Review Focus

- A learner with 4+ subjects whose top 4 are all close (within `multi_margin`): the 4th is the runner-up and too close → unsure (falls back to the best), never 4 subjects. Pinned in Task 3's policy tests.
- The agent's first event is `error` (e.g. MCP down during detection): no thread is created and the error reaches the browser unchanged. Pinned in Task 6.
- The agent names a subject the learner doesn't have (stale or tampered): the API refuses it (`ThreadSubjectsError`), creates no thread, and sends the `unavailable` error. Pinned in Task 6.
- Another learner's document in the same shared subject never changes this learner's scores. Pinned in Task 4's isolation test.
- A search hit's `subject_ids` lists only requested subjects, even when the document has more. Pinned in Task 1 (fake, SQL integration, isolation).

---

### Task 1: Search hits say which requested subjects they belong to

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/domain/search.py`, `backend/src/smart_tutor/knowledge/adapters/sql_library.py` (`_Chunks.search`, ~line 286), `backend/src/smart_tutor/knowledge/application/search_service.py`, `backend/src/smart_tutor/knowledge/README.md`
- Modify: `backend/tests/fakes/knowledge.py` (`_Chunks.search`), `backend/tests/fakes/ingest.py` (`ingest_ready`)
- Modify: `backend/src/smart_tutor/apps/mcp_server/server.py` (`ChunkResult`, tool docstring)
- Modify: `backend/src/smart_tutor/tutoring/domain/retrieved_chunk.py`, `backend/src/smart_tutor/tutoring/adapters/mcp_retriever.py`
- Test: `backend/tests/unit/knowledge/test_search_service.py`, `backend/tests/integration/knowledge/test_sql_library.py`, `backend/tests/isolation/test_search.py`, `backend/tests/unit/apps/mcp_server/test_server.py`, `backend/tests/unit/tutoring/test_mcp_retriever.py`

**Interfaces:**
- Produces: `ChunkHit(chunk_id, document_id, document_title, page, text, score, subject_ids: tuple[SubjectId, ...])` (new **required** last field, sorted ascending); `RetrievedChunk(chunk_id, document_title, page, text, score, subject_ids: tuple[SubjectId, ...] = ())` (new last field with default); MCP `search` result chunks gain `"subject_ids": list[str]`; `SearchService.search` accepts 1 to `MAX_SUBJECTS = 100` subject ids; `ingest_ready(library, owner, text, subject_ids: Sequence[SubjectId] = (GENERAL_SUBJECT_ID,))`.

- [ ] **Step 1: Write the failing tests**

`tests/unit/knowledge/test_search_service.py` — add (reuse the file's existing helpers/imports; `ingest_ready` now takes `subject_ids`):

```python
S1 = SubjectId("00000000-0000-4000-8000-0000000000a1")
S2 = SubjectId("00000000-0000-4000-8000-0000000000a2")


def test_a_hit_lists_only_the_requested_subjects_its_document_has() -> None:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention weighs tokens.", subject_ids=[S1, S2])
    search = SearchService(library.unit_of_work, fake_embeddings())

    [only_s2] = search.search(UserId("ada"), "Attention weighs tokens.", [S2])
    [both] = search.search(UserId("ada"), "Attention weighs tokens.", [S2, S1])

    assert only_s2.subject_ids == (S2,)
    assert both.subject_ids == (S1, S2)  # sorted


def test_search_takes_up_to_100_subjects() -> None:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention weighs tokens.")
    search = SearchService(library.unit_of_work, fake_embeddings())
    many = [SubjectId(str(uuid.UUID(int=i))) for i in range(1, 100)] + [GENERAL_SUBJECT_ID]

    assert len(search.search(UserId("ada"), "Attention weighs tokens.", many)) == 1
    with pytest.raises(InvalidSearchError, match="1 to 100 subjects"):
        search.search(UserId("ada"), "q", [*many, SubjectId(str(uuid.UUID(int=101)))])
```

Replace any existing test that asserts a 4-subject search is refused with the 101 case above (the message changes from "Search 1 to 3 subjects" to "Search 1 to 100 subjects").

`tests/integration/knowledge/test_sql_library.py` — add a test in the file's existing style (it builds documents/chunks against Postgres; reuse its fixtures and subject-row helpers) that a ready document with subjects `{S1, S2}` searched with `[S2]` returns hits whose `subject_ids == (S2,)`, and with `[S1, S2]` returns `(S1, S2)`.

`tests/isolation/test_search.py` — add:

```python
async def test_a_hit_names_only_the_subjects_asked_for() -> None:
    library, verifier, _ = world()
    other = SubjectId("00000000-0000-4000-8000-0000000000b2")
    ingest_ready(library, "learner-a", "Attention scales with heads.", subject_ids=[GENERAL_SUBJECT_ID, other])
    result = await search_as(
        library, verifier, "token-a", query="Attention scales with heads.", subject_ids=[str(GENERAL_SUBJECT_ID)]
    )
    assert not result.is_error
    assert all(c["subject_ids"] == [str(GENERAL_SUBJECT_ID)] for c in result.structured_content["chunks"])
```

`tests/unit/apps/mcp_server/test_server.py` — extend the existing successful-search test to assert each chunk has `"subject_ids": ["00000000-0000-4000-8000-000000000001"]`.

`tests/unit/tutoring/test_mcp_retriever.py` — extend the existing parse test so the served chunk includes `"subject_ids": ["s1", "s2"]` and the `RetrievedChunk` has `subject_ids == ("s1", "s2")`.

- [ ] **Step 2: Run them to verify they fail**

Run (from `backend/`): `uv run pytest tests/unit/knowledge/test_search_service.py tests/isolation/test_search.py tests/unit/apps/mcp_server tests/unit/tutoring/test_mcp_retriever.py -q`
Expected: FAIL (`ingest_ready() got an unexpected keyword argument 'subject_ids'`, missing `subject_ids`).

- [ ] **Step 3: Implement**

`knowledge/domain/search.py`: add the last field `subject_ids: tuple[SubjectId, ...]  # the requested subjects this hit's document has, sorted`.

`knowledge/application/search_service.py`: `MAX_SUBJECTS = 100  # all of a learner's subjects, for subject detection (PRD §9.2 step 1)`; error message `f"Search 1 to {MAX_SUBJECTS} subjects"`. Export `MAX_SUBJECTS` from `knowledge/application/__init__.py` as `MAX_SEARCH_SUBJECTS` (`from ...search_service import MAX_SUBJECTS as MAX_SEARCH_SUBJECTS`, add to `__all__`).

`knowledge/adapters/sql_library.py` `_Chunks.search`: add a correlated scalar subquery column; `can_read` filtering is unchanged.

```python
        requested = list(subject_ids)
        hit_subjects = (
            select(func.array_agg(document_subjects.c.subject_id))
            .where(
                document_subjects.c.document_id == documents.c.document_id,
                document_subjects.c.subject_id.in_(requested),
            )
            .scalar_subquery()
        )
```

Use `requested` in `in_subjects` too, select `hit_subjects.label("subject_ids")`, and build each hit with `tuple(sorted(SubjectId(str(s)) for s in r.subject_ids))` as the last argument.

`tests/fakes/knowledge.py` `_Chunks.search`: pass `tuple(sorted(s for s in d.subject_ids if s in set(subject_ids)))` as the last `ChunkHit` argument.

`tests/fakes/ingest.py`: add `subject_ids: Sequence[SubjectId] = (GENERAL_SUBJECT_ID,)` and call `document.choose_subjects(list(subject_ids))`; update the docstring ("ready in `subject_ids` (General by default)").

`apps/mcp_server/server.py`: `ChunkResult.subject_ids: list[str]`, filled with `[str(s) for s in h.subject_ids]`; docstring: `"""Chunks of the caller's ready documents in any of these subjects (1 to 100), nearest first; each names which of them it belongs to."""`

`tutoring/domain/retrieved_chunk.py`: add `subject_ids: tuple[SubjectId, ...] = ()  # which of the searched subjects it belongs to`.

`tutoring/adapters/mcp_retriever.py`: build with `RetrievedChunk(c["chunk_id"], c["document_title"], c["page"], c["text"], c["score"], tuple(SubjectId(s) for s in c["subject_ids"]))`.

`knowledge/README.md`: in Rules change "not 1–3 subjects" to "not 1–100 subjects" and add after "each hit carries the document's display title": "and the requested subjects its document has (`subject_ids`), so the agent can score each subject".

Fix any other test that constructs `ChunkHit` positionally (grep `ChunkHit(` under `backend/tests`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q && uv run pytest -m integration tests/integration/knowledge -q`
Expected: PASS.

- [ ] **Step 5: Run all checks and commit**

```bash
git add -A backend
git commit -m "Say which requested subjects each search hit belongs to

Subject detection scores each subject by its best chunk, so a hit must name
its subjects, and detection searches all of a learner's subjects at once.
can_read filtering is unchanged.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: DetectionPolicy

**Files:**
- Create: `backend/src/smart_tutor/tutoring/domain/detection.py`
- Test: `backend/tests/unit/tutoring/test_detection_policy.py`

**Interfaces:**
- Consumes: `RetrievedChunk.subject_ids` (Task 1).
- Produces: `DetectionPolicy(detect_threshold: float, detect_margin: float, multi_margin: float)` frozen dataclass with `bind(scores: Mapping[SubjectId, float]) -> tuple[SubjectId, ...] | None` (None = unsure) and `ranked(scores) -> list[SubjectId]`; `best_scores(chunks: Iterable[RetrievedChunk], among: Collection[SubjectId]) -> dict[SubjectId, float]`; `Detection(subject_ids: tuple[SubjectId, ...], unsure: bool, scores: Mapping[SubjectId, float])` frozen dataclass.

- [ ] **Step 1: Write the failing tests**

Use dyadic values so float subtraction is exact (e.g. 0.75 − 0.625 == 0.125 exactly).

```python
"""DetectionPolicy (PRD §9.2 step 1): bind 1–3 subjects from per-subject best scores, or be unsure."""

import pytest

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.domain.detection import DetectionPolicy, best_scores
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

A, B, C, D = (SubjectId(x) for x in "abcd")
POLICY = DetectionPolicy(detect_threshold=0.5, detect_margin=0.125, multi_margin=0.0625)


@pytest.mark.parametrize(
    ("scores", "bound"),
    [
        ({}, None),
        ({A: 0.75}, (A,)),  # no runner-up
        ({A: 0.5}, (A,)),  # exactly at the threshold
        ({A: 0.4375}, None),  # just below the threshold
        ({A: 0.75, B: 0.625}, (A,)),  # leads by exactly detect_margin
        ({A: 0.75, B: 0.65625}, None),  # leads by less than detect_margin, more than multi_margin
        ({A: 0.75, B: 0.6875, C: 0.5}, (A, B)),  # B exactly at multi_margin; runner-up C leads by 0.25
        ({A: 0.75, B: 0.6875, C: 0.6875}, (A, B, C)),
        ({A: 0.75, B: 0.6875, C: 0.625}, (A, B)),  # C outside multi_margin, exactly detect_margin behind
        ({A: 0.75, B: 0.6875, C: 0.65625}, None),  # C outside multi_margin but too close
        ({A: 0.5, B: 0.4375}, None),  # B is under the threshold, so it's the runner-up, 0.0625 behind
        ({A: 0.53125, B: 0.40625}, (A,)),
    ],
)
def test_binds_or_is_unsure(scores: dict[SubjectId, float], bound: tuple[SubjectId, ...] | None) -> None:
    assert POLICY.bind(scores) == bound


def test_never_binds_more_than_three() -> None:
    wide = DetectionPolicy(detect_threshold=0.5, detect_margin=0.125, multi_margin=0.25)
    assert wide.bind({A: 0.875, B: 0.8125, C: 0.75, D: 0.625}) == (A, B, C)  # D leads by 0.25 ≥ 0.125


def test_a_fourth_close_subject_makes_it_unsure() -> None:
    assert POLICY.bind({A: 0.75, B: 0.75, C: 0.75, D: 0.75}) is None


def test_a_multi_margin_wider_than_the_threshold_still_needs_the_threshold() -> None:
    wide = DetectionPolicy(detect_threshold=0.5, detect_margin=0.125, multi_margin=0.5)
    assert wide.bind({A: 0.75, B: 0.375}) == (A,)  # B within multi_margin but under the threshold; leads by 0.375


def test_ties_rank_by_subject_id() -> None:
    assert POLICY.ranked({B: 0.5, A: 0.5, C: 0.75}) == [C, A, B]


def test_best_scores_keeps_each_subjects_best_chunk_among_the_asked_subjects() -> None:
    chunks = [
        RetrievedChunk("c1", "a.pdf", 1, "x", 0.9, (A, B)),
        RetrievedChunk("c2", "b.pdf", 1, "y", 0.7, (B,)),
        RetrievedChunk("c3", "c.pdf", 1, "z", 0.95, (D,)),  # not asked about: ignored
    ]
    assert best_scores(chunks, among=[A, B, C]) == {A: 0.9, B: 0.9}
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/unit/tutoring/test_detection_policy.py -q` — Expected: FAIL (module not found).

- [ ] **Step 3: Implement `tutoring/domain/detection.py`**

```python
"""Subject detection (PRD §9.2 step 1): which of the learner's subjects a first question clearly matches."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk
from smart_tutor.tutoring.domain.thread import MAX_SUBJECTS


def best_scores(chunks: Iterable[RetrievedChunk], among: Collection[SubjectId]) -> dict[SubjectId, float]:
    """Each asked-about subject's best chunk similarity; subjects without a chunk are absent."""
    asked = set(among)
    scores: dict[SubjectId, float] = {}
    for chunk in chunks:
        for subject_id in chunk.subject_ids:
            if subject_id in asked and chunk.score > scores.get(subject_id, float("-inf")):
                scores[subject_id] = chunk.score
    return scores


@dataclass(frozen=True)
class DetectionPolicy:
    """Thresholds are settings (SSM), tuned on the detection dataset (PRD §10.3)."""

    detect_threshold: float
    detect_margin: float
    multi_margin: float

    def ranked(self, scores: Mapping[SubjectId, float]) -> list[SubjectId]:
        """Highest score first; ties by subject id, so detection is deterministic."""
        return sorted(scores, key=lambda s: (-scores[s], s))

    def bind(self, scores: Mapping[SubjectId, float]) -> tuple[SubjectId, ...] | None:
        """The 1–3 subjects the question clearly matches, or None when unsure.

        Bound: every subject at or above the threshold and within `multi_margin` of the best (at most 3). They must
        lead the runner-up, the best subject not bound, by at least `detect_margin`.
        """
        ranked = self.ranked(scores)
        if not ranked or scores[ranked[0]] < self.detect_threshold:
            return None
        best = scores[ranked[0]]
        close = [s for s in ranked if scores[s] >= self.detect_threshold and best - scores[s] <= self.multi_margin]
        bound = close[:MAX_SUBJECTS]
        rest = ranked[len(bound) :]
        if rest and best - scores[rest[0]] < self.detect_margin:
            return None
        return tuple(bound)


@dataclass(frozen=True)
class Detection:
    """The subjects a new thread starts with; `unsure` when the policy bound none and the best was taken."""

    subject_ids: tuple[SubjectId, ...]
    unsure: bool
    scores: Mapping[SubjectId, float] = field(default_factory=dict)
```

- [ ] **Step 4: Run tests** — `uv run pytest tests/unit/tutoring -q` → PASS. Run all checks (mypy, lint-imports included).

- [ ] **Step 5: Commit** — `git commit -m "Add the subject detection policy"` with a body explaining the runner-up reading, plus the Co-Authored-By line.

---

### Task 3: Detection thresholds are settings (SSM), and the PRD says what the runner-up is

**Files:**
- Create: `backend/src/smart_tutor/tutoring/application/detection_settings.py`
- Modify: `backend/src/smart_tutor/shared/config.py`, `backend/src/smart_tutor/tutoring/application/__init__.py`
- Modify: `local/localstack/init/ready.d/10-smart-tutor.sh`, `infra/smart_tutor_infra/stacks/config.py`, `infra/tests/test_config_stack.py`
- Modify: `sdd/prd.md` (status line version → v2.19, new "Changes from v2.18" row at the top of the changes rows, §9.2 step 1 text, §9.4 Settings row)
- Test: `backend/tests/unit/tutoring/test_detection_settings.py`

**Interfaces:**
- Consumes: `DetectionPolicy` (Task 2); `ParameterStore` (`smart_tutor.shared.ports.parameter_store`, method `get(name) -> str`); the fake `fakes.parameters` (read it — it has an in-memory store used by `test_limits.py`).
- Produces: `load_detection_policy(store: ParameterStore, threshold_param: str, margin_param: str, multi_margin_param: str) -> DetectionPolicy`; settings `detect_threshold_param = "/smart-tutor/detect-threshold"`, `detect_margin_param = "/smart-tutor/detect-margin"`, `multi_margin_param = "/smart-tutor/multi-margin"`; `tutoring.application` exports `DetectionPolicy`, `Detection`, `load_detection_policy`.

- [ ] **Step 1: Failing tests** — `tests/unit/tutoring/test_detection_settings.py`, modelled on `tests/unit/knowledge/test_limits.py` (same fake store):

```python
def test_loads_the_three_values() -> None:
    store = <fake store>({"/t": "0.35", "/m": "0.05", "/mm": "0.03"})
    assert load_detection_policy(store, "/t", "/m", "/mm") == DetectionPolicy(0.35, 0.05, 0.03)


@pytest.mark.parametrize("bad", ["", "abc", "-0.1", "1.5", "nan", "inf"])
def test_a_value_outside_0_to_1_stops_startup(bad: str) -> None:
    store = <fake store>({"/t": bad, "/m": "0.05", "/mm": "0.03"})
    with pytest.raises(ValueError, match="/t"):
        load_detection_policy(store, "/t", "/m", "/mm")
```

`infra/tests/test_config_stack.py`: one test asserting the three `AWS::SSM::Parameter` resources with the exact names and values `0.35`, `0.05`, `0.03` (copy the existing `max-processing-attempts` test's shape).

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/tutoring/test_detection_settings.py -q` (backend) and `cd infra && uv run pytest -q` → FAIL.

- [ ] **Step 3: Implement**

`detection_settings.py`:

```python
"""Load the detection thresholds from settings (SSM), never from code (PRD §9.2)."""

import math

from smart_tutor.shared.ports.parameter_store import ParameterStore
from smart_tutor.tutoring.domain.detection import DetectionPolicy


def _fraction(store: ParameterStore, name: str) -> float:
    value = store.get(name)
    try:
        number = float(value)
    except ValueError:
        number = math.nan
    if not 0 <= number <= 1:  # also refuses nan and inf
        raise ValueError(f"SSM parameter {name} must be a number from 0 to 1, got {value!r}")
    return number


def load_detection_policy(
    store: ParameterStore, threshold_param: str, margin_param: str, multi_margin_param: str
) -> DetectionPolicy:
    return DetectionPolicy(
        detect_threshold=_fraction(store, threshold_param),
        detect_margin=_fraction(store, margin_param),
        multi_margin=_fraction(store, multi_margin_param),
    )
```

`shared/config.py` after `max_processing_attempts_param`:

```python
    # Subject detection (PRD §9.2 step 1), read once at startup by the agent; starting values, tuned by evals.
    detect_threshold_param: str = "/smart-tutor/detect-threshold"
    detect_margin_param: str = "/smart-tutor/detect-margin"
    multi_margin_param: str = "/smart-tutor/multi-margin"
```

LocalStack script, after the processing-attempts line:

```bash
# Subject detection (PRD §9.2 step 1): starting values, read by the agent; the detection evals tune them.
awslocal ssm put-parameter --name /smart-tutor/detect-threshold --type String --value 0.35 --overwrite
awslocal ssm put-parameter --name /smart-tutor/detect-margin --type String --value 0.05 --overwrite
awslocal ssm put-parameter --name /smart-tutor/multi-margin --type String --value 0.03 --overwrite
```

Also put them into the running LocalStack now: `MSYS_NO_PATHCONV=1 docker compose exec localstack awslocal ssm put-parameter --name /smart-tutor/detect-threshold --type String --value 0.35 --overwrite` (and the other two).

CDK `config.py`: add `("detect-threshold", "0.35"), ("detect-margin", "0.05"), ("multi-margin", "0.03")` to the loop and update the comment to mention detection thresholds (read by the agent).

PRD: status line `Draft v2.19`; new row `| **Changes from v2.18** | Subject detection (§9.2 step 1) states that the runner-up is the best subject not bound, and that a subject without a chunk among the top 20 results has no score. Starting values in SSM: `detect-threshold` 0.35, `detect-margin` 0.05, `multi-margin` 0.03. No other behavior changes. |` placed above the v2.13 row in the same table (find the newest "Changes from" row and put it before it). In §9.2 step 1, after "(at most 3 in total)" insert: "; the bound subjects must lead the **runner-up** — the best-scoring subject not bound — by ≥ `detect_margin`. Detection is one search of the top 20 chunks across those subjects; a subject with no chunk among them has no score." and adjust the preceding sentence so it reads: "Bind the best subject if its score ≥ `detect_threshold`; also bind any other subject whose score ≥ `detect_threshold` and is within `multi_margin` of the best (at most 3 in total); the bound subjects must lead…". In §9.4's Settings row change "detection thresholds" to "detection thresholds (`detect-threshold` 0.35, `detect-margin` 0.05, `multi-margin` 0.03; starting values)".

- [ ] **Step 4: Run tests and checks** (backend + `cd infra && uv run pytest`) → PASS.

- [ ] **Step 5: Commit** — "Make the detection thresholds SSM settings" (body: starting values recorded before evals tune them; PRD v2.19 clarifies the runner-up).

---

### Task 4: SubjectDetector and ConversationService take detected subjects

**Files:**
- Create: `backend/src/smart_tutor/tutoring/application/subject_detector.py`
- Modify: `backend/src/smart_tutor/tutoring/application/conversation_service.py`, `backend/src/smart_tutor/tutoring/application/__init__.py`, `backend/src/smart_tutor/tutoring/domain/errors.py` (delete `DetectionUnavailableError`), `backend/src/smart_tutor/tutoring/README.md`
- Test: `backend/tests/unit/tutoring/test_subject_detector.py`, `backend/tests/unit/tutoring/test_conversation_service.py`, `backend/tests/isolation/test_detection.py`

**Interfaces:**
- Consumes: `Retriever.search(query, subject_ids, k)`; `DetectionPolicy`, `Detection`, `best_scores` (Task 2); `ingest_ready(..., subject_ids=...)` (Task 1).
- Produces: `DETECTION_K = 20`; `SubjectDetector(retriever: Retriever, policy: DetectionPolicy)` with `async detect(question: str, learner_subjects: Sequence[SubjectId]) -> Detection`; `ConversationService.subjects_for_new_thread(user_id) -> list[SubjectId]` (sorted; raises `NoDocumentsError("Upload a document first")`); `ConversationService.start_thread(user_id, subject_ids: Sequence[SubjectId]) -> Thread` (raises `NoDocumentsError`, or `ThreadSubjectsError` when a subject isn't the learner's or the count isn't 1–3). `tutoring.application` exports `SubjectDetector`, `DETECTION_K`; `DetectionUnavailableError` is gone.

- [ ] **Step 1: Failing tests**

`tests/unit/tutoring/test_subject_detector.py`:

```python
"""SubjectDetector: one search over all of the learner's subjects, scored per subject (PRD §9.2 step 1)."""

import pytest

from fakes import FakeRetriever
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.application import DETECTION_K, DetectionPolicy, SubjectDetector
from smart_tutor.tutoring.domain.retrieved_chunk import RetrievedChunk

A, B, C = SubjectId("a"), SubjectId("b"), SubjectId("c")
POLICY = DetectionPolicy(detect_threshold=0.5, detect_margin=0.125, multi_margin=0.0625)


def chunk(score: float, *subjects: SubjectId) -> RetrievedChunk:
    return RetrievedChunk(f"c{score}", "a.pdf", 1, "text", score, subjects)


async def test_one_subject_is_bound_without_searching() -> None:
    retriever = FakeRetriever([chunk(0.9, A)])
    detection = await SubjectDetector(retriever, POLICY).detect("q", [A])
    assert detection.subject_ids == (A,) and not detection.unsure
    assert retriever.calls == []


async def test_searches_all_subjects_once_and_binds_the_clear_match() -> None:
    retriever = FakeRetriever([chunk(0.75, A), chunk(0.5, B), chunk(0.25, C)])
    detection = await SubjectDetector(retriever, POLICY).detect("What is attention?", [A, B, C])
    assert retriever.calls == [("What is attention?", [A, B, C], DETECTION_K)]
    assert detection.subject_ids == (A,) and not detection.unsure
    assert detection.scores == {A: 0.75, B: 0.5, C: 0.25}


async def test_binds_several_close_subjects() -> None:
    retriever = FakeRetriever([chunk(0.75, A, B), chunk(0.5, C)])
    detection = await SubjectDetector(retriever, POLICY).detect("q", [A, B, C])
    assert detection.subject_ids == (A, B) and not detection.unsure


async def test_unsure_falls_back_to_the_best_subject() -> None:
    retriever = FakeRetriever([chunk(0.75, B), chunk(0.65625, A)])  # A: outside multi_margin, inside detect_margin
    detection = await SubjectDetector(retriever, POLICY).detect("q", [A, B])
    assert detection.subject_ids == (B,) and detection.unsure


async def test_no_hits_falls_back_to_the_first_subject() -> None:
    detection = await SubjectDetector(FakeRetriever([]), POLICY).detect("q", [B, A])
    assert detection.subject_ids == (B,) and detection.unsure and detection.scores == {}


async def test_no_subjects_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        await SubjectDetector(FakeRetriever([]), POLICY).detect("q", [])
```

`tests/unit/tutoring/test_conversation_service.py`: keep the no-documents and processing tests but call `subjects_for_new_thread`; replace the one-subject test and `test_several_subjects_need_detection_which_is_not_built_yet` with:

```python
S2 = SubjectId("00000000-0000-4000-8000-000000000002")


def test_the_subjects_for_a_new_thread_are_the_learners_sorted() -> None:
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Attention is all you need.", subject_ids=[S2])
    ingest_ready(library, "ada", "Gradient descent.")  # General
    ingest_ready(library, "bob", "Photosynthesis.", subject_ids=[SubjectId("00000000-0000-4000-8000-000000000009")])
    subjects = service(library, InMemoryThreads(), FixedClock()).subjects_for_new_thread(UserId("ada"))
    assert subjects == [GENERAL_SUBJECT_ID, S2]


def test_starts_a_thread_with_the_detected_subjects() -> None:
    library, threads, clock = InMemoryLibrary(), InMemoryThreads(), FixedClock()
    ingest_ready(library, "ada", "Attention is all you need.", subject_ids=[GENERAL_SUBJECT_ID, S2])

    thread = service(library, threads, clock).start_thread(UserId("ada"), [S2, GENERAL_SUBJECT_ID])

    assert thread.user_id == "ada" and thread.subject_ids == (S2, GENERAL_SUBJECT_ID)
    assert thread.created_at == clock.now()
    assert threads.threads == {thread.thread_id: thread}


def test_a_subject_the_learner_does_not_have_is_refused() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    ingest_ready(library, "ada", "Attention is all you need.")
    with pytest.raises(ThreadSubjectsError):
        service(library, threads, FixedClock()).start_thread(UserId("ada"), [S2])
    assert threads.threads == {}


def test_no_subjects_or_more_than_three_is_refused() -> None:
    library, threads = InMemoryLibrary(), InMemoryThreads()
    many = [SubjectId(f"00000000-0000-4000-8000-00000000000{i}") for i in range(1, 5)]
    ingest_ready(library, "ada", "a", subject_ids=many[:3])
    ingest_ready(library, "ada", "b", subject_ids=many[3:])
    with pytest.raises(ThreadSubjectsError):
        service(library, threads, FixedClock()).start_thread(UserId("ada"), [])
    with pytest.raises(ThreadSubjectsError):
        service(library, threads, FixedClock()).start_thread(UserId("ada"), many)
    assert threads.threads == {}
```

(Two `ingest_ready` calls with different texts make two documents; identical texts share one content but are still two documents only for different owners — use distinct texts per owner.)

`tests/isolation/test_detection.py` — learner B's document in a shared subject never changes learner A's scores, end to end through the MCP server:

```python
"""US-12: detection scores come only from the learner's own documents, even in a shared subject."""

from collections.abc import Mapping

from fakes import FakeTokenVerifier, InMemoryLibrary, fake_embeddings, in_process_mcp, ingest_ready
from fakes.mcp import MCP_TEST_URL
from smart_tutor.apps.mcp_server import server
from smart_tutor.knowledge.application import SearchService
from smart_tutor.shared.config import Settings
from smart_tutor.shared.domain.ids import SubjectId, UserId
from smart_tutor.shared.domain.principal import Principal
from smart_tutor.tutoring.adapters.mcp_retriever import McpRetriever
from smart_tutor.tutoring.application import DetectionPolicy, SubjectDetector

S1 = SubjectId("00000000-0000-4000-8000-0000000000c1")
S2 = SubjectId("00000000-0000-4000-8000-0000000000c2")  # shared by both learners
QUESTION = "Photosynthesis makes glucose."
POLICY = DetectionPolicy(detect_threshold=0.35, detect_margin=0.05, multi_margin=0.03)


async def a_scores(with_b: bool) -> Mapping[SubjectId, float]:
    library = InMemoryLibrary()
    ingest_ready(library, "learner-a", "Attention weighs tokens.", subject_ids=[S1])
    ingest_ready(library, "learner-a", "Gradient descent follows the slope.", subject_ids=[S2])
    if with_b:
        ingest_ready(library, "learner-b", QUESTION, subject_ids=[S2])  # would score 1.0 in S2 if it leaked
    verifier = FakeTokenVerifier()
    verifier.add("token-a", Principal(UserId("learner-a"), "a", frozenset({"learner"})))
    mcp = server.build_server(Settings(), verifier, SearchService(library.unit_of_work, fake_embeddings()))
    async with in_process_mcp(mcp) as transport:
        retriever = McpRetriever(MCP_TEST_URL, "token-a", transport=transport)
        detection = await SubjectDetector(retriever, POLICY).detect(QUESTION, [S1, S2])
    return detection.scores


async def test_another_learners_chunks_in_a_shared_subject_never_change_the_scores() -> None:
    alone, together = await a_scores(with_b=False), await a_scores(with_b=True)
    assert together == alone
    assert set(together) == {S1, S2} and together[S2] < 0.999
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/tutoring tests/isolation/test_detection.py -q` → FAIL.

- [ ] **Step 3: Implement**

`subject_detector.py`:

```python
"""Detect a new thread's subjects from its first question (PRD §9.2 step 1, US-3)."""

from collections.abc import Sequence

from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.domain.detection import Detection, DetectionPolicy, best_scores
from smart_tutor.tutoring.ports.retriever import Retriever

DETECTION_K = 20  # one search over all of the learner's subjects; each subject scores its best chunk


class SubjectDetector:
    def __init__(self, retriever: Retriever, policy: DetectionPolicy) -> None:
        self._retriever = retriever
        self._policy = policy

    async def detect(self, question: str, learner_subjects: Sequence[SubjectId]) -> Detection:
        if not learner_subjects:
            raise ValueError("detection needs the learner's subjects")
        if len(learner_subjects) == 1:  # learners with one subject skip detection
            return Detection((learner_subjects[0],), unsure=False)
        chunks = await self._retriever.search(question, learner_subjects, DETECTION_K)
        scores = best_scores(chunks, among=learner_subjects)
        bound = self._policy.bind(scores)
        if bound is not None:
            return Detection(bound, unsure=False, scores=scores)
        # Unsure: until the learner is asked to pick (next slice of US-3), take the best subject.
        ranked = self._policy.ranked(scores)
        return Detection((ranked[0] if ranked else learner_subjects[0],), unsure=True, scores=scores)
```

`conversation_service.py`:

```python
"""Start a thread (PRD §8 US-3) with the subjects detected from its first question, all the learner's own."""

import uuid
from collections.abc import Sequence

from smart_tutor.knowledge.application import DocumentService
from smart_tutor.shared.domain.ids import SubjectId, ThreadId, UserId
from smart_tutor.shared.ports.clock import Clock
from smart_tutor.tutoring.domain.errors import NoDocumentsError, ThreadSubjectsError
from smart_tutor.tutoring.domain.thread import Thread
from smart_tutor.tutoring.ports.thread_repository import ThreadRepository


class ConversationService:
    def __init__(self, threads: ThreadRepository, documents: DocumentService, clock: Clock) -> None:
        self._threads = threads
        self._documents = documents
        self._clock = clock

    def subjects_for_new_thread(self, user_id: UserId) -> list[SubjectId]:
        """The learner's subjects, sorted: detection chooses among them. None → "Upload a document first"."""
        subjects = self._documents.learner_subjects(user_id)
        if not subjects:
            raise NoDocumentsError("Upload a document first")
        return sorted(subjects)

    def start_thread(self, user_id: UserId, subject_ids: Sequence[SubjectId]) -> Thread:
        """A new thread with 1 to 3 of the learner's own subjects, persisted."""
        if not set(subject_ids) <= set(self.subjects_for_new_thread(user_id)):
            raise ThreadSubjectsError("A thread's subjects are the learner's own")
        thread = Thread.start(ThreadId(str(uuid.uuid4())), user_id, subject_ids, self._clock.now())
        self._threads.add(thread)
        return thread
```

Remove `DetectionUnavailableError` from `errors.py` and `__init__.py`; export `DETECTION_K`, `Detection`, `DetectionPolicy`, `SubjectDetector`, `load_detection_policy` (Task 3 export kept) from `tutoring/application/__init__.py`. `apps/api/routes/threads.py` still imports `DetectionUnavailableError` and calls `start_thread(user_id)`: make it compile now by changing only the import and the `except` to `NoDocumentsError` and the call to `conversations.start_thread(principal.user_id, conversations.subjects_for_new_thread(principal.user_id)[:1])` — Task 6 replaces this; keep the API tests green (they have one subject).

`tutoring/README.md`: Built so far — add `DetectionPolicy`, `SubjectDetector` (one search, k = 20, over all of the learner's subjects; unsure falls back to the best subject until the learner is asked), `ConversationService.subjects_for_new_thread` / `start_thread(user_id, subject_ids)` (refuses subjects that aren't the learner's), thresholds from SSM (`load_detection_policy`). Replace the "Interim rule…" paragraph with: "**Interim rule until the learner is asked (US-3 criterion 3):** an unsure detection starts the thread with the best-scoring subject."

- [ ] **Step 4: Run all checks** → PASS.

- [ ] **Step 5: Commit** — "Detect a new thread's subjects from its first question".

---

### Task 5: The agent resolves subjects before searching and streams them first

**Files:**
- Create: `backend/src/smart_tutor/apps/agent/nodes/resolve_subjects.py`
- Modify: `backend/src/smart_tutor/apps/agent/graph.py`, `backend/src/smart_tutor/apps/agent/state.py`, `backend/src/smart_tutor/apps/agent/server.py`, `compose.yaml` (agent service)
- Test: `backend/tests/unit/apps/agent/test_graph.py`, `backend/tests/unit/apps/agent/test_server.py`, `backend/tests/unit/apps/agent/test_no_token_in_traces.py` (only if it builds the graph or request body)

**Interfaces:**
- Consumes: `SubjectDetector`, `DetectionPolicy`, `load_detection_policy` (Tasks 3–4); `MAX_SEARCH_SUBJECTS` (Task 1); `SsmParameterStore`, `ssm_client` (`smart_tutor.shared.adapters.aws.ssm_parameters`, `...aws.clients`).
- Produces: `build_graph(retriever_for, model, policy: DetectionPolicy) -> AskGraph`, nodes `resolve_subjects → search → answer`; `AskState.learner_subjects: dict[str, str]` (id → learner's name, in the order sent); agent `POST /ask` body `{"question": str, "learner_subjects": [{"subject_id", "name"}] (1–100)}`; SSE stream starts with `event: subjects` `{"subject_ids": [..1–3 ids..]}`, then `delta*`, `citations`, `done` (or `error` at any point, which may come before `subjects`).

- [ ] **Step 1: Failing tests**

`test_graph.py`: change `INPUT` to `{"question": "What is attention?", "learner_subjects": {"s1": "General"}}` and give every `build_graph` call a third argument `POLICY = DetectionPolicy(0.5, 0.125, 0.0625)`. The first test now expects `tokens == ["t-ada", "t-ada"]` (one retriever per node) and `out["subject_ids"] == ["s1"]`. Add:

```python
async def test_detects_the_subjects_then_searches_only_those() -> None:
    chunks = [
        RetrievedChunk("c1", "a.pdf", 3, "Attention weighs tokens.", 0.75, ("s2",)),
        RetrievedChunk("c2", "b.pdf", 1, "Unrelated.", 0.25, ("s1",)),
    ]
    retriever = FakeRetriever(chunks)
    graph = build_graph(lambda token: retriever, fake_chat_model(AIMessage("It weighs tokens [1].")), POLICY)
    out = await graph.ainvoke(
        {"question": "What is attention?", "learner_subjects": {"s1": "General", "s2": "LLMs"}},
        context=AgentContext(access_token="t"),
    )
    assert retriever.calls == [("What is attention?", ["s1", "s2"], 20), ("What is attention?", ["s2"], 5)]
    assert out["subject_ids"] == ["s2"] and out["subject_names"] == ["LLMs"]
```

`test_server.py`: `BODY = {"question": "What is attention?", "learner_subjects": [{"subject_id": "s1", "name": "General"}]}`; `client()` passes `POLICY` to `build_graph`. Update `test_no_chunks_streams_the_fixed_answer` to expect `("subjects", {"subject_ids": ["s1"]})` as the first event. Add:

```python
def test_the_subjects_event_comes_first() -> None:
    c, _ = client(FakeRetriever([CHUNK]))
    got = events(c.post("/ask", json=BODY, headers=AUTH).text)
    assert got[0] == ("subjects", {"subject_ids": ["s1"]})
    assert [e for e, _ in got].count("subjects") == 1


def test_a_detection_failure_is_an_error_before_any_subjects() -> None:
    body = {**BODY, "learner_subjects": [{"subject_id": "s1", "name": "A"}, {"subject_id": "s2", "name": "B"}]}
    c, _ = client(FakeRetriever(error=RetrievalError("down")))
    got = events(c.post("/ask", json=body, headers=AUTH).text)
    assert got == [("error", {"code": "unavailable", "message": "The tutor couldn't answer right now. Try again in a moment."})]


def test_more_than_100_subjects_is_422() -> None:
    c, _ = client(FakeRetriever([CHUNK]))
    many = [{"subject_id": f"s{i}", "name": "x"} for i in range(101)]
    assert c.post("/ask", json={**BODY, "learner_subjects": many}, headers=AUTH).status_code == 422
```

Also update the existing test that posts the old `subjects` field (if any asserts 422 for unknown fields, keep it with the new field name).

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/apps/agent -q` → FAIL.

- [ ] **Step 3: Implement**

`state.py`: add `learner_subjects: dict[str, str]  # all of the learner's subjects (id → their name); detection picks from them` above `subject_ids`; comment on `subject_ids`: `# the thread's 1–3 subjects, set by resolve_subjects`.

`nodes/resolve_subjects.py`:

```python
"""Resolve subjects (PRD §9.2 step 1): detect the new thread's subjects among the learner's, with their token."""

from collections.abc import Callable
from typing import Protocol

from langgraph.runtime import Runtime

from smart_tutor.apps.agent.state import AgentContext, AskState
from smart_tutor.shared.domain.ids import SubjectId
from smart_tutor.tutoring.application import DetectionPolicy, Retriever, SubjectDetector


class ResolveSubjectsNode(Protocol):
    async def __call__(self, state: AskState, *, runtime: Runtime[AgentContext]) -> AskState: ...


def resolve_subjects_node(retriever_for: Callable[[str], Retriever], policy: DetectionPolicy) -> ResolveSubjectsNode:
    async def resolve_subjects(state: AskState, *, runtime: Runtime[AgentContext]) -> AskState:
        learner = state["learner_subjects"]
        detector = SubjectDetector(retriever_for(runtime.context.access_token), policy)
        detection = await detector.detect(state["question"], [SubjectId(s) for s in learner])
        subject_ids = [str(s) for s in detection.subject_ids]
        return {"subject_ids": subject_ids, "subject_names": [learner[s] for s in subject_ids]}

    return resolve_subjects
```

`graph.py`: docstring `"""The ask graph (PRD §9.2): resolve subjects → search → answer. Single turn, no checkpointer (#31)."""`; `build_graph(retriever_for, model, policy: DetectionPolicy)`; add node `"resolve_subjects"` and edges `START → resolve_subjects → search → answer → END`.

`server.py`:
- `AskRequest.learner_subjects: list[SubjectIn] = Field(min_length=1, max_length=MAX_SEARCH_SUBJECTS)` (import from `smart_tutor.knowledge.application`), replacing `subjects`.
- Initial state: `{"question": body.question, "learner_subjects": {s.subject_id: s.name for s in body.learner_subjects}}`.
- In the `updates` branch: `elif part["type"] == "updates" and "resolve_subjects" in part["data"]: yield sse("subjects", {"subject_ids": part["data"]["resolve_subjects"]["subject_ids"]})` before the existing `"answer"` handling (make the two `updates` cases separate `elif`s).
- Module docstring: events start with `subjects` {"subject_ids"} (the thread's 1–3 subjects), then `delta`…; `error` may come first.
- Lifespan, when `graph is None`: `policy = load_detection_policy(SsmParameterStore(ssm_client(settings)), settings.detect_threshold_param, settings.detect_margin_param, settings.multi_margin_param)` and pass it to `build_graph`.

`compose.yaml` agent service `environment`: add `SMART_TUTOR_LOCALSTACK: "true"` and the same `AWS_ENDPOINT_URL_SSM` the `api` service uses (read the api block; copy its SSM endpoint line and the comment about dummy keys). Check `.env.example` and `make agent` work the same way the API's do (the host `.env` already sets the LocalStack endpoints for `make api`).

- [ ] **Step 4: Run all checks** → PASS.

- [ ] **Step 5: Commit** — "Resolve a new thread's subjects in the agent graph".

---

### Task 6: The API sends all the learner's subjects and starts the thread on the agent's `subjects` event

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py`, `backend/src/smart_tutor/apps/api/agent_client.py`
- Test: `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py`; regenerate `web/src/api/` only if `make api-client` shows a diff (the route's signature shouldn't change).

**Interfaces:**
- Consumes: `ConversationService.subjects_for_new_thread`, `start_thread(user_id, subject_ids)`, `ThreadSubjectsError` (Task 4); the agent's stream (Task 5).
- Produces: `AgentClient.open_answer(access_token, question, learner_subjects: list[tuple[str, str]])` posting `{"question", "learner_subjects": [{"subject_id", "name"}]}`; `POST /threads` SSE: `thread` {thread_id, subjects:[{subject_id, name}]} (unchanged shape; now 1–3 subjects), then the agent's events after its `subjects` event.

- [ ] **Step 1: Failing tests** in `test_thread_routes.py`

Change `AGENT_SSE` to start with `b'event: subjects\ndata: {"subject_ids": ["00000000-0000-4000-8000-000000000001"]}\n\n'` and define `AGENT_ANSWER` = the remaining events; the main test asserts `rest == AGENT_ANSWER.decode()` and the request JSON uses `"learner_subjects"`. Update the placeholder test to read `json.loads(seen[0].content)["learner_subjects"]`. Add (with `S2 = "00000000-0000-4000-8000-000000000002"`, and a second ready document of ada's in S2 named "LLMs" — give `api_services` a catalog/`subjects` override that names S2, reading `fakes/api.py` and `fakes/subjects.py` for how General is named):

```python
def test_the_thread_starts_with_the_subjects_the_agent_detected() -> None:
    # ada has General and S2; the agent sends both, detects both
    ...
    response = client.post("/threads", json=QUESTION, headers=AUTH)
    [thread] = threads.threads.values()
    assert thread.subject_ids == (S2, GENERAL)  # the order the agent sent
    first = response.text.split("\n\n", 1)[0]
    assert json.loads(first.split("data: ", 1)[1])["subjects"] == [
        {"subject_id": S2, "name": "LLMs"}, {"subject_id": GENERAL, "name": "General"}
    ]
    assert json.loads(seen[0].content)["learner_subjects"] == [
        {"subject_id": GENERAL, "name": "General"}, {"subject_id": S2, "name": "LLMs"}
    ]


def test_an_agent_error_before_subjects_is_relayed_and_starts_no_thread() -> None:
    error = b'event: error\ndata: {"code": "unavailable", "message": "x"}\n\n'
    client, threads, _ = setup(lambda r: httpx.Response(200, content=error, headers={"content-type": "text/event-stream"}))
    response = client.post("/threads", json=QUESTION, headers=AUTH)
    assert response.status_code == 200 and response.text == error.decode()
    assert threads.threads == {}


def test_a_subject_the_learner_does_not_have_starts_no_thread() -> None:
    bad = b'event: subjects\ndata: {"subject_ids": ["00000000-0000-4000-8000-000000000099"]}\n\n' + AGENT_ANSWER
    client, threads, _ = setup(lambda r: httpx.Response(200, content=bad, headers={"content-type": "text/event-stream"}))
    response = client.post("/threads", json=QUESTION, headers=AUTH)
    assert response.text == f"event: error\ndata: {json.dumps({'code': 'unavailable', 'message': UNAVAILABLE})}\n\n"
    assert threads.threads == {}


@pytest.mark.parametrize("first", [b"event: delta\ndata: {\"text\": \"hi\"}\n\n", b"event: subjects\ndata: nope\n\n", b""])
def test_a_stream_that_does_not_start_with_subjects_is_unavailable(first: bytes) -> None:
    client, threads, _ = setup(lambda r: httpx.Response(200, content=first, headers={"content-type": "text/event-stream"}))
    response = client.post("/threads", json=QUESTION, headers=AUTH)
    assert response.text.endswith(f"data: {json.dumps({'code': 'unavailable', 'message': UNAVAILABLE})}\n\n")
    assert "event: thread" not in response.text and threads.threads == {}
```

Keep the existing relay tests that split events across network chunks (update their payloads to begin with the `subjects` event). Add one where the `subjects` event itself arrives split across two chunks.

`tests/isolation/test_threads.py`: the `done` handler must now send a `subjects` event naming General first (both learners have General); assertions unchanged. Add a case: learner B's agent stream names a subject only learner A has → no thread for B.

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/unit/apps/api/test_thread_routes.py tests/isolation/test_threads.py -q` → FAIL.

- [ ] **Step 3: Implement**

`agent_client.py`: rename the parameter to `learner_subjects` and the JSON key to `"learner_subjects"`.

`routes/threads.py` (keep `_sse`, constants, `AskRequest`; drop the `DetectionUnavailableError` import):

```python
StartThread = Callable[[list[str]], Awaitable[bytes | None]]


def _event(raw: bytes) -> tuple[str, object] | None:
    """(name, data) of one SSE event without its blank line; None when it isn't one."""
    fields = dict(line.split(": ", 1) for line in raw.decode().splitlines() if ": " in line)
    try:
        return fields["event"], json.loads(fields["data"])
    except (KeyError, ValueError):
        return None


async def _relay(answer: AgentAnswer, start: StartThread) -> AsyncIterator[bytes]:
    """The agent's events, its first `subjects` event replaced by the `thread` event, forwarded only once complete.

    The thread is started only when the agent has detected its subjects; an `error` first is relayed as-is and starts
    none. Network reads can end inside an event; if the stream drops there, the partial event is dropped so the
    error event that follows stays a well-formed event of its own.
    """
    pending = b""
    started = False
    try:
        async for chunk in answer.chunks():
            pending += chunk
            complete, separator, pending = pending.rpartition(_EVENT_END)
            if not separator:
                continue
            block = complete + separator
            if not started:
                first, _, block = block.partition(_EVENT_END)
                started = True
                event = _event(first)
                if event is not None and event[0] == "error":
                    yield first + _EVENT_END
                else:
                    subject_ids = event[1].get("subject_ids") if event and event[0] == "subjects" and isinstance(event[1], dict) else None
                    thread_event = await start(subject_ids) if isinstance(subject_ids, list) else None
                    if thread_event is None:
                        yield _UNAVAILABLE_EVENT
                        return
                    yield thread_event
            if block:
                yield block
        if pending.strip() or not started:  # ended inside an event, or before the subjects
            yield _UNAVAILABLE_EVENT
    except httpx.HTTPError:
        yield _UNAVAILABLE_EVENT
    finally:
        await answer.aclose()
```

(Readability over this sketch is welcome — e.g. a small `_subject_ids(event) -> list[str] | None` helper — as long as the behavior and tests hold; mypy must pass.)

The route:

```python
    try:
        learner_subjects = await run_in_threadpool(conversations.subjects_for_new_thread, principal.user_id)
    except NoDocumentsError as e:
        raise HTTPException(409, str(e)) from None
    names = await run_in_threadpool(subjects.names_for, principal.user_id, learner_subjects)
    named: dict[str, str] = {}
    for s in learner_subjects:
        if not names.get(s):
            logger.warning("subject %s has no name; using a placeholder", s)
        named[s] = names.get(s) or UNNAMED_SUBJECT
    try:
        answer = await agent.open_answer(token, body.question, list(named.items()))
    except UnauthenticatedError:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"}) from None
    except AgentUnavailableError:
        raise HTTPException(503, UNAVAILABLE) from None

    async def start(subject_ids: list[str]) -> bytes | None:
        if not all(isinstance(s, str) for s in subject_ids):
            return None
        try:
            thread = await run_in_threadpool(
                conversations.start_thread, principal.user_id, [SubjectId(s) for s in subject_ids]
            )
        except (ThreadSubjectsError, NoDocumentsError) as e:
            logger.warning("the agent's subjects were refused: %s", e)  # ids only, never the question or token
            return None
        return _sse(
            "thread",
            {
                "thread_id": thread.thread_id,
                "subjects": [{"subject_id": s, "name": named.get(s, UNNAMED_SUBJECT)} for s in thread.subject_ids],
            },
        )

    return StreamingResponse(_relay(answer, start), media_type="text/event-stream", headers=SSE_HEADERS)
```

Update the module docstring ("…ask the first question of a new thread; the agent detects its subjects, then the API starts it") and the `SSE_RESPONSE` description stays "thread, then delta*, citations, done (or error)".

- [ ] **Step 4: Run all checks**, plus `cd backend && uv run python -m smart_tutor.apps.api.openapi_export` (or `make api-client`) and confirm `git diff web/src/api` is empty; if not, commit the regenerated client.

- [ ] **Step 5: Commit** — "Start the thread with the subjects the agent detects".

---

### Task 7: The chat header shows the thread's subjects as chips

**Files:**
- Modify: `web/src/features/chat/ChatPage.tsx`, `web/src/features/chat/ChatPage.module.css`
- Test: `web/src/features/chat/ChatPage.test.tsx`

**Interfaces:**
- Consumes: the `thread` event `{ type: "thread", thread_id, subjects: {subject_id, name}[] }` (unchanged, from `web/src/api/chat.ts`); `SubjectChip` (`web/src/components/SubjectChip/SubjectChip.tsx`: props `name`, `hueKey`, `size?: "sm" | "md" | "lg"`).
- Produces: UI only.

Read `DESIGN.md` (app shell, chat, chips, accessibility) and look at `.design-shots/v0.7/chat-subjects-detected{,-multi}.{light,dark}.png` (render with `cd web && npm run design:shots -- --states "chat-subjects-detected,chat-subjects-detected-multi" --round v0.7 --theme both`). The mockup: once a thread exists, the top of the page is a thread header — the first question as the title (one line, ellipsis when long) and below it the thread's subjects as small chips (dot coloured by subject, text in the main text colour). The citations toggle, Summarize, archive, token counter, and processing hint in the mockup belong to other tickets: leave them out.

- [ ] **Step 1: Failing tests** in `ChatPage.test.tsx` (reuse its fake `ask` helpers):

```tsx
it("shows the thread's subjects as chips under the question in the header", async () => {
  render(<ChatPage ask={fakeAsk([
    { type: "thread", thread_id: "t1", subjects: [{ subject_id: "s1", name: "LLMs" }, { subject_id: "s2", name: "AI Agents" }] },
    { type: "delta", text: "Answer." },
    { type: "citations", citations: [] },
    { type: "done" },
  ])} />);
  // ask "How does chain-of-thought help?" with the page's input, as the other tests do
  const heading = await screen.findByRole("heading", { level: 1, name: "How does chain-of-thought help?" });
  const header = heading.closest("header")!;
  const list = within(header).getByRole("list", { name: "Subjects" });
  expect(within(list).getAllByRole("listitem").map((li) => li.textContent)).toEqual(["LLMs", "AI Agents"]);
});

it("shows the Chat page header until a question is asked", () => {
  render(<ChatPage ask={fakeAsk([])} />);
  expect(screen.getByRole("heading", { level: 1, name: "Chat" })).toBeInTheDocument();
  expect(screen.queryByRole("list", { name: "Subjects" })).toBeNull();
});
```

Adapt helper names to the file's actual ones (`fakeAsk` is a placeholder for whatever the file uses to script events). Update any existing test that looked for the old subjects list outside the header.

- [ ] **Step 2: Run to verify failure** — `cd web && npx vitest run src/features/chat` → FAIL.

- [ ] **Step 3: Implement**

In `ChatPage.tsx`: when `exchange` is set, render a thread header in place of `PageHeader`:

```tsx
{exchange ? (
  <header className={styles.threadHeader}>
    <h1 className={styles.threadTitle} title={exchange.question}>{exchange.question}</h1>
    {exchange.subjects.length > 0 && (
      <ul className={styles.subjects} aria-label="Subjects">
        {exchange.subjects.map((s) => (
          <li key={s.subject_id}>
            <SubjectChip name={s.name} hueKey={s.subject_id} size="sm" />
          </li>
        ))}
      </ul>
    )}
  </header>
) : (
  <PageHeader title="Chat" description="Ask a question about your documents." />
)}
```

Remove the old subjects `<ul>` from the exchange block (keep the question bubble). CSS: delete `.subject`; add

```css
.threadHeader { display: grid; gap: var(--sp-2); padding-bottom: var(--sp-3); border-bottom: 1px solid var(--border); }
.threadTitle {
  margin: 0; font-size: var(--fs-16); font-weight: 600; color: var(--text);
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.subjects { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin: 0; padding: 0; list-style: none; }
```

Use only tokens that exist (check `web/src/styles/` for the exact `--fs-*` and weight tokens and use the ones `PageHeader.module.css` uses for its title if `--fs-16` doesn't exist).

- [ ] **Step 4: Run** `cd web && npx vitest run && npm run build` → PASS. Render the app state if you can (see `README` "Run the app" — `make web` against the running API) or compare the component visually with the mockups in both themes; at minimum check light and dark tokens are used (no hard-coded colours).

- [ ] **Step 5: Commit** — "Show a thread's subjects as chips in the chat header".

---

### Task 8: Final checks and docs

- [ ] Run every check from Global Constraints (backend, web, infra) and `uv run pytest -m integration tests/integration -q` (Compose is up).
- [ ] `git grep -n "DetectionUnavailableError\|1 to 3 subjects\|\"subjects\": \[{" backend web/src` — nothing stale left (the thread event's `subjects` key is expected in API/web code; the agent request must use `learner_subjects`).
- [ ] `CONTEXT.md`: if it defines detection terms, add "**Runner-up** — in subject detection, the best-scoring subject not bound to the thread." Otherwise skip.
- [ ] Commit any doc fixes.

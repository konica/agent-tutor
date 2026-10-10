# Citation highlight in the document viewer (#124) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One click on a Sources chip opens the cited document beside the conversation at the chunk's page, scrolls the passage into view, and highlights it; a passage that can't be found shows the page with "Couldn't highlight the passage on this page." and bumps a content-free counter.

**Architecture:** Backend: `chunks.start_index` (offset in the page's cleaned text) is set by the splitter (`add_start_index=True`) at ingestion and, for existing chunks, by a backfill the worker runs at startup (it locates each chunk's text in the saved `.pages.json`, so chunk ids don't change). `GET /chunks/{id}` (knowledge `ViewerService.passage`, through `can_read`, archived included) returns document, page, `start_index`, and text. `POST /viewer/highlight-misses` (new `insights.HighlightMissService`) adds one to a per-day counter row with no text, ids, or user. Web: a pure matcher (`features/viewer/passage.ts`) finds the chunk on the pdf.js text-layer items of its page after the chunking cleanup (NFKC, joined line-end hyphens, whitespace ignored), `start_index` choosing between repeats; `DocumentViewer` draws the highlight over the canvas from the items' positions, scrolls it to a third from the top, and announces the result; `ChatPage` turns Sources chips into buttons that open the pane with a passage and keep the shown chip highlighted.

**Tech Stack:** FastAPI, SQLAlchemy Core + Alembic, langchain-text-splitters, React 19 + TypeScript, Vitest + Testing Library, `pdfjs-dist@6.3.289` (already pinned).

**Spec:** GitHub issue #124 (parent #118); PRD v2.30 §8 US-4b, §9.2 step 6, §9.3 step 5, §9.4 Chunk, §10.1 "Citation highlight", Q56, Q59, Q60; `DESIGN.md` → Chat ("Split view"), Accessibility; mockups `design-v0.10` states `viewer-citation-highlight`, `viewer-no-highlight`, `chat-answer-citations` (render: `cd web && npm run design:shots -- --states "viewer-citation-highlight,viewer-no-highlight,chat-answer-citations" --round v0.10 --theme both`).

## Global Constraints

- Copy (verbatim): "Cited passage" (visible label), "Cited passage begins" / "Cited passage ends" (visually hidden), "Opened page 3 of 12. Cited passage highlighted." (polite status, numbers filled in), "Couldn't highlight the passage on this page." (visible note in the pane, and the status reads "Opened page 3 of 12. Couldn't highlight the passage on this page."). Chip accessible name: "<full title>, p. 3. Open beside the conversation" or, when shown, "<full title>, p. 3. Shown beside the conversation".
- `start_index`: nullable `integer` on `chunks`, the chunk's character offset in its page's **cleaned** text (`clean_page_text`). Never change `chunk_id`s; the chunker id stays `recursive_character:1000/200:v1` (the chunk texts don't change).
- Every chunk read goes through `can_read` in SQL (`readable_by(user_id)` joined via `documents.content_id = chunks.content_id`), archived documents included; anything else is `404 "Chunk not found"`.
- The miss counter stores only `(day, misses)`; no user id, chunk id, document id, or text — not in the table and not in logs.
- Highlight: soft accent fill over the passage, a 2px side marker, the "Cited passage" label; text over the fill ≥ 4.5:1 in light and dark (the PDF page stays white in both themes, so the highlight colors are fixed, not themed).
- Scroll target: the passage's top at about one third of the pane's visible height from the top.
- Web: API calls only through `src/api/`; regenerate `web/src/api/generated` after the routes land (`cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`). Build with existing components and tokens; never paste prototype HTML/CSS.
- Windows Git Bash: `PYTHONUTF8=1` for `lint-imports`; `make` may be missing — run the Makefile command directly.
- Backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Web: `cd web && npx vitest run && npm run build`.
- Commits: imperative subject, body says why, end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- The learner clicks a second chip of the **same** document while the first passage is shown: the viewer must not remount (no PDF reload), must jump to the new page, and must drop the old highlight before drawing the new one (Task 7 test "a second chip of the same document moves the highlight").
- The learner clicks chip A, then chip B of another document before A's chunk request returns: A's late chunk must never highlight in B's document (Task 7 test "a late chunk of a swapped-out passage is ignored").
- A chunk text repeated on its page (e.g. a heading or boilerplate sentence): `start_index` picks the occurrence nearest to it, not always the first (Task 5 test "start_index chooses between repeats").
- `GET /chunks/{id}` fails (network, 404 because the document was deleted after the answer): the page still opens (or the file's own error shows) and the note "Couldn't highlight…" appears once, counted once (Task 7 test "a failed chunk request shows the page without highlight").
- The learner zooms after the highlight is drawn: the boxes must scale with the canvas (Task 7 test "the highlight follows zoom").

---

### Task 1: `start_index` at ingestion

**Files:**
- Create: `backend/src/smart_tutor/knowledge/domain/page_text.py` (move `clean_page_text` here; add `locate_chunks`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/chunking.py` (import `clean_page_text` from the domain and re-export it for existing imports; `add_start_index=True`)
- Modify: `backend/src/smart_tutor/knowledge/domain/chunk.py` (`Chunk.start_index`, `start_index_of`)
- Modify: `backend/src/smart_tutor/knowledge/application/ingestion_service.py` (`_chunks` keeps `start_index`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_tables.py`, `sql_library.py` (`_Chunks.replace` writes `start_index`)
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0012_chunk_start_index.py`
- Modify: `backend/tests/fakes/processing.py` (`PageChunker` sets `start_index`)
- Test: `backend/tests/unit/knowledge/test_chunking.py`, `test_domain.py` (or a new `test_page_text.py`), `test_ingestion_service.py`

**Interfaces:**
- Produces:
  - `knowledge.domain.page_text.clean_page_text(text: str) -> str` (same behavior as today).
  - `knowledge.domain.page_text.locate_chunks(page_text: str, texts: Sequence[str]) -> list[int | None]` — offsets of each chunk text (in output order) in the cleaned page text; searches from the previous found offset + 1, falls back to the whole page, `None` when absent.
  - `knowledge.domain.chunk.start_index_of(value: object) -> int | None` — an `int >= 0` (not bool) as is, else `None` (the splitter returns `-1` when its `find` fails).
  - `Chunk(content_id, seq, page, text, embedding, start_index: int | None = None)` — new last field with a default so existing constructors keep working.

- [ ] **Step 1: Failing tests.**

In `tests/unit/knowledge/test_page_text.py`:

```python
from smart_tutor.knowledge.domain.page_text import clean_page_text, locate_chunks


def test_clean_page_text_is_the_chunking_cleanup() -> None:
    assert clean_page_text("ﬁne exam-\nple\x07 A-\nB") == "fine example A-\nB"


def test_locate_chunks_finds_each_chunk_in_order() -> None:
    page = "Alpha beta. Gamma delta. Alpha beta."
    assert locate_chunks(page, ["Alpha beta.", "Gamma delta.", "Alpha beta."]) == [0, 12, 25]


def test_locate_chunks_handles_overlapping_chunks() -> None:
    page = "one two three four five"
    assert locate_chunks(page, ["one two three", "three four five"]) == [0, 8]


def test_locate_chunks_leaves_a_missing_chunk_none_and_goes_on() -> None:
    page = "first part. second part."
    assert locate_chunks(page, ["first part.", "not here", "second part."]) == [0, None, 12]


def test_locate_chunks_falls_back_to_the_whole_page() -> None:
    # Out of order (shouldn't happen, but a chunk is still found rather than left None).
    assert locate_chunks("aaa bbb", ["bbb", "aaa"]) == [4, 0]
```

In `tests/unit/knowledge/test_chunking.py` add:

```python
def test_each_chunk_knows_its_offset_in_the_cleaned_page_text() -> None:
    chunker, _ = build_chunker(ChunkingConfig())
    raw = " ".join(f"ﬁeld{i} exam-\nple." for i in range(300))
    chunks = chunker.transform_documents([Document(page_content=raw, metadata={"page": 2})])
    cleaned = clean_page_text(raw)
    assert len(chunks) > 1
    for c in chunks:
        start = c.metadata["start_index"]
        assert cleaned[start : start + len(c.page_content)] == c.page_content
```

In `tests/unit/knowledge/test_ingestion_service.py` add a test (follow the file's existing helpers for making a stored content and running `process_content`) asserting that every stored chunk has `start_index` equal to its offset within its page's text: with the fake `PageChunker` (100-char pieces), page text `"x" * 250` gives chunks with `start_index` `0, 100, 200`. Read stored chunks from `library` state (`library._state.chunks[content_id]` or the helper the file already uses).

- [ ] **Step 2:** Run `cd backend && uv run pytest tests/unit/knowledge/test_page_text.py tests/unit/knowledge/test_chunking.py tests/unit/knowledge/test_ingestion_service.py -q` → FAIL (import error / KeyError `start_index`).

- [ ] **Step 3: Implement.**

`knowledge/domain/page_text.py`:

```python
"""A page's cleaned text: what chunks are cut from and what `start_index` counts in (PRD §9.2 step 6, §9.4)."""

import re
import unicodedata
from collections.abc import Sequence


def clean_page_text(text: str) -> str:
    """Fold ligatures, rejoin words hyphenated across lines, and drop control characters except \\n and \\t."""
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"(?<=[a-z])-\n(?=[a-z])", "", text)
    return "".join(c for c in text if c in "\n\t" or unicodedata.category(c) != "Cc")


def locate_chunks(page_text: str, texts: Sequence[str]) -> list[int | None]:
    """Each chunk's offset in the cleaned page text, chunks given in the chunker's order (None when absent).

    The splitter's chunks start in increasing order, so each search starts just after the previous chunk's start;
    that picks the right copy of a repeated passage. A chunk not found there is looked for in the whole page.
    """
    found: list[int | None] = []
    after = 0
    for text in texts:
        index = page_text.find(text, after)
        if index < 0:
            index = page_text.find(text)
        if index < 0:
            found.append(None)
            continue
        found.append(index)
        after = index + 1
    return found
```

`chunking.py`: delete the local `clean_page_text`, `import re`, `import unicodedata`; add `from smart_tutor.knowledge.domain.page_text import clean_page_text` and keep it importable (`__all__ = ["CleanedSplitter", "build_chunker", "clean_page_text"]`). Pass `add_start_index=True` to `RecursiveCharacterTextSplitter` with a comment: `# metadata["start_index"]: the chunk's offset in the cleaned page text (the viewer's highlight, PRD §9.4)`. Do not change the chunker id.

`chunk.py`: add `start_index: int | None = None  # offset in the page's cleaned text; None when unknown` as the last field of `Chunk`, and:

```python
def start_index_of(value: object) -> int | None:
    """The splitter's start offset, or None when it couldn't find the chunk (it reports -1) or gave none."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value
```

`ingestion_service._chunks`: carry the offset through:

```python
found = [
    (validate_chunk(p.metadata.get("page"), p.page_content), p.page_content, start_index_of(p.metadata.get("start_index")))
    for p in pieces
]
...
vectors = self._tools.embeddings.embed_documents([text for _, text, _ in found])
...
return [
    Chunk(content_id, seq, page, text, v, start)
    for seq, ((page, text, start), v) in enumerate(zip(found, vectors, strict=True))
]
```

`sql_tables.chunks`: add `Column("start_index", Integer),`. `sql_library._Chunks.replace`: add `"start_index": c.start_index,`.

Migration `0012_chunk_start_index.py` (copy 0011's header style):

```python
"""Each chunk's offset in its page's cleaned text, for the viewer's highlight (PRD §9.4, US-4b): chunks.start_index.

Nullable: existing chunks get it from the worker's backfill, and one whose text can't be located stays null.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-10
"""
...
def upgrade() -> None:
    op.add_column("chunks", sa.Column("start_index", sa.Integer, nullable=True))


def downgrade() -> None:
    op.drop_column("chunks", "start_index")
```

`fakes/processing.PageChunker`: `metadata={**d.metadata, "start_index": i}`.

- [ ] **Step 4:** Run the Step 2 command → PASS; then the full backend checks (Global Constraints). Update `knowledge/README.md`: in **Rules**, after "It extracts page text, saves it at …, chunks, embeds, and writes chunks via `ChunkRepository`", add "each chunk with its `start_index` (offset in its page's cleaned text, `clean_page_text`), or null when the splitter couldn't place it".
- [ ] **Step 5: Commit** — `git add -A backend && git commit` with subject "Record each chunk's offset in its page's cleaned text".

---

### Task 2: Backfill `start_index` for existing chunks

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py` (`ChunkRepository`: three methods; `StoredChunk`)
- Modify: `backend/src/smart_tutor/knowledge/domain/chunk.py` (`StoredChunk` dataclass)
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py`
- Modify: `backend/tests/fakes/knowledge.py`
- Create: `backend/src/smart_tutor/knowledge/application/start_index_backfill.py`
- Modify: `backend/src/smart_tutor/knowledge/application/__init__.py` (export `StartIndexBackfill`, `BackfillResult`)
- Modify: `backend/src/smart_tutor/apps/worker/main.py` (run it at startup, after `embed_missing_names`)
- Modify: `backend/src/smart_tutor/knowledge/README.md`
- Test: `backend/tests/unit/knowledge/test_start_index_backfill.py`, `backend/tests/integration/knowledge/test_sql_library.py` (SQL methods, `@pytest.mark.integration`, follow the file's fixtures)

**Interfaces:**
- Consumes: `locate_chunks`, `clean_page_text` (Task 1); `ObjectStore.read`, `ObjectNotFoundError`; `ContentRepository.get`.
- Produces:
  - `@dataclass(frozen=True) class StoredChunk: chunk_id: str; seq: int; page: int | None; text: str; start_index: int | None` (in `knowledge/domain/chunk.py`).
  - `ChunkRepository.contents_missing_start_index(self) -> list[ContentId]` — distinct content ids, ordered, of chunks with `start_index IS NULL` (no access check: a system job).
  - `ChunkRepository.list_for_content(self, content_id: ContentId) -> list[StoredChunk]` — ordered by `seq`.
  - `ChunkRepository.set_start_indexes(self, offsets: Mapping[str, int]) -> None` — `UPDATE chunks SET start_index = :v WHERE chunk_id = :id` per entry (an id that no longer exists updates nothing).
  - `@dataclass(frozen=True) class BackfillResult: located: int; missing: int`
  - `class StartIndexBackfill: __init__(self, uow: Callable[[], LibraryUnitOfWork], objects: ObjectStore)`; `run(self) -> BackfillResult`.
  - Fake chunk ids: `str(uuid.uuid5(uuid.NAMESPACE_URL, f"{content_id}:{seq}"))` — the same formula the fake's `search` already uses; factor it into a module function `fake_chunk_id(content_id, seq)` in `fakes/knowledge.py` and use it in both places.

- [ ] **Step 1: Failing unit tests** in `tests/unit/knowledge/test_start_index_backfill.py`. Build state directly: `library = InMemoryLibrary()`, `objects = FakeObjectStore()`; insert a ready content (use `Content.first_upload(...)` then `.ready(...)` as other tests do, or ingest through `IngestionService` with `fake_tools()` and then null out the offsets with `library._state.chunks[cid] = [replace(c, start_index=None) for c in ...]` — choose whichever the existing tests make shortest) and put `objects.objects[pages_key(owner, cid)] = json.dumps({"pages": [{"page": 1, "text": "ﬁrst para-\ngraph. second"}]}).encode()`. Cases:
  - chunks `["first paragraph.", "second"]` on page 1 with `start_index=None` → after `run()`, offsets `0` and `17`; result `BackfillResult(located=2, missing=0)`.
  - a chunk whose text isn't on its page → stays `None`, `missing == 1`, and a warning is logged naming the chunk id and content id (use `caplog`); the other chunks of the content still get their offsets.
  - a content whose `.pages.json` is missing (`ObjectNotFoundError`) → its chunks stay `None` and are counted missing; other contents are still processed.
  - chunks that already have `start_index` are not changed and the content is not read (assert `objects` read count, or that a content with all offsets set isn't listed by `contents_missing_start_index`).
  - a chunk with `page=None` → stays `None`, counted missing.
  - running `run()` twice: the second run locates nothing new and changes nothing.
- [ ] **Step 2:** `cd backend && uv run pytest tests/unit/knowledge/test_start_index_backfill.py -q` → FAIL (import error).
- [ ] **Step 3: Implement.**

```python
"""Give existing chunks their `start_index` by locating their text in the saved page text (PRD §9.4).

Chunk ids and texts stay as they are, so citations keep working. The worker runs it at startup; it only reads
contents that still have a chunk without an offset, so after the first run it is cheap. A chunk whose text can't be
located stays null and is logged (the viewer then shows its page without a highlight).
"""

import json
import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from smart_tutor.knowledge.domain.chunk import StoredChunk
from smart_tutor.knowledge.domain.page_text import clean_page_text, locate_chunks
from smart_tutor.knowledge.ports.library import LibraryUnitOfWork
from smart_tutor.knowledge.ports.object_store import ObjectNotFoundError, ObjectStore
from smart_tutor.shared.domain.ids import ContentId

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillResult:
    located: int
    missing: int


class StartIndexBackfill:
    def __init__(self, uow: Callable[[], LibraryUnitOfWork], objects: ObjectStore) -> None:
        self._uow, self._objects = uow, objects

    def run(self) -> BackfillResult:
        with self._uow() as tx:
            content_ids = tx.chunks.contents_missing_start_index()
        located = missing = 0
        for content_id in content_ids:
            found, lost = self._content(content_id)
            located, missing = located + found, missing + lost
        return BackfillResult(located, missing)

    def _content(self, content_id: ContentId) -> tuple[int, int]:
        with self._uow() as tx:
            content = tx.contents.get(content_id)
            chunks = [c for c in tx.chunks.list_for_content(content_id) if c.start_index is None]
        pages = self._pages(content.text_key) if content is not None and content.text_key else None
        if pages is None:
            logger.warning("content %s: no saved page text; %d chunks keep no start_index", content_id, len(chunks))
            return 0, len(chunks)
        by_page: dict[int | None, list[StoredChunk]] = defaultdict(list)
        for chunk in chunks:
            by_page[chunk.page].append(chunk)
        offsets: dict[str, int] = {}
        for page, on_page in by_page.items():
            text = pages.get(page) if page is not None else None
            starts = locate_chunks(clean_page_text(text), [c.text for c in on_page]) if text is not None else []
            for chunk, start in zip(on_page, starts or [None] * len(on_page), strict=True):
                if start is None:
                    logger.warning("chunk %s of content %s: text not found on its page; start_index stays null",
                                   chunk.chunk_id, content_id)
                else:
                    offsets[chunk.chunk_id] = start
        with self._uow() as tx:
            tx.chunks.set_start_indexes(offsets)
            tx.commit()
        return len(offsets), len(chunks) - len(offsets)

    def _pages(self, key: str) -> dict[int, str] | None:
        try:
            listing = json.loads(self._objects.read(key))
        except ObjectNotFoundError:
            return None
        return {int(p["page"]): str(p["text"]) for p in listing["pages"]}
```

Note: `list_for_content` returns every chunk ordered by `seq`; the service filters to null ones. But `locate_chunks` must see the null ones **in seq order**; if some chunks of a page already have offsets, searching only the null ones from the page start is still correct thanks to the whole-page fallback. Keep it.

SQL (`sql_library._Chunks`):

```python
def contents_missing_start_index(self) -> list[ContentId]:
    rows = self._conn.execute(
        select(chunks.c.content_id).where(chunks.c.start_index.is_(None)).distinct().order_by(chunks.c.content_id)
    )
    return [ContentId(str(r.content_id)) for r in rows]

def list_for_content(self, content_id: ContentId) -> list[StoredChunk]:
    rows = self._conn.execute(
        select(chunks.c.chunk_id, chunks.c.seq, chunks.c.page, chunks.c.text, chunks.c.start_index)
        .where(chunks.c.content_id == content_id)
        .order_by(chunks.c.seq)
    )
    return [StoredChunk(str(r.chunk_id), r.seq, r.page, r.text, r.start_index) for r in rows]

def set_start_indexes(self, offsets: Mapping[str, int]) -> None:
    for chunk_id, start in offsets.items():
        self._conn.execute(update(chunks).where(chunks.c.chunk_id == chunk_id).values(start_index=start))
```

Fake: same semantics over `self._s.chunks` (ids from `fake_chunk_id`; `set_start_indexes` replaces matching `Chunk`s with `dataclasses.replace(c, start_index=...)`).

Worker (`apps/worker/main.py`), right after the subject-name backfill:

```python
library_objects = S3ObjectStore(s3_client(settings), settings.documents_bucket)
offsets = StartIndexBackfill(library, library_objects).run()  # chunks from before start_index (#124)
logger.info("start_index backfill: %d located, %d left null", offsets.located, offsets.missing)
ingestion = IngestionService(library, library_objects, tools, limits)
```

Integration test (marked, follows `tests/integration/knowledge/test_sql_library.py` fixtures): insert a content with two chunks (`start_index` None and 5), check `contents_missing_start_index` lists it once, `list_for_content` returns both in seq order with their offsets, `set_start_indexes` sets the null one and the content then disappears from `contents_missing_start_index`. (Not in CI; run it if Compose is up: `uv run pytest -m integration tests/integration/knowledge/test_sql_library.py -q`.)

README **Rules**: add "`StartIndexBackfill.run` (worker startup) gives chunks without `start_index` their offset by locating their text (`locate_chunks`) in their page's cleaned saved text; chunk ids never change; a chunk it can't locate, or one whose `.pages.json` is missing, stays null and is logged." Add `StartIndexBackfill` to **Key classes** and the three methods to the `ChunkRepository` port list.
- [ ] **Step 4:** Unit tests PASS; full backend checks pass.
- [ ] **Step 5: Commit** — "Backfill start_index for existing chunks at worker startup".

---

### Task 3: `GET /chunks/{id}`

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/domain/chunk.py` (`ChunkPassage`)
- Modify: `backend/src/smart_tutor/knowledge/domain/errors.py` (`ChunkNotFoundError`)
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py` (`ChunkRepository.get_readable`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py`, `backend/tests/fakes/knowledge.py`
- Modify: `backend/src/smart_tutor/knowledge/application/viewer_service.py` (`passage`), `application/__init__.py` (export `ChunkPassage`, `ChunkNotFoundError`)
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py`
- Modify: `backend/src/smart_tutor/knowledge/README.md`
- Test: `backend/tests/unit/knowledge/test_viewer_service.py`, `backend/tests/isolation/test_chunks.py` (new), `backend/tests/isolation/README.md` (list it, if the README lists files)

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class ChunkPassage: chunk_id: str; document_id: DocumentId; page: int | None; start_index: int | None; text: str`
  - `ChunkRepository.get_readable(self, user_id: UserId, chunk_id: str) -> ChunkPassage | None` — `can_read` in SQL, archived included, any state; a malformed id returns None (the route's `UUID` path type already refuses malformed ids with 422).
  - `ViewerService.passage(self, user_id: UserId, chunk_id: str) -> ChunkPassage` raises `ChunkNotFoundError("This passage isn't in your library")`.
  - Route `GET /chunks/{chunk_id}`, `operation_id="get_chunk"`, response `ChunkResponse { chunk_id: str; document_id: str; page: int | None; start_index: int | None; text: str }`, `404 "Chunk not found"`.

- [ ] **Step 1: Failing tests.**

`test_viewer_service.py` (reuse its helpers for a ready document): `passage` returns the chunk's document id, page, start_index, text for the owner; an archived document's chunk is returned; another learner → `ChunkNotFoundError`; unknown id → `ChunkNotFoundError`. Get a real chunk id with `fake_chunk_id(content_id, 0)` from `fakes.knowledge`.

`tests/isolation/test_chunks.py`:

```python
"""US-12, US-4b: a learner reads a chunk only through a document they can read (archived included)."""

from fakes.knowledge import fake_chunk_id
from isolation.test_documents import A, B, setup_with_library  # if importing across test files is not the
# convention there, copy setup_with_library's few lines instead.


def _ready_document(client, objects, ingestion) -> tuple[str, str]:
    stored = client.post("/uploads", json={"file_name": "a1.pdf"}, headers=A).json()
    objects.objects[stored["fields"]["key"]] = b"%PDF-1.7 " + ("A sentence about attention mechanisms. " * 5).encode()
    ingestion.ingest_upload(stored["fields"]["key"])
    return stored["document_id"], stored["fields"]["key"]


def test_b_cannot_read_a_chunk_of_as_document() -> None:
    client, objects, ingestion, library = setup_with_library()
    doc, _ = _ready_document(client, objects, ingestion)
    content_id = library._state.documents[doc].content_id  # or the accessor the fakes provide
    chunk = fake_chunk_id(content_id, 0)

    assert client.get(f"/chunks/{chunk}", headers=B).status_code == 404
    mine = client.get(f"/chunks/{chunk}", headers=A)
    assert mine.status_code == 200
    body = mine.json()
    assert body["document_id"] == doc and body["page"] == 1 and body["start_index"] == 0
    assert body["text"].startswith("A sentence about attention")


def test_a_chunk_of_an_archived_document_is_still_readable_by_its_owner() -> None:
    client, objects, ingestion, library = setup_with_library()
    doc, _ = _ready_document(client, objects, ingestion)
    client.post(f"/documents/{doc}/archive", headers=A)
    chunk = fake_chunk_id(library._state.documents[doc].content_id, 0)
    assert client.get(f"/chunks/{chunk}", headers=A).status_code == 200
    assert client.get(f"/chunks/{chunk}", headers=B).status_code == 404


def test_an_unknown_chunk_is_404() -> None:
    client, *_ = setup_with_library()
    assert client.get("/chunks/00000000-0000-4000-8000-000000000000", headers=A).status_code == 404
```

Adjust attribute paths to the fake's real internals (read `tests/fakes/knowledge.py` `_State` first). If the ingested document is still `awaiting_subjects`, that is fine: chunks exist and the route serves any state.

- [ ] **Step 2:** Run both test files → FAIL.
- [ ] **Step 3: Implement.** SQL:

```python
def get_readable(self, user_id: UserId, chunk_id: str) -> ChunkPassage | None:
    try:
        uuid.UUID(chunk_id)
    except ValueError:
        return None
    row = self._conn.execute(
        select(chunks.c.chunk_id, chunks.c.page, chunks.c.start_index, chunks.c.text, documents.c.document_id)
        .join(documents, documents.c.content_id == chunks.c.content_id)
        .where(chunks.c.chunk_id == chunk_id, readable_by(user_id))
    ).first()
    if row is None:
        return None
    return ChunkPassage(str(row.chunk_id), DocumentId(str(row.document_id)), row.page, row.start_index, row.text)
```

Fake: iterate documents with `can_be_read_by(user_id)` (archived included) and their content's chunks; match `fake_chunk_id(content_id, c.seq) == chunk_id`.

Service:

```python
def passage(self, user_id: UserId, chunk_id: str) -> ChunkPassage:
    """A cited chunk, for the viewer's highlight: only through a document the caller can read, archived included."""
    with self._uow() as tx:
        found = tx.chunks.get_readable(user_id, chunk_id)
    if found is None:
        raise ChunkNotFoundError("This passage isn't in your library")
    return found
```

Route (`routes/knowledge.py`; mention chunks in the module docstring):

```python
class ChunkResponse(BaseModel):
    chunk_id: str
    document_id: str
    page: int | None
    start_index: int | None  # offset in the page's cleaned text; null when unknown
    text: str


@router.get("/chunks/{chunk_id}", operation_id="get_chunk", responses={404: {"description": "Not the caller's chunk."}})
def get_chunk(chunk_id: UUID, principal: CurrentPrincipal, viewer: Viewer) -> ChunkResponse:
    """A cited passage for the viewer's highlight (PRD §8 US-4b, §9.3 step 5), through a readable document only."""
    try:
        found = viewer.passage(principal.user_id, str(chunk_id))
    except ChunkNotFoundError:
        raise HTTPException(404, "Chunk not found") from None
    return ChunkResponse(
        chunk_id=found.chunk_id, document_id=found.document_id, page=found.page,
        start_index=found.start_index, text=found.text,
    )
```

README: add `ViewerService` (`file`, `passage`) and the rule "`ViewerService.passage` reads a chunk through `can_read` in SQL (archived included, any state); others' and unknown chunks are `ChunkNotFoundError` (404)".
- [ ] **Step 4:** Tests PASS; full backend checks.
- [ ] **Step 5: Commit** — "Serve a cited chunk to the viewer through a readable document".

---

### Task 4: Content-free counter of "Couldn't highlight" views

**Files:**
- Create: `backend/src/smart_tutor/insights/ports/highlight_misses.py` (`HighlightMissCounter`)
- Create: `backend/src/smart_tutor/insights/application/highlight_miss_service.py`; export from `insights/application/__init__.py`
- Create: `backend/src/smart_tutor/insights/adapters/sql_highlight_misses.py`
- Create: `backend/src/smart_tutor/shared/adapters/postgres/migrations/versions/0013_highlight_misses.py`
- Create: `backend/src/smart_tutor/apps/api/routes/insights.py`; include it in `apps/api/main.py` like the other routers
- Modify: `apps/api/services.py` (`highlight_misses: HighlightMissService`), `apps/api/deps.py` (`HighlightMisses`), `tests/fakes/api.py`
- Create: `backend/tests/fakes/insights.py` (`InMemoryHighlightMisses`); export from `fakes/__init__.py`
- Modify: `backend/src/smart_tutor/insights/README.md`, `docs/runbooks/on-premise-monitoring.md`, `sdd/prd.md`
- Then regenerate the web API client (Global Constraints command) — this task is the last backend route.
- Test: `backend/tests/unit/insights/test_highlight_miss_service.py` (create `tests/unit/insights/__init__.py` only if sibling test folders have one), `backend/tests/unit/api/…` or wherever route tests live (find with `grep -rln "TestClient" tests/unit | head`) — a route test.

**Interfaces:**
- Produces:
  - `class HighlightMissCounter(ABC): increment(self, day: date) -> None` (adds one to that day's count).
  - `class HighlightMissService: __init__(self, counter: HighlightMissCounter, clock: Clock)`; `record(self) -> None` — `counter.increment(clock.now().astimezone(UTC).date())`.
  - SQL table `highlight_misses(day date primary key, misses integer not null)`; `SqlHighlightMisses(engine)` upserts `INSERT … ON CONFLICT (day) DO UPDATE SET misses = highlight_misses.misses + 1` in its own transaction.
  - Route `POST /viewer/highlight-misses`, `operation_id="record_highlight_miss"`, no body, `204`, needs a signed-in learner (the app-wide `current_principal` dependency) but stores nothing about them.

- [ ] **Step 1: Failing tests.** Service: two `record()` calls on one day and one on the next (move `FixedClock.current`) → fake counts `{day1: 2, day2: 1}`. Route: `POST /viewer/highlight-misses` with a token → 204 and the fake count is 1; without a token → 401; a JSON body is ignored (still 204, nothing else stored). Fake: `InMemoryHighlightMisses.counts: dict[date, int]`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3: Implement.** Follow `subjects/adapters/sql_subjects.py` for an engine-based adapter with its own `Table` definition. Migration 0013 (Revises 0012): `op.create_table("highlight_misses", sa.Column("day", sa.Date, primary_key=True), sa.Column("misses", sa.Integer, nullable=False))`; downgrade drops it. Route module docstring: "Quality monitoring (insights): a content-free count of citation highlights the viewer couldn't draw (PRD §10.1)". Wire `HighlightMissService(SqlHighlightMisses(engine), SystemClock())` in `build_services` and the fake in `api_services` (`"highlight_misses": HighlightMissService(InMemoryHighlightMisses(), clock)`; let tests pass their own through `overrides`).

  `insights/README.md`: Owns adds "the count of citation highlights the viewer couldn't draw"; Key classes `HighlightMissService`, port `HighlightMissCounter`; Rules: "The highlight-miss count is one number per UTC day: never a user id, chunk, document, or text."

  Runbook `docs/runbooks/on-premise-monitoring.md`: add a section "Citation highlight misses" — what it counts (each time the viewer shows "Couldn't highlight the passage on this page."), how to read it (`dc exec postgres psql -U postgres -d <app database> -c "SELECT day, misses FROM highlight_misses ORDER BY day DESC LIMIT 30;"` — use the database/user names the runbook already uses elsewhere), and what to do when it climbs (check recent uploads' chunks for null `start_index`, compare with the seed-corpus matcher test in `web/src/features/viewer/passage.seed.test.ts`).

  PRD (`sdd/prd.md`): bump the status line to **v2.31**; add a row at the top of the change log: `| **Changes from v2.30** | Citation highlight (#124, US-4b): \`chunks.start_index\` is set at ingestion and backfilled by the worker at startup for existing chunks (ids unchanged; a chunk that can't be located stays null); \`GET /chunks/{id}\` returns document, page, \`start_index\`, and text through a readable document (archived included), else \`404\`; \`POST /viewer/highlight-misses\` (204) counts "Couldn't highlight" views per UTC day in \`highlight_misses\` with no user, ids, or text. |`; in the §9.4 data-model table add a row after "Decline log": `| Highlight misses | PostgreSQL \`highlight_misses\` | \`day\` | Count of "Couldn't highlight the passage on this page." views that day (§10.1). **No user id, ids, or text.** |`.

  Regenerate the web client (command in Global Constraints) and commit `web/src/api/openapi.json` + `web/src/api/generated/`.
- [ ] **Step 4:** Tests PASS; full backend checks; `cd web && npm run build` still passes.
- [ ] **Step 5: Commit** — "Count citation highlights the viewer couldn't draw".

---

### Task 5: The passage matcher (web, pure)

**Files:**
- Create: `web/src/features/viewer/passage.ts`
- Test: `web/src/features/viewer/passage.test.ts`

**Interfaces:**
- Produces:
  - `export type TextItem = { str: string; hasEOL: boolean; x: number; y: number; width: number; height: number };` — one pdf.js text-content item; box in CSS px at zoom 100%, origin top-left of the page.
  - `export type PassageSpan = { start: { item: number; offset: number }; end: { item: number; offset: number } };` — `end` exclusive.
  - `export function matchKey(source: string): { key: string; map: number[] }` — the comparison form: NFKC, line-end hyphens between lowercase letters joined (`-\n` removed), all whitespace and control characters removed; `map[i]` is the index in `source` of `key[i]`.
  - `export function findPassage(items: Pick<TextItem, "str" | "hasEOL">[], text: string, startIndex: number | null): PassageSpan | null`
  - `export type Box = { x: number; y: number; width: number; height: number };`
  - `export function passageBoxes(items: TextItem[], span: PassageSpan): Box[]` — one box per text line (items whose vertical centers are within half a line height merge into their union), sorted top to bottom.

- [ ] **Step 1: Failing tests** (`passage.test.ts`):

```ts
import { describe, expect, it } from "vitest";
import { findPassage, matchKey, passageBoxes, type TextItem } from "./passage";

const item = (str: string, hasEOL = false, x = 0, y = 0, width = str.length * 5, height = 10): TextItem => ({ str, hasEOL, x, y, width, height });

describe("matchKey", () => {
  it("folds ligatures, joins line-end hyphens, and drops whitespace", () => {
    expect(matchKey("ﬁne exam-\nple  A-\nB").key).toBe("fineexampleA-B");
  });
  it("maps each key character back to the source", () => {
    const { key, map } = matchKey("a ﬁ b");
    expect(key).toBe("afib");
    expect(map).toEqual([0, 2, 2, 4]);
  });
});

describe("findPassage", () => {
  const items = [item("Reasoning traces help the model in-", true), item("duce, track, and update", true), item("action plans.", true)];

  it("finds a chunk across items, hyphenation, and line breaks", () => {
    const span = findPassage(items, "help the model induce, track, and update action plans.", 0);
    expect(span).toEqual({ start: { item: 0, offset: 16 }, end: { item: 2, offset: 13 } });
  });
  it("matches whatever spacing each extractor used", () => {
    const spaced = [item("Thought"), item(" : "), item("I need to search"), item("Apple Remote", true)];
    expect(findPassage(spaced, "Thought: I need to search Apple Remote", null)).not.toBeNull();
  });
  it("start_index chooses between repeats", () => {
    const repeated = [item("Answer the question. ", false), item("Some text in between here. ", false), item("Answer the question.", true)];
    expect(findPassage(repeated, "Answer the question.", 0)?.start.item).toBe(0);
    expect(findPassage(repeated, "Answer the question.", 47)?.start.item).toBe(2);
  });
  it("falls back to the chunk's first and last words when the middle differs", () => {
    const head = "The agent first reads the question and then decides what to search for";
    const tail = "before it writes its final answer for the learner to read";
    const page = [item(`${head} [a footnote marker 1] ${tail}`, true)];
    const span = findPassage(page, `${head} ${tail}`, null);
    expect(span?.start).toEqual({ item: 0, offset: 0 });
    expect(span?.end.offset).toBe(page[0]!.str.length);
  });
  it("returns null when the chunk isn't on the page", () => {
    expect(findPassage(items, "Nothing like this appears on the page at all.", 0)).toBeNull();
  });
  it("returns null for a blank chunk", () => {
    expect(findPassage(items, "  \n ", 0)).toBeNull();
  });
});

describe("passageBoxes", () => {
  it("draws one box per line, partial at the ends", () => {
    const lines = [item("aaaa bbbb", true, 10, 0, 90, 10), item("cccc", false, 10, 12, 40, 10), item(" dddd", true, 50, 12, 50, 10)];
    const boxes = passageBoxes(lines, { start: { item: 0, offset: 5 }, end: { item: 2, offset: 3 } });
    expect(boxes).toHaveLength(2);
    expect(boxes[0]).toEqual({ x: 60, y: 0, width: 40, height: 10 });
    expect(boxes[1]).toEqual({ x: 10, y: 12, width: 70, height: 10 });
  });
});
```

(Adjust only the expected numbers if your exact arithmetic differs but the behavior is the same; keep every case.)

- [ ] **Step 2:** `cd web && npx vitest run src/features/viewer/passage.test.ts` → FAIL.
- [ ] **Step 3: Implement** `passage.ts`:

```ts
// Finds a cited chunk on the pdf.js text layer of its page (PRD §9.3 step 5). The chunk was cut from pypdf's text after
// the chunking cleanup (NFKC, joined line-end hyphens); pdf.js splits and spaces the same words differently, so both
// sides are compared in one key form: the same cleanup, then no whitespace at all (the extreme of collapsing it).

export type TextItem = { str: string; hasEOL: boolean; x: number; y: number; width: number; height: number };
export type PassageSpan = { start: { item: number; offset: number }; end: { item: number; offset: number } };
export type Box = { x: number; y: number; width: number; height: number };

const EDGE = 40; // key characters compared at each end when the whole chunk isn't found
const SPAN_SLACK = 0.3; // a head-to-tail match may be 30% shorter or longer than the chunk

export function matchKey(source: string): { key: string; map: number[] } {
  // 1. NFKC per source character, remembering where each output character came from.
  const chars: string[] = [];
  const from: number[] = [];
  for (let i = 0; i < source.length; i++) {
    for (const c of source[i]!.normalize("NFKC")) {
      chars.push(c);
      from.push(i);
    }
  }
  // 2. Join words hyphenated across lines (lowercase on both sides), as clean_page_text does; 3. drop whitespace and
  // control characters.
  const key: string[] = [];
  const map: number[] = [];
  for (let i = 0; i < chars.length; i++) {
    const c = chars[i]!;
    if (c === "-" && chars[i + 1] === "\n" && /[a-z]/.test(chars[i - 1] ?? "") && /[a-z]/.test(chars[i + 2] ?? "")) {
      i++; // skip the hyphen and the line break
      continue;
    }
    if (/\s/.test(c) || /\p{Cc}/u.test(c)) continue;
    key.push(c);
    map.push(from[i]!);
  }
  return { key: key.join(""), map };
}

function occurrences(haystack: string, needle: string): number[] {
  const found: number[] = [];
  for (let i = haystack.indexOf(needle); i >= 0; i = haystack.indexOf(needle, i + 1)) found.push(i);
  return found;
}

// start_index counts characters of the cleaned text with its whitespace; the key has none, so compare positions by
// their share of the page rather than as raw offsets. Null start_index: no preference (the first match wins).
function targetOf(startIndex: number | null, keyLength: number, sourceLength: number): number | null {
  return startIndex === null ? null : (startIndex / Math.max(1, sourceLength)) * keyLength;
}

// Candidates ordered nearest-first to the target (stable: equal distances keep page order).
function byNearness(candidates: number[], target: number | null): number[] {
  return target === null ? candidates : [...candidates].sort((a, b) => Math.abs(a - target) - Math.abs(b - target));
}

export function findPassage(items: Pick<TextItem, "str" | "hasEOL">[], text: string, startIndex: number | null): PassageSpan | null {
  // The page as the text layer reads it, and which item each character belongs to.
  let source = "";
  const owner: { item: number; offset: number }[] = [];
  items.forEach((it, index) => {
    for (let o = 0; o < it.str.length; o++) owner.push({ item: index, offset: o });
    source += it.str;
    if (it.hasEOL) {
      owner.push({ item: index, offset: it.str.length });
      source += "\n";
    }
  });
  const page = matchKey(source);
  const chunk = matchKey(text).key;
  if (!chunk) return null;

  const target = targetOf(startIndex, page.key.length, source.length);
  let start: number | undefined = byNearness(occurrences(page.key, chunk), target)[0];
  let end = start === undefined ? undefined : start + chunk.length;
  if (start === undefined && chunk.length >= 2 * EDGE) {
    const head = chunk.slice(0, EDGE);
    const tail = chunk.slice(-EDGE);
    for (const h of byNearness(occurrences(page.key, head), target)) {
      const t = page.key.indexOf(tail, h + EDGE);
      if (t < 0) continue;
      const length = t + EDGE - h;
      if (Math.abs(length - chunk.length) <= chunk.length * SPAN_SLACK) {
        start = h;
        end = t + EDGE;
        break;
      }
    }
  }
  if (start === undefined || end === undefined) return null;
  const first = owner[page.map[start]!]!;
  const last = owner[page.map[end - 1]!]!;
  return { start: first, end: { item: last.item, offset: last.offset + 1 } };
}
```

Then `passageBoxes`:

```ts
export function passageBoxes(items: TextItem[], span: PassageSpan): Box[] {
  const pieces: Box[] = [];
  for (let i = span.start.item; i <= span.end.item; i++) {
    const it = items[i]!;
    const length = it.str.length;
    if (length === 0 || it.width <= 0) continue;
    const from = i === span.start.item ? Math.min(span.start.offset, length) : 0;
    const to = i === span.end.item ? Math.min(span.end.offset, length) : length;
    if (to <= from) continue;
    pieces.push({ x: it.x + (it.width * from) / length, y: it.y, width: (it.width * (to - from)) / length, height: it.height });
  }
  const lines: Box[] = [];
  for (const p of pieces) {
    const line = lines.find((l) => Math.abs(l.y + l.height / 2 - (p.y + p.height / 2)) < Math.max(l.height, p.height) / 2);
    if (!line) {
      lines.push({ ...p });
      continue;
    }
    const right = Math.max(line.x + line.width, p.x + p.width);
    const bottom = Math.max(line.y + line.height, p.y + p.height);
    line.x = Math.min(line.x, p.x);
    line.y = Math.min(line.y, p.y);
    line.width = right - line.x;
    line.height = bottom - line.y;
  }
  return lines.sort((a, b) => a.y - b.y || a.x - b.x);
}
```

- [ ] **Step 4:** Tests PASS; `npm run build` passes.
- [ ] **Step 5: Commit** — "Find a cited chunk on the pdf.js text layer".

---

### Task 6: Seed-corpus fixture and the ≥ 95% matcher test

The seed corpus manifest is empty (`documents: []`) and PDFs aren't committed. This task adds four CC BY 4.0 arXiv papers to the manifest and commits a **text fixture** generated from them: per page, the pdf.js text items (string + end-of-line flag) and the real chunker's chunks. CC BY allows redistributing excerpts with attribution; the fixture folder's README gives it. A vitest then runs the Task 5 matcher over every chunk; CI runs it (`npm test`).

**Documents (licenses checked on arXiv on 2026-10-10, all `http://creativecommons.org/licenses/by/4.0/`):**

| id | arXiv | sha256 of the PDF |
|---|---|---|
| `react-2022` | `2210.03629v3` — ReAct: Synergizing Reasoning and Acting in Language Models (Yao et al.) | `f285b0971ae4a790e402fb93966bed3adde2cf0a04977d08b2b40d6ab0cace69` |
| `cot-2022` | `2201.11903v6` — Chain-of-Thought Prompting Elicits Reasoning in Large Language Models (Wei et al.) | `7d9f878c23b460e4566aa4ec9201b1abfb3b8faefb2b1356e411cb90fef72a12` |
| `reflexion-2023` | `2303.11366v4` — Reflexion: Language Agents with Verbal Reinforcement Learning (Shinn et al.) | `6059b6f89fea9959bd3dab553fbb97756a3dfb1b15e3cbab2fbf3ab6664333bd` |
| `self-rag-2023` | `2310.11511v1` — Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection (Asai et al.) | `d9eaa1398abac0df67a9d0933a5bf8b6d9d83d2e72da2a486073cd842dd52978` |

Download: `curl -sSL -o <dir>/<arxiv>.pdf https://arxiv.org/pdf/<arxiv>` into `data/seed_corpus/` (git-ignored; check `.gitignore` covers it, add `data/` if not) and verify each sha256 (`sha256sum`). Already downloaded copies may exist at `C:\Users\dtrun\.claude\jobs\21400686\tmp\seed\` — copy them instead of downloading again if present.

**Files:**
- Modify: `backend/evals/seed_corpus/manifest.yaml` (four entries)
- Create: `backend/evals/highlight_fixture.py` — chunks for each PDF with the worker's own extractor and chunker
- Create: `web/scripts/text-layer-fixture.mjs` — pdf.js text items for each PDF (Node, `pdfjs-dist/legacy/build/pdf.mjs`)
- Create: `web/src/features/viewer/fixtures/seed-text.json` (generated; first **6 pages** of each paper to keep it small) and `web/src/features/viewer/fixtures/README.md` (attribution, license, how to regenerate)
- Create: `web/src/features/viewer/passage.seed.test.ts`
- Modify: `backend/evals/README.md` and `backend/evals/seed_corpus/README.md` (one line each: the highlight fixture and its command)

**Interfaces:**
- Consumes: `findPassage` (Task 5); `PypdfExtractor`, `build_chunker`, `ChunkingConfig` (backend).
- Produces: fixture shape

```json
{
  "documents": [
    {
      "id": "react-2022",
      "pages": [ { "page": 1, "items": [["ReAct: Synergizing", false], ["Reasoning and Acting", true]] } ],
      "chunks": [ { "page": 1, "start_index": 0, "text": "…" } ]
    }
  ]
}
```

- [ ] **Step 1: Manifest.** Add the four entries following the schema comment in `manifest.yaml` (`source: {type: arxiv, ref: "2210.03629v3"}`, `license: "CC-BY-4.0"`, `sha256`, `subjects` — use `["LLM agents"]` for ReAct and Reflexion, `["Prompting"]` for CoT, `["Retrieval-augmented generation", "LLM agents"]` for Self-RAG; `metadata` with the exact title, authors (copy the author list from each arXiv abstract page), year (2022, 2022, 2023, 2023), no DOI; `work_key` = normalized title + year computed with `smart_tutor.knowledge.domain.description.work_key`-style normalization (read `description.py` and reuse its function in a one-off `uv run python -c`); `cites`: ReAct → `["cot-2022"]`, Reflexion → `["react-2022", "cot-2022"]`, others `[]` (only links you can confirm in the paper's references); `adversarial: false`).
- [ ] **Step 2: Chunk generator** `backend/evals/highlight_fixture.py`:

```python
"""Chunks of seed-corpus PDFs, as the worker makes them, for the viewer's highlight test (PRD §10.1).

Usage: uv run --extra ingest python -m evals.highlight_fixture --pages 6 --out chunks.json data/seed_corpus/*.pdf
Writes {"<file stem>": [{"page", "start_index", "text"}, ...]} for the first --pages pages of each PDF.
"""
```

It reads each file's bytes, `PypdfExtractor().extract_pages(data, max_pages=500)[:pages]`, wraps non-blank pages in LangChain `Document(page_content=text, metadata={"page": n})`, runs `build_chunker(ChunkingConfig())[0].transform_documents(...)`, and dumps page/start_index/text per chunk (`json.dump(..., ensure_ascii=False, indent=None)`).
- [ ] **Step 3: Text-layer generator** `web/scripts/text-layer-fixture.mjs`:

```js
// The pdf.js text items of seed-corpus PDFs plus the worker's chunks, for passage.seed.test.ts (see fixtures/README.md).
// Usage: node scripts/text-layer-fixture.mjs --chunks chunks.json --pages 6 --ids react-2022=2210.03629v3,... <pdf dir>
import { getDocument } from "pdfjs-dist/legacy/build/pdf.mjs";
```

For each id=stem pair: open `<dir>/<stem>.pdf` (`getDocument({ data: new Uint8Array(buf), useSystemFonts: true })`), for pages 1..N `page.getTextContent()` → `items.filter((i) => "str" in i).map((i) => [i.str, i.hasEOL])`; combine with that stem's chunks; write `src/features/viewer/fixtures/seed-text.json` (no indentation).
- [ ] **Step 4: Generate** the fixture (backend step → temp `chunks.json` in `$CLAUDE_JOB_DIR/tmp` or similar, then the Node step). Check its size (`du -h`); if over ~600 KB, lower `--pages` to 5. Write `fixtures/README.md`: the four papers with authors, arXiv links, "CC BY 4.0, excerpts of the papers' text", that the text is unmodified except for extraction, and the two regeneration commands.
- [ ] **Step 5: The test** `passage.seed.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import fixture from "./fixtures/seed-text.json";
import { findPassage } from "./passage";

type Doc = { id: string; pages: { page: number; items: [string, boolean][] }[]; chunks: { page: number; start_index: number | null; text: string }[] };

// PRD §10.1 "Citation highlight": ≥ 95% of seed-corpus chunks are found on their page by the viewer's matcher.
describe("the matcher on the seed corpus", () => {
  const docs = (fixture as { documents: Doc[] }).documents;
  const results = docs.flatMap((doc) =>
    doc.chunks.map((chunk) => {
      const page = doc.pages.find((p) => p.page === chunk.page)!;
      const items = page.items.map(([str, hasEOL]) => ({ str, hasEOL }));
      return { doc: doc.id, page: chunk.page, found: findPassage(items, chunk.text, chunk.start_index) !== null };
    }),
  );

  it("has chunks from every document", () => {
    expect(new Set(results.map((r) => r.doc)).size).toBe(docs.length);
    expect(results.length).toBeGreaterThan(100);
  });

  it("finds at least 95% of chunks on their page", () => {
    const rate = results.filter((r) => r.found).length / results.length;
    expect(rate).toBeGreaterThanOrEqual(0.95);
  });
});
```

(`resolveJsonModule` must be on in the web tsconfig used by vitest; if not, read the file with `fs.readFileSync(new URL("./fixtures/seed-text.json", import.meta.url))` + `JSON.parse`.)
- [ ] **Step 6:** Run `cd web && npx vitest run src/features/viewer/passage.seed.test.ts`. Print the rate (temporarily `console.log`) and the misses. If the rate is below 0.95, improve `passage.ts` (Task 5's file) for the failure classes you see — e.g. pypdf and pdf.js reading two columns in different orders (the head/tail fallback), different dash or quote characters (fold `‐‑‒–—` to `-` and `‘’“”` to `'"` in `matchKey`, on both sides), or ligature glyphs pdf.js leaves unmapped — adding a unit test to `passage.test.ts` for each fix. Never lower the threshold. Record the final rate in the fixture README.
- [ ] **Step 7:** `npx vitest run && npm run build` pass; backend `uv run ruff check . && uv run ruff format --check . && uv run mypy` pass (evals is linted).
- [ ] **Step 8: Commit** — "Check the highlight matcher on four seed-corpus papers".

---

### Task 7: The viewer draws the highlight

**Files:**
- Modify: `web/src/features/viewer/pdf.ts` (`PdfPage.textItems()`)
- Create: `web/src/api/chunks.ts` (`loadChunk`, `ChunkNotFoundError`, `recordHighlightMiss`) + `web/src/api/chunks.test.ts`
- Create: `web/src/features/viewer/useChunk.ts`
- Create: `web/src/features/viewer/PassageHighlight.tsx`
- Modify: `web/src/features/viewer/DocumentViewer.tsx`, `DocumentViewer.module.css`, `DocumentPane.tsx`, `ViewerDialog.tsx`, `testFakes.ts`
- Modify: `web/src/styles/tokens.css` (fixed highlight colors), `DESIGN.md` (one sentence in Split view about the highlight)
- Test: `web/src/features/viewer/DocumentViewer.test.tsx`, `DocumentPane.test.tsx`, `web/src/features/viewer/highlightContrast.test.ts`

**Interfaces:**
- Consumes: `TextItem`, `findPassage`, `passageBoxes`, `Box` (Task 5); generated `getChunk`, `recordHighlightMiss` SDK functions (Task 4 regeneration — check the exact generated names in `src/api/generated/sdk.gen.ts`).
- Produces:
  - `pdf.ts`: `PdfPage` gains `textItems(): Promise<TextItem[]>`:

    ```ts
    textItems: async () => {
      const content = await p.getTextContent();
      return content.items.flatMap((it) => {
        if (!("str" in it)) return [];
        const [, , c, d, e, f] = Util.transform(base.transform, it.transform);
        const height = Math.hypot(c, d);
        return [{ str: it.str, hasEOL: it.hasEOL, x: e, y: f - height, width: it.width * CSS_PER_PT, height }];
      });
    },
    ```

    (`Util` from `pdfjs-dist`; `base` is the scale-`CSS_PER_PT` viewport already in the file.)
  - `api/chunks.ts`: `export type ChunkPassage = { chunkId: string; documentId: string; page: number | null; startIndex: number | null; text: string }`; `loadChunk(chunkId, apiClient = client): Promise<ChunkPassage>` (401 → `SessionExpiredError` via `sessionOver`; 404 → `ChunkNotFoundError`; else `failure(error)`); `recordHighlightMiss(apiClient = client): void` — fire and forget, errors swallowed.
  - `export type Passage = { chunkId: string; page: number }` (in `DocumentViewer.tsx`, exported). A **new object per click**: the viewer treats each new object as "jump to this passage".
  - `DocumentViewer` props: `passage?: Passage`; deps `loadChunk?: (id: string) => Promise<ChunkPassage>`, `recordMiss?: () => void`. `ViewerDeps` (in `ViewerDialog.tsx`) adds `"loadChunk" | "recordMiss"`.
  - `DocumentPane` props: `passage?: Passage` (passed to the pane's viewer and to the "Open in dialog" overlay so it shows the same highlight). `ViewerDialog` props: `passage?: Passage`.
  - `fakePdf(numPages, items?)` in `testFakes.ts`: each page's `textItems` resolves to `items` (default `[]`); `fakeViewerDeps()` adds `loadChunk: vi.fn(async (id) => ({ chunkId: id, documentId: "d1", page: 2, startIndex: 0, text: "Cited text here." }))` and `recordMiss: vi.fn()`.

**Behavior (DocumentViewer):**
1. With a `passage`, the viewer starts at `passage.page` (it overrides `initialPage`), and each new `passage` object jumps to its page (like `jumpTo`) without remounting.
2. `useChunk(passage?.chunkId, loadChunk)` → `{ status: "idle" } | { status: "loading" } | { status: "ready"; chunk } | { status: "failed" }`, tagged by chunk id so a late reply for a previous passage is dropped (same pattern as `useDocumentFile`'s `Tagged`).
3. Once the PDF is ready, the current page equals the chunk's page, and the chunk is ready: `await (await doc.page(page)).textItems()`, then `findPassage(items, chunk.text, chunk.startIndex)` → `passageBoxes(...)` or `null`. Store as `{ chunkId, boxes: Box[] | null }`; ignore the result if the passage changed meanwhile. A failed chunk request resolves to `boxes: null` too. Zero boxes counts as `null`.
4. Drawing: `.page` becomes `position: relative`; `<PassageHighlight boxes scale={zoom / 100} text={chunk.text} />` renders an `aria-hidden` box layer — each box an absolutely positioned `<span>` with the fill; one 2px marker `<span>` left of the union of the boxes (top of the first to bottom of the last, 4px left of the leftmost x); the label `<span>` "Cited passage" just above the first box — plus, outside the hidden layer, a visually hidden `<p>`: "Cited passage begins. {chunk.text} Cited passage ends." (so screen readers get the passage, which the canvas doesn't expose). Show it only while the page shown is the chunk's page.
5. Scroll: the first time a passage's boxes are drawn, set the canvas area's `scrollTop` to `max(0, pageEl.offsetTop + firstBox.y * scale - canvasArea.clientHeight / 3)` (refs on `.canvasArea` and `.page`).
6. No match (`boxes: null` on the chunk's page): above the page, `<p className={styles.note} role="note">` with the lucide `Info` icon and "Couldn't highlight the passage on this page."; call `recordMiss()` **once per passage object**.
7. Status (the existing polite `<p className="visually-hidden" aria-live="polite">`): once the passage resolves, `Opened page ${page} of ${numPages}. Cited passage highlighted.` or `Opened page ${page} of ${numPages}. Couldn't highlight the passage on this page.`; after the learner changes page, back to `Page n of N`. Without a passage, unchanged.

**CSS** (`DocumentViewer.module.css`, tokens only): `.page { position: relative; }`; `.hlBox { position: absolute; background: var(--cite-fill); border-radius: 2px; pointer-events: none; }`; `.hlMarker { position: absolute; width: 2px; background: var(--cite-mark); border-radius: 1px; }`; `.hlLabel { position: absolute; transform: translateY(-100%); padding: 0 var(--sp-1); border-radius: var(--r-sm); background: var(--cite-mark); color: var(--cite-on-mark); font-size: var(--fs-12); font-weight: 600; line-height: 1.5; white-space: nowrap; }`; `.note` like the mockup's pill (`display: flex; align-items: center; gap: var(--sp-2); width: fit-content; margin: var(--sp-4) auto 0; padding: var(--sp-1) var(--sp-3); border: 1px solid var(--border); border-radius: var(--r-pill); background: var(--surface); color: var(--text); font-size: var(--fs-13);` and a 16px `--text-2` icon).

**Tokens** (`tokens.css`, in the light `:root` block only, with a comment "fixed: the PDF page stays white in both themes"): `--cite-fill: rgba(11, 107, 102, 0.16); --cite-mark: #0B6B66; --cite-on-mark: #FFFFFF;`. Check the dark-theme blocks don't redefine them. Add to `DESIGN.md` Split view: "A citation opens at its page with the passage highlighted: a soft accent fill over its lines, a 2px marker beside them, and a "Cited passage" label (fixed colors, since the page stays white); if the passage can't be found, the page opens with "Couldn't highlight the passage on this page.""

- [ ] **Step 1: Failing tests.**
  - `chunks.test.ts`: `loadChunk` maps the response to camelCase, 404 → `ChunkNotFoundError`, 401 → `SessionExpiredError`; `recordHighlightMiss` posts to `/viewer/highlight-misses` and never throws when the request fails (follow `documents.test.ts`'s fake-client style).
  - `highlightContrast.test.ts`: read `src/styles/tokens.css` (`fs`), parse `--cite-fill`, `--cite-mark`, `--cite-on-mark`; blend the fill over white; assert WCAG contrast of `#000000` and of `#595959` (dark-grey PDF text) over the blend ≥ 4.5, and `--cite-on-mark` on `--cite-mark` ≥ 4.5. Write the small `luminance`/`contrast` helpers in the test.
  - `DocumentViewer.test.tsx` (use `fakeViewerDeps()` and a `fakePdf` whose page 2 items contain the chunk text, e.g. `[{ str: "Cited text here.", hasEOL: true, x: 50, y: 300, width: 200, height: 12 }]`):
    - "a citation opens its page with the passage highlighted": render with `passage={{ chunkId: "c1", page: 2 }}` → readout "p. 2 / 3"; a highlight box is in the DOM (query by `data-testid="passage-box"`), the label "Cited passage" is present, the visually hidden text contains "Cited passage begins. Cited text here. Cited passage ends."; the status reads "Opened page 2 of 3. Cited passage highlighted."; `recordMiss` not called.
    - "no match shows the page with the note": items without the text → `getByRole("note")` has "Couldn't highlight the passage on this page."; status "Opened page 2 of 3. Couldn't highlight the passage on this page."; `recordMiss` called exactly once (rerender with the same passage object → still once).
    - "a failed chunk request shows the page without highlight": `loadChunk` rejects → page 2 shown, note shown, `recordMiss` once.
    - "a second chip of the same document moves the highlight": rerender with a new passage `{ chunkId: "c2", page: 3 }` (loadChunk returns page 3 for c2) → readout "p. 3 / 3", `loadPdfDoc` called once in total, the box from c1 is gone before/when c2's appears.
    - "a late chunk of a swapped-out passage is ignored": `loadChunk` for c1 is a deferred promise; rerender with c2 (resolves at once, no match → note); then resolve c1 with matching text → no highlight box appears.
    - "the highlight follows zoom": after the box appears, click "Zoom in" → the box's inline `width` grows by the zoom ratio (100 → 125 or whatever `ZOOM_STEPS` next is).
    - "the highlight shows only on its page": press PageDown → no box; status back to "Page 3 of 3"; PageUp → box again (no second `recordMiss`, no second scroll requirement).
    - "scrolls the passage to a third from the top": stub `clientHeight` on the canvas area (`Object.defineProperty(HTMLElement.prototype, "clientHeight", …)` scoped to the test, or set it on the element found via its class) and `offsetTop` of the page; assert `scrollTop === offsetTop + 300 * 1 - clientHeight / 3` (clamped at 0).
  - `DocumentPane.test.tsx`: the pane passes `passage` to the viewer (highlight shown); "Open in dialog" shows the same highlight in the dialog.
- [ ] **Step 2:** `cd web && npx vitest run src/features/viewer src/api/chunks.test.ts` → FAIL.
- [ ] **Step 3: Implement** per Behavior/CSS/Tokens above. Keep `DocumentViewer.tsx` readable: put the matching effect and its state in `usePassageHighlight(doc, page, chunk, passage)` inside `useChunk.ts` or a new `usePassageHighlight.ts` if the component grows past ~320 lines. Loaded lazily: `pdf.ts` stays the only file importing pdf.js.
- [ ] **Step 4:** Tests PASS; `npx vitest run && npm run build` pass.
- [ ] **Step 5: Commit** — "Highlight the cited passage in the document viewer".

---

### Task 8: Sources chips open the pane at the passage

**Files:**
- Modify: `web/src/features/chat/ChatPage.tsx`, `ChatPage.module.css`
- Test: `web/src/features/chat/ChatPage.test.tsx`

**Interfaces:**
- Consumes: `DocumentPane` `passage` prop and `Passage` type (Task 7); `ViewerDeps` with `loadChunk`/`recordMiss`.
- Produces: ChatPage's `Viewer` state becomes `{ documentId: string; chunkId?: string; passage?: Passage }`.

**Behavior:**
- Each non-deleted Sources chip is a `<button type="button">` (still inside its `<li>`), keeping today's content (`[n]` marker, title, "· p. 3" / "· page unavailable") and `title={formatCitation(c)}`, with `aria-label={`${c.document_title}, ${pageText}. ${shown ? "Shown beside the conversation" : "Open beside the conversation"}`}` where `pageText` is `p. ${c.page}` or `page unavailable`, `aria-current={shown ? "true" : undefined}`, and `data-chunk-id={c.chunk_id}`. Deleted chips stay non-interactive spans (unchanged).
- Click: `opener.current = button; setViewer({ documentId: c.document_id, chunkId: c.chunk_id, passage: c.page === null ? undefined : { chunkId: c.chunk_id, page: c.page } })` — a new object every click, so clicking the same chip again re-jumps to the passage. A chip of another document swaps the document in place (the pane already does this); a chip of the same document moves the highlight without reloading.
- `shown` = `viewer?.chunkId === c.chunk_id`. A panel row click (`openDocument`) clears `chunkId`, so no chip stays highlighted.
- Close (Esc or Close) returns focus to the chip: the existing focus-restore effect already prefers `opener.current` when it is still connected; update its comment ("openers outside the panel (Sources chips, a later ticket)" → chips stay mounted, so they take focus back directly).
- Pass `passage={viewer.passage}` to `DocumentPane`.
- CSS: reset button styles on `.source` (font, background `var(--surface)`, `cursor: pointer`, `:hover { border-color: var(--accent) }`, `:focus-visible` outline per DESIGN), a 24px hit area (`position: relative` + `::before { content: ""; position: absolute; inset: -1px 0; }`), and `.sourceShown { background: var(--accent-soft); border-color: var(--accent); box-shadow: inset 0 0 0 1px var(--accent); }` with `.sourceShown .sourceTitle, .sourceShown .sourcePage { color: var(--accent-text); }` (wrap the page text in a `.sourcePage` span). Keep `.sourceDeleted` as is.

- [ ] **Step 1: Failing tests** in `ChatPage.test.tsx` (reuse the file's helpers for streaming an answer with citations and its `viewerDeps` fakes; give two citations of "d1" (chunks c1 p. 2, c2 p. 3) and one of "d2" (c3 p. 1)):
  - "a Sources chip opens the document beside the conversation at its page": click the chip named /ReAct, p. 2. Open beside the conversation/ → the pane region (named by the title) appears, readout "p. 2 / 3", `loadChunk` called with "c1"; the chip's accessible name now ends "Shown beside the conversation" and it has `aria-current="true"`.
  - "another chip swaps the document in place": click the d2 chip → pane title "PPO", the d1 chip loses `aria-current`, the d2 chip has it.
  - "a second chip of the same document keeps the PDF loaded": click c1 then c2 → readout "p. 3 / 3", `loadPdfDoc` called once.
  - "closing returns focus to the chip": open from a chip, press Escape → the chip has focus; open again, click Close → the chip has focus.
  - "a deleted document's chip is not a button": with `used` marking d2 deleted → no button named /PPO/; the "Deleted document" text is present.
  - "a citation without a page opens the document at page 1": citation with `page: null` → readout "p. 1 / 3", `loadChunk` not called.
  - "a panel row clears the chip highlight": open from a chip, then click the panel row of d1 → no chip has `aria-current`.
- [ ] **Step 2:** `cd web && npx vitest run src/features/chat/ChatPage.test.tsx` → FAIL.
- [ ] **Step 3: Implement** per Behavior.
- [ ] **Step 4:** `npx vitest run && npm run build` pass. Render the mockups (`npm run design:shots -- --states "viewer-citation-highlight,viewer-no-highlight,chat-answer-citations" --round v0.10 --theme both`) and compare against the running app if Compose is available; otherwise compare the CSS against the mockup PNGs in `.design-shots/v0.10/`. Note any intentional difference for the PR description.
- [ ] **Step 5: Commit** — "Open the cited passage beside the conversation from a Sources chip".

---

## Final checks (after Task 8)

- Backend: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`
- Migrations apply on a fresh DB if Compose is up: `uv run --env-file ../.env python -m smart_tutor.apps.jobs.migrate`
- Web: `cd web && npm ci && npx vitest run && npm run build`; the generated client is current (re-run the generator, `git diff --exit-code web/src/api`).
- PR description: what changed, the seed-corpus match rate, the mockup comparison, and "Closes #124".

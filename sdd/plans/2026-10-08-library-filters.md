# Library authors, year, and filters — Implementation Plan (#107)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The Library lists each document's authors and year, and the learner narrows it by subject (any of), upload date range (GMT+7), and state, combined; filtering runs in the API in one query with `can_read` in SQL.

**Spec:** PRD §8 US-10, D24, D27, §9.4. Ticket #107. Design round v0.7: `library-default`, `library-filtered-by-subject`, `library-no-results`.

**Architecture:** A `DocumentFilter` value object in `knowledge.domain` with `Document.matches()` as the domain twin of the SQL `WHERE`. `DocumentRepository.list_readable_by(user_id, filter)` applies it in SQL (subject `EXISTS`, `state IN`, `created_at` range) and in the in-memory fake. `DocumentService.list_documents` turns calendar dates into a half-open instant range in the app time zone. `GET /documents` takes repeatable `subject_id` and `state`, and `uploaded_from` / `uploaded_to` dates. The time zone comes from the new SSM parameter `/smart-tutor/app-time-zone` (D27), read once at API startup.

**Tech stack:** FastAPI, SQLAlchemy Core, pytest; React + TypeScript, Vitest + Testing Library.

## Decisions

- **Date range:** `uploaded_from` and `uploaded_to` are calendar dates (`YYYY-MM-DD`), both inclusive, in the app time zone: `created_at >= from 00:00` and `created_at < (to + 1 day) 00:00`. A `from` after `to` matches nothing (no error, so the polling list never shows "Can't load").
- **Subjects:** `subject_id` repeats; a document matches when it has **any** of them. Up to 100 values. Names resolve at read time as before.
- **State:** `state` repeats (`processing`, `awaiting_subjects`, `ready`, `failed`); the UI sends one.
- **Authors and year** come from the shared content (`contents.authors`, `contents.year`); `authors` is `[]` and `year` is `null` when missing.
- **Time zone:** SSM `/smart-tutor/app-time-zone` = `Asia/Ho_Chi_Minh` (ConfigStack, LocalStack init). `DocumentService(…, time_zone=…)` defaults to `ZoneInfo("Asia/Ho_Chi_Minh")` for tests. Add `tzdata` as a direct dependency (Windows and slim images have no zone database).
- **Web:** single-select Subject and State, From/To date inputs, "N documents", Clear filters (shown while any filter is set). Subject options come from `GET /me/subjects` (every document with subjects is ready, so this covers the list). Byline: one author → full name; two → "Last and Last"; three or more → "Last et al."; then " · year". No byline when both are missing.
- **Out of scope** (later tickets): Active/Archived tabs, the "needs subjects" banner, Open and row menus, subject chips.

---

### Task 1: Filtered listing in `knowledge` (domain, port, SQL, fake, service)

**Files:**
- Modify: `backend/src/smart_tutor/knowledge/domain/document.py` (add `DocumentFilter`, `content_authors`, `content_year`, `Document.matches`)
- Modify: `backend/src/smart_tutor/knowledge/ports/library.py` (`list_readable_by(user_id, document_filter=DocumentFilter())`)
- Modify: `backend/src/smart_tutor/knowledge/adapters/sql_library.py` (`_document` reads authors/year; listing selects them and applies the filter)
- Modify: `backend/tests/fakes/knowledge.py` (fake applies `Document.matches`, fills authors/year)
- Modify: `backend/src/smart_tutor/knowledge/application/document_service.py` (`DocumentView.authors`, `.year`; `list_documents(user_id, *, subject_ids=(), states=(), uploaded_from=None, uploaded_to=None)`; `time_zone` constructor arg)
- Modify: `backend/src/smart_tutor/knowledge/application/__init__.py` (export `DocumentStateName` if needed)
- Modify: `backend/src/smart_tutor/knowledge/README.md` (one sentence on filtering)
- Tests: `backend/tests/unit/knowledge/test_domain.py`, `test_document_service.py`, `backend/tests/integration/knowledge/test_sql_library.py`

- [ ] **Step 1 (test first):** domain tests for `Document.matches` — empty filter matches everything; any-of subjects; states; `uploaded_from` inclusive; `uploaded_before` exclusive; combination.
- [ ] **Step 2:** implement `DocumentFilter` (frozen dataclass: `subject_ids: frozenset[SubjectId]`, `states: frozenset[DocumentState]`, `uploaded_from: datetime | None`, `uploaded_before: datetime | None`; empty set = no constraint) and `Document.matches`. Run the tests.
- [ ] **Step 3 (test first):** service tests with the fake library — authors/year in `DocumentView` (from a described content, and `[]`/`None` for one still uploading); each filter; the combination; dates in GMT+7 (a document created at `2026-10-01T17:30Z` is on 2 Oct in GMT+7, so `uploaded_to=2026-10-01` excludes it and `uploaded_from=2026-10-02` includes it); another learner's documents never appear under any filter.
- [ ] **Step 4:** implement port signature, fake, and service. Run unit tests.
- [ ] **Step 5 (test first):** SQL integration tests (`@pytest.mark.integration`, Compose Postgres on 10400) mirroring the filter cases, including one combining all three, and authors/year returned.
- [ ] **Step 6:** implement in `sql_library.py`: select `contents.c.authors`, `contents.c.year` with the existing labels pattern; `where` adds `exists(document_subjects where subject_id in …)`, `state in …`, `created_at >= …`, `created_at < …` only when set. Keep `readable_by(user_id)` and `archived is false`. Run `uv run pytest -m integration tests/integration/knowledge`.
- [ ] **Step 7:** `ruff check`, `ruff format`, `mypy`, `lint-imports`, `pytest`; commit "List documents with authors and year, filtered in one query".

### Task 2: `GET /documents` filters, authors, year; the app time zone

**Files:**
- Modify: `backend/src/smart_tutor/apps/api/routes/knowledge.py` (query params, `authors`, `year` in `DocumentResponse`)
- Modify: `backend/src/smart_tutor/shared/config.py` (`app_time_zone_param = "/smart-tutor/app-time-zone"`)
- Modify: `backend/src/smart_tutor/apps/api/services.py` (`ZoneInfo(params.get(...))` → `DocumentService`)
- Modify: `backend/pyproject.toml`, `backend/uv.lock` (`tzdata`)
- Modify: `infra/smart_tutor_infra/stacks/config.py`, `infra/tests/test_config_stack.py`, `local/localstack/init/ready.d/10-smart-tutor.sh`
- Modify: `web/src/api/openapi.json`, `web/src/api/generated/*` (`make api-client`)
- Modify: `sdd/prd.md` (v2.21: D27 also covers the Library's upload date range; US-10 API note)
- Tests: `backend/tests/unit/apps/api/test_knowledge_routes.py`, `backend/tests/isolation/test_documents.py`

- [ ] **Step 1 (test first):** route tests — authors/year in the response; each filter via query string; combination; repeated `subject_id`; malformed `subject_id`, unknown `state`, or bad date → 422.
- [ ] **Step 2:** route params: `subject_id: Annotated[list[UUID], Query(max_length=100)] = []`, `state: Annotated[list[Literal[...]], Query()] = []`, `uploaded_from: date | None`, `uploaded_to: date | None`. Pass through to the service.
- [ ] **Step 3 (test first):** isolation test — learner B filtering by learner A's subject id, A's state, and a date range covering A's uploads gets `[]`; A's own filtered list holds only A's documents.
- [ ] **Step 4:** settings, wiring, `tzdata`, infra parameter + test, LocalStack init line. Startup fails if the zone name is invalid (`ZoneInfo` raises).
- [ ] **Step 5:** `make api-client` (or its one-line commands); PRD bump.
- [ ] **Step 6:** backend checks, `cd infra && uv run pytest`; commit "Filter GET /documents by subject, upload dates, and state".

### Task 3: Library filter bar, byline, no-results state (web)

**Files:**
- Modify: `web/src/api/documents.ts` (`loadDocuments(filters?)`, `DocumentFilters` type)
- Create: `web/src/features/library/LibraryFilters.tsx`, `LibraryFilters.module.css`, `LibraryFilters.test.tsx`
- Modify: `web/src/features/library/LibraryPage.tsx`, `useDocuments.ts` (+ tests), `DocumentTable.tsx` (+ byline), `DocumentTable.module.css`
- Modify: `web/src/features/library/LibraryPage.test.tsx`

- [ ] **Step 1 (test first):** `byline(authors, year)` cases; DocumentTable shows "Schick et al. · 2023" under the title.
- [ ] **Step 2:** `LibraryFilters` (`role="search"`, `aria-label="Filter documents"`): Subject select ("All subjects" + options), From and To `type="date"` with `max`/`min` tied to each other, State select ("All states", Processing, Choose subjects, Ready, Failed), live count "N documents" / "1 document", Clear filters (ghost button with X) only when a filter is set. Use design tokens (DESIGN.md) and `components/Button`.
- [ ] **Step 3 (test first):** LibraryPage tests — choosing a subject calls `load` with `{ subject_ids: [id] }`; date and state go through; zero results with a filter set shows "No documents match these filters" (EmptyState, `Filter` icon, text "Try another subject, state or a wider date range.") and Clear filters reloads with no filters and restores the list; an empty library with no filters still shows the upload empty state; the Upload header button stays while filtered to zero.
- [ ] **Step 4:** `useDocuments(load, pollMs, filters)` reloads immediately when filters change and polls with the current filters; responses for old filters are dropped. `loadDocuments` maps filters to the query (`subject_id`, `state`, `uploaded_from`, `uploaded_to`).
- [ ] **Step 5:** `npm run build`, `npx vitest run`; render the three states and compare with `.design-shots/v0.7/`; commit "Library filter bar with authors and year".

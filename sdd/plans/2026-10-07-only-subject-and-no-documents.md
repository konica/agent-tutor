# Thread starts with the only subject; no ready documents asks for an upload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ticket #83 (story #11, PRD §8 US-3 criteria 1 and 4): the chat knows the learner's subjects before the first question, shows "Your subjects", shows "Upload a document first" when there are no ready documents, a quiet hint while documents are processing, and the thread's subjects as chips in the header.

**Architecture:** The backend already starts a one-subject thread without detection and refuses with 409 "Upload a document first" (`ConversationService.start_thread`, #82). This slice adds one read endpoint, `GET /me/subjects`, which composes `DocumentService.learner_subjects` (knowledge) with `SubjectNames.names_for` (subjects) in the route, as `POST /threads` already does. The web chat loads it with `GET /documents` (for the processing count) on mount and renders the v0.7 states.

**Tech Stack:** FastAPI, pytest + fakes in `backend/tests/fakes/`; React + TypeScript + Vite, Vitest + Testing Library; generated API client (`make api-client`).

**Spec:** GitHub issue #83; PRD `sdd/prd.md` §8 US-3, §4 "My subjects", §9.4; mockups round v0.7 (`design-v0.7`), states `chat-new`, `chat-new-conversation`, `chat-no-documents`, `chat-documents-processing`, `chat-subjects-detected`. Story #11 points at v0.7, which supersedes the ticket's v0.4 reference.

## Global Constraints

- "My subjects" = distinct subjects of the learner's ready, non-archived documents (`DocumentService.learner_subjects`). Names only through `SubjectNames.names_for` (personal name, else canonical — personal names arrive with US-10b behind that method).
- No user id in requests; the owner comes from the token.
- Copy, exactly: header title "New conversation", description "Subjects appear after your first question."; heading "Ask about your documents"; intro "I work out which of your subjects a question is about, answer only from your documents, and show the page each answer came from."; label "Your subjects:"; empty state title "Upload a document first", text "The tutor answers only from your documents. Add a PDF to your Library and you can start asking in a few minutes.", action "Upload" → `/library`; hint "1 document is still processing and can't be used yet." / "N documents are still processing and can't be used yet."
- D10: no "Try asking" example questions. No subject picker. Out of scope: Show-citations toggle, token counter, Summarize lesson, archive.
- UI uses `web/src/components/` (`PageHeader`, `EmptyState`, `SubjectChip`, `Button`) and design tokens (`DESIGN.md`); never paste prototype HTML/CSS.
- API calls only through `web/src/api/`; after the route change run `make api-client` (or its one-line command) so `web/src/api/openapi.json` and `generated/` are current.

## Review Focus

- A learner whose only documents are `awaiting_subjects` or `failed` has no subjects → no-documents state (not the hint). Pinned in Task 1 (API returns `[]`) and Task 2 (empty state).
- The ask returns 409 "Upload a document first" although the page loaded with subjects (last document archived meanwhile) → switch to the no-documents empty state. Pinned in Task 2.
- Loading `GET /me/subjects` fails (network) → a message, not a blank page or a false "Upload" prompt. Pinned in Task 2.
- Subject with no resolvable name → listed as "Unnamed subject", never dropped or blank. Pinned in Task 1.
- Hint pluralization (1 vs N) and the hint stays visible after a thread starts. Pinned in Task 2.

---

### Task 1: `GET /me/subjects` (backend)

**Files:**
- Create: `backend/src/smart_tutor/apps/api/routes/subjects.py`
- Modify: `backend/src/smart_tutor/apps/api/main.py` (include the router with `include_protected`)
- Modify: `backend/tests/fakes/ingest.py` (`ingest_ready` gets `subject_ids` keyword, default `[GENERAL_SUBJECT_ID]`)
- Modify: `web/src/api/openapi.json`, `web/src/api/generated/*` (regenerated)
- Test: `backend/tests/unit/apps/api/test_subject_routes.py`, `backend/tests/isolation/test_subjects.py`

**Interfaces:**
- Produces: `GET /me/subjects`, `operation_id="list_my_subjects"`, tag `subjects`, response `list[SubjectResponse]` (`{subject_id: str, name: str}`, reuse `SubjectResponse` from `routes/knowledge.py`), sorted by `name.casefold()` then `subject_id`. Generated TS function `listMySubjects`, type `SubjectResponse`.
- `ingest_ready(library, owner, text, subject_ids: Sequence[SubjectId] = (GENERAL_SUBJECT_ID,)) -> DocumentId`

- [ ] **Step 1: Failing route tests** (`test_subject_routes.py`, setup like `test_thread_routes.py`):

```python
def test_lists_the_subjects_of_ready_documents_by_name() -> None:
    catalog = InMemorySubjects({GENERAL_SUBJECT_ID: "General", RL: "Reinforcement Learning", AG: "AI Agents"})
    library = InMemoryLibrary()
    ingest_ready(library, "ada", "Policies act.", subject_ids=[RL, AG])
    ingest_ready(library, "ada", "Agents plan.", subject_ids=[AG])
    client = make_client(library, catalog)
    assert client.get("/me/subjects", headers=AUTH).json() == [
        {"subject_id": AG, "name": "AI Agents"}, {"subject_id": RL, "name": "Reinforcement Learning"}]

def test_no_ready_documents_is_an_empty_list() -> None:  # e.g. only an upload still processing
    library = InMemoryLibrary()
    UploadService(library.unit_of_work, FakeObjectStore(), FixedClock(), TEST_LIMITS).start_upload(UserId("ada"), "a.pdf")
    assert make_client(library).get("/me/subjects", headers=AUTH).json() == []

def test_a_subject_without_a_name_shows_a_placeholder() -> None:
    ingest_ready(library, "ada", "x", subject_ids=[UNKNOWN])  # catalog lacks UNKNOWN
    assert ...json() == [{"subject_id": UNKNOWN, "name": "Unnamed subject"}]

def test_requires_a_token() -> None:
    assert make_client(InMemoryLibrary()).get("/me/subjects").status_code == 401
```

- [ ] **Step 2: Failing isolation test** (`tests/isolation/test_subjects.py`): learners A and B, A's ready document in subject `SA`, B's in `SB` (and both may share General in a second document — shared subject must still appear for each only through their own documents). Assert A's list is exactly `[SA...]` and never contains `SB`, and vice versa; a learner with no documents gets `[]` even though others have subjects.
- [ ] **Step 3:** Run `cd backend && uv run pytest tests/unit/apps/api/test_subject_routes.py tests/isolation/test_subjects.py` → FAIL (404 / missing kwarg).
- [ ] **Step 4: Implement.** `ingest_ready` kwarg. Route:

```python
"""Subject routes: my subjects, the subjects of the learner's ready documents (PRD §4, §8 US-3)."""

UNNAMED_SUBJECT = "Unnamed subject"

@router.get("/me/subjects", operation_id="list_my_subjects")
async def list_my_subjects(principal: CurrentPrincipal, documents: Documents, subjects: Subjects) -> list[SubjectResponse]:
    mine = await run_in_threadpool(documents.learner_subjects, principal.user_id)
    names = await run_in_threadpool(subjects.names_for, principal.user_id, mine)
    listed = [SubjectResponse(subject_id=s, name=names.get(s) or UNNAMED_SUBJECT) for s in mine]
    return sorted(listed, key=lambda r: (r.name.casefold(), r.subject_id))
```

Have `routes/threads.py` import `UNNAMED_SUBJECT` from the new module instead of defining its own (one placeholder). Include the router in `main.py` after `knowledge`.
- [ ] **Step 5:** Regenerate the client: `cd backend && uv run python -m smart_tutor.apps.api.openapi_export ../web/src/api/openapi.json && cd ../web && npm --prefix tools/api-gen ci && npm run api:generate`.
- [ ] **Step 6:** Full backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest` → all pass.
- [ ] **Step 7:** Commit "List the learner's subjects for the chat (GET /me/subjects)".

### Task 2: Chat states (web)

**Files:**
- Create: `web/src/api/subjects.ts`, `web/src/api/subjects.test.ts`
- Modify: `web/src/features/chat/ChatPage.tsx`, `ChatPage.module.css`, `ChatPage.test.tsx`
- Possibly modify: `web/src/components/PageHeader/PageHeader.tsx` (optional `below?: ReactNode` slot for header chips, rendered under the description)

**Interfaces:**
- Consumes: generated `listMySubjects`, `SubjectResponse`; existing `loadDocuments()` from `api/documents.ts`.
- Produces: `loadMySubjects(apiClient?: Client): Promise<SubjectResponse[]>` (throws `SessionExpiredError` on 401/expired, `Error` otherwise — same pattern as `loadMe`). `ChatPage` props: `{ ask?, loadSubjects?: () => Promise<{subject_id: string; name: string}[]>, loadDocs?: () => Promise<DocumentResponse[]> }`, defaults the real loaders.

Behavior:
1. On mount load both in parallel. While loading: render the header only (no input flash of the empty state).
2. Subjects `[]` → replace the whole chat (header too) with `EmptyState` icon `Upload`, title/text from Global Constraints, action: a `Link` to `/library` styled as primary button with the Upload icon, label "Upload" (if `Button` can't render as a link, use `Link` with the button classes or add an `as`/`to` prop to `Button` — keep it minimal).
3. Otherwise, before any question: `PageHeader` title "New conversation", description "Subjects appear after your first question."; body: heading "Ask about your documents", intro, "Your subjects:" + `SubjectChip size="sm"` per subject (`hueKey=subject_id`), as a list with `aria-label="Your subjects"`.
4. After the `thread` event: header title = the question, chips of `event.subjects` under the title (`aria-label="Subjects"`), description gone; welcome block gone; existing exchange rendering (answer, citations) stays.
5. Processing hint: count of documents with `state === "processing"`; when > 0 show above the form, `Clock` icon (lucide) + text, muted small text (tokens from `DESIGN.md`). Shown in both new and active states.
6. Ask → `NoDocumentsError` → switch to the empty state (step 2). Subjects load failure (non-session) → `<p className={styles.problem}>` "Your subjects couldn't be loaded. Reload the page to try again." and no input. `SessionExpiredError` → nothing (session screen takes over).
7. Remove the old inline "Go to Library" no-documents problem paragraph.

- [ ] **Step 1: Failing tests** in `ChatPage.test.tsx` (render inside `MemoryRouter` as existing tests do; inject `loadSubjects`/`loadDocs`): (a) shows "New conversation", "Your subjects" list with names, no "Try asking"; (b) `[]` subjects → heading "Upload a document first" and link "Upload" with `href="/library"`, no textbox; (c) two processing docs → "2 documents are still processing and can't be used yet."; one → "1 document is still processing…"; ready-only → no hint; (d) after asking, header `h1` is the question and the "Subjects" list holds the thread's chip, hint still present; (e) ask throws `NoDocumentsError` → empty state; (f) `loadSubjects` rejects with `Error` → load-failure message, no textbox. Update existing tests to pass loaders. `subjects.test.ts`: 200 → data; 401 → `SessionExpiredError`; 500 → `Error` (mirror `me.test.ts`).
- [ ] **Step 2:** `cd web && npx vitest run src/features/chat src/api/subjects.test.ts` → FAIL.
- [ ] **Step 3:** Implement per Behavior; CSS only with tokens.
- [ ] **Step 4:** `cd web && npm run build && npx vitest run` → pass (and `npm run lint` if defined).
- [ ] **Step 5:** Compare with `.design-shots/v0.7/chat-*.png` (both themes) by running the app or a component render; adjust spacing/typography with tokens.
- [ ] **Step 6:** Commit "Show my subjects, the upload prompt, and the processing hint in the chat".

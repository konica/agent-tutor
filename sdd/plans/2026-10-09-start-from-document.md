# Start a Conversation from a Document Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The learner starts a new conversation from one of their ready documents ("Chat" on a Library row); the new conversation already lists that document (issue #132, PRD v2.22+ §8 US-4c, Q61).

**Architecture:** `POST /threads` accepts an optional `document_id`. The route checks it (the caller's ready, non-archived document, through `DocumentService.documents_by_id`, i.e. `can_read`) before it calls the agent, so a refused id is a plain `404` and no stream starts. `ConversationService.start_thread` then adds it to the new thread's list as `added_by = learner` (via `ThreadRepository.add_documents`), before the answer records its documents, so an answer that uses it only marks it used. On the web, "Chat" navigates to `/chat?document=<id>`; the chat page lists that document in the panel as "Added" before any thread exists, shows a "Started from …" notice, focuses the composer, and sends `document_id` with the first question.

**Tech Stack:** FastAPI, pydantic, pytest; React + TypeScript + Vite, react-router, Vitest + Testing Library, generated hey-api client.

**Spec:** Issue #132 (body is the spec), PRD `sdd/prd.md` §8 US-4c, prototype at tag `design-v0.10`: `js/documents.js` line ~209 (row "Chat" button) and ~550 (`ask-about`), `js/chat.js` ~257 (`from-doc` notice), `js/states.js` `chat-new-from-document`.

## Global Constraints

- Out of scope (record in the PR): "Ask about this" in document details (#109 open, no details screen yet) and in the document viewer (#118 open, no viewer yet); the row title opening the viewer (no viewer yet); the "Only search these documents" switch and `search_scope` (#131 open; no `search_scope` exists yet, so the thread is library-wide by construction).
- Release 1 `can_read`: owner only. A `document_id` that isn't the caller's, isn't `ready`, or is archived → `404` with detail `"Document not found"`, checked **before** the agent is called and before any thread starts; the response never contains the document's title.
- `document_id` is optional (`uuid.UUID | None = None`) on `AskRequest` (`extra="forbid"` stays). Without it, behavior is unchanged.
- Ordering: the starting document's row is added when the thread starts (`added_at = now`), so it sorts first; the answer's `record_answer` afterwards only sets its `first_used_at` if the answer used it.
- Web route: `/chat?document=<document_id>`. The chat page reads the param with `useSearchParams`. If the id isn't among the loaded documents as `state === "ready" && !archived`, the page ignores it (plain new conversation).
- Starting document applies to the **first question of the page** only (chat is single-turn, #82: a later question starts a new thread and the panel starts over).
- Before the first question the panel lists the starting document as a synthesized row `{document_id, title, authors, year, archived: false, deleted: false, added_by: "learner", used: false}` (so it shows the "Added" badge) and the panel is open (call the panel-open setter if it's closed). Its × remove button works before the thread exists: it drops the starting document (no request), and the notice disappears.
- Composer is focused on load when a starting document is shown.
- Notice copy (above the welcome, only while a starting document is pending, before the first question), verbatim: `Started from <em>{title}</em>. It's listed in Documents; answers still use all your documents.` (the prototype's switch clause is dropped until #131).
- Library: every row with `state === "ready" && !archived` (and not uploading) gets an always-visible secondary small button with a `MessageSquare` icon (lucide), text `Chat`, `aria-label="Chat about {title}"`, that navigates to `/chat?document={id}`. No other row gets it. "More" keeps its current items.
- Web visual rules: `DESIGN.md` (compact density), tokens only; reuse `web/src/components/` (`Button`, notice styles already in `ChatPage.module.css` if any; else add a small token-based class). Never paste prototype HTML/CSS.
- Backend checks: `cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && PYTHONUTF8=1 uv run lint-imports && uv run pytest`. Web: `cd web && npx vitest run && npm run build`.
- After changing the API: regenerate `web/src/api/` with the Makefile's `api-client` target command (run the one-line command directly if `make` is missing). CI fails when stale.
- Commits: imperative subject, body says why, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. Another learner's document id → `404`, nothing streamed, agent never called, no thread created, title not leaked. → Task 1 isolation test.
2. Archived or processing own document → `404` before the agent call. → Task 1 isolation test.
3. The answer uses the starting document: the list has one row, `added_by = "learner"`, `used = true` (no duplicate). → Task 1 route test.
4. The learner asks a second question: the second `ask` gets no document id and the panel starts over. → Task 3 test.
5. `?document=` names an unknown/archived id: no notice, no panel row, the first ask sends no document id. → Task 3 test.

---

### Task 1: `POST /threads` accepts a starting document

**Files:**
- Modify: `backend/src/smart_tutor/tutoring/application/conversation_service.py`
- Modify: `backend/src/smart_tutor/apps/api/routes/threads.py`
- Test: `backend/tests/unit/tutoring/` (the existing ConversationService test file — find it with `grep -rl "start_thread" backend/tests/unit`), `backend/tests/unit/apps/api/test_thread_routes.py`, `backend/tests/isolation/test_threads.py`

**Interfaces:**
- Produces:
  - `ConversationService.require_readable(user_id: UserId, document_id: DocumentId) -> None` — raises `DocumentNotAvailableError("Document not found")` unless the document is the caller's (`documents_by_id`), `state == "ready"`, and not archived.
  - `ConversationService.start_thread(user_id, question: str | None = None, document_id: DocumentId | None = None) -> Thread` — when `document_id` is given: `require_readable` first, then after `self._threads.add(thread)` call `self._threads.add_documents(thread.thread_id, [document_id], now)` with the same `now` the thread was started with.
  - `AskRequest.document_id: uuid.UUID | None = None`; OpenAPI declares `404` on `ask_in_new_thread` ("A document that isn't the caller's ready one.").

- [ ] **Step 1: Write failing service tests** (in the existing ConversationService unit test file, same fakes and style):
  - starting with the caller's ready document lists it: `documents_used(thread, user)` → one row, `added_by == "learner"`, `used is False`;
  - then `record_answer(thread, user, [doc, other])` → rows `[doc (learner, used True), other (answer, used True)]`;
  - another learner's document, an archived one, and a processing one each raise `DocumentNotAvailableError` and **no thread is added** (`threads.threads` unchanged).
- [ ] **Step 2: Run** `cd backend && uv run pytest <that file> -v` — Expected: FAIL (`unexpected keyword argument 'document_id'`).
- [ ] **Step 3: Implement** in `conversation_service.py`:

```python
    def require_readable(self, user_id: UserId, document_id: DocumentId) -> None:
        """The document is the learner's ready, non-archived one (`can_read`), else "Document not found"."""
        view = self._documents.documents_by_id(user_id, [document_id]).get(document_id)
        if view is None or view.state != "ready" or view.archived:
            raise DocumentNotAvailableError("Document not found")

    def start_thread(
        self, user_id: UserId, question: str | None = None, document_id: DocumentId | None = None
    ) -> Thread:
        """A new thread owned by the learner, persisted; its title starts as the first question. Started from a
        document (US-4c), it lists that document as added by the learner; answers still search all documents."""
        self.require_documents(user_id)
        if document_id is not None:
            self.require_readable(user_id, document_id)
        now = self._clock.now()
        thread = Thread.start(ThreadId(str(uuid.uuid4())), user_id, now, title=question)
        self._threads.add(thread)
        if document_id is not None:
            self._threads.add_documents(ThreadId(thread.thread_id), [document_id], now)
        return thread
```

  and reuse `require_readable` inside `add_documents` only if it stays all-or-nothing (it may keep its own loop; don't change its behavior).
- [ ] **Step 4: Run** the service tests — Expected: PASS.
- [ ] **Step 5: Write failing route + isolation tests.**
  - `test_thread_routes.py` (use its `setup`/`recording`/`sources`/`ask_with` helpers): (a) `POST /threads` with `{"question": "q", "document_id": <ready doc>}` whose answer's `sources` names that document → `GET /threads/{id}/documents` returns one row, `added_by == "learner"`, `used is True`; (b) an answer that names no sources still lists it with `used is False`; (c) `document_id` that's not a UUID → `422`; (d) the OpenAPI schema of `ask_in_new_thread` has the `document_id` property and a `404` response.
  - `tests/isolation/test_threads.py`: `test_a_learner_starts_a_thread_only_from_their_own_ready_document` — with A and B each owning a ready document, A archived and processing documents (copy the setup used in `test_a_learner_can_add_only_their_own_ready_active_documents`, including `UploadService(...).start_upload` for processing): A posting with B's id → `404`, body contains neither B's title nor id, **no thread created**, agent never called (use the `recording` style: a list of seen requests stays empty — if the isolation file has no such helper, wrap `answers` to append to a list); archived → `404`; processing → `404`; A's own ready → `200` and the thread lists it. Update the module docstring to mention starting from a document.
- [ ] **Step 6: Run** those tests — Expected: FAIL.
- [ ] **Step 7: Implement** in `routes/threads.py`: add `document_id: uuid.UUID | None = None` to `AskRequest` (comment: "Started from a document (US-4c): listed in the new thread; answers still search all documents."); add `404: {"description": "A document that isn't the caller's ready one."}` to `SSE_RESPONSE`; in `ask_in_new_thread`, after `require_documents`, if `body.document_id` is set:

```python
    document_id = DocumentId(str(body.document_id)) if body.document_id else None
    if document_id is not None:
        try:
            await run_in_threadpool(conversations.require_readable, principal.user_id, document_id)
        except DocumentNotAvailableError as e:
            raise HTTPException(404, str(e)) from None
```

  and in `start()` call `conversations.start_thread(principal.user_id, body.question, document_id)`; also catch `DocumentNotAvailableError` there next to `NoDocumentsError` (archived between check and start: log a warning, return `None`). Update the module docstring's first sentence to mention the optional starting document.
- [ ] **Step 8: Run** the full backend checks (Global Constraints) — Expected: all pass.
- [ ] **Step 9: Commit** — subject `Start a conversation from one of the learner's documents`.

### Task 2: Regenerate the API client and send the starting document

**Files:**
- Modify (generated): `web/src/api/openapi.json`, `web/src/api/generated/*`
- Modify: `web/src/api/chat.ts`, Test: `web/src/api/chat.test.ts`

**Interfaces:**
- Consumes: Task 1's `AskRequest.document_id`.
- Produces: `askInNewThread(question: string, documentId?: string, apiClient: Client = client): AsyncGenerator<ChatEvent>` — body is `{ question }` without a document, `{ question, document_id }` with one. A `404` response throws `AskRefusedError` with the server's detail (fallback message `"That document can't be used. Start a new conversation."` when there is no detail).

- [ ] **Step 1:** Regenerate the client (Makefile `api-client` target; read the Makefile for the exact command). Confirm `AskRequest` in `types.gen.ts` has `document_id?: string | null`.
- [ ] **Step 2: Write failing tests** in `chat.test.ts` (follow the existing `askInNewThread` tests' fake-fetch style): the body sent has `document_id` when given and has no `document_id` key when not; a `404` with `{"detail": "Document not found"}` rejects with `AskRefusedError("Document not found")`.
- [ ] **Step 3: Run** `cd web && npx vitest run src/api/chat.test.ts` — Expected: FAIL.
- [ ] **Step 4: Implement** the new parameter and the 404 branch (keep existing call sites compiling; `apiClient` moves to third position — update any caller/test that passed it second).
- [ ] **Step 5: Run** the tests and `npm run build` — Expected: PASS.
- [ ] **Step 6: Commit** — subject `Send the starting document with the first question`.

### Task 3: The chat page starts from a document

**Files:**
- Modify: `web/src/features/chat/ChatPage.tsx`, `web/src/features/chat/ChatPage.module.css`
- Test: `web/src/features/chat/ChatPage.test.tsx`

**Interfaces:**
- Consumes: `askInNewThread(question, documentId?)` from Task 2.
- Produces: `ChatPage` prop `ask?: (question: string, documentId?: string) => AsyncIterable<ChatEvent>` (default `(q, d) => askInNewThread(q, d)`); the page reads `useSearchParams().get("document")`.

- [ ] **Step 1: Write failing tests** (existing ChatPage test style; render inside a `MemoryRouter` with `initialEntries={["/chat?document=d1"]}` — check how the file renders today and add the entry):
  1. With a ready document `d1` titled "ReAct…" in `loadDocs`: the panel lists "ReAct…" with the "Added" badge; the notice "Started from ReAct…. It's listed in Documents; answers still use all your documents." shows (match with a text matcher on the paragraph); the textarea has focus.
  2. Asking sends `ask("q", "d1")`; a second question sends `ask("q2", undefined)` and the notice is gone after the first question.
  3. Removing the row before asking (click "Remove ReAct… from this conversation") drops it and the notice; asking then sends `ask("q", undefined)`.
  4. `?document=` naming an archived document, a processing one, or an unknown id: no notice, panel says "Documents used to answer will appear here.", ask sends no id.
  5. A `404` refusal (`AskRefusedError("Document not found")`) shows the message as a problem line (existing behavior; just assert it).
  6. If the panel was stored closed (see `usePanelOpen` tests for how), it opens when a starting document is shown.
- [ ] **Step 2: Run** `cd web && npx vitest run src/features/chat/ChatPage.test.tsx` — Expected: FAIL.
- [ ] **Step 3: Implement:**
  - In the `loadDocs` effect, also keep the starting document: `const id = searchParams.get("document"); const start = docs.find((d) => d.document_id === id && d.state === "ready" && !d.archived) ?? null; setStarting(start)`.
  - State `starting: DocumentResponse | null`. Before the first question (`exchange === null` and `threadId === null`), the panel's `documents` is `starting ? [asListed(starting)] : used`, where `asListed` builds the synthesized row from Global Constraints. `onRemoveDocument` when `threadId === null && starting`: `(id) => { setStarting(null); setAnnouncement(\`${starting.title} removed from this conversation.\`) }`.
  - In `submit()`, `const documentId = starting?.document_id; setStarting(null);` then `ask(trimmed, documentId)`.
  - Open the panel when a starting document is found and the panel is closed (use whatever `usePanelOpen` exposes; if it only has a toggle, call `togglePanel()` once when `!panelOpen`).
  - Focus: a `ref` on the textarea, focused in an effect when `starting` becomes non-null and the library is ready.
  - Notice: render above the welcome section while `starting && !exchange`: `<p className={styles.notice}><FileText …/> <span>Started from <em>{starting.title}</em>. It's listed in Documents; answers still use all your documents.</span></p>`; add `.notice` to `ChatPage.module.css` using existing tokens (look at `.problem` and DESIGN.md "notice row / info" for the token names).
- [ ] **Step 4: Run** the tests, then `npx vitest run && npm run build` — Expected: PASS.
- [ ] **Step 5: Commit** — subject `Open a new conversation that lists the document it started from`.

### Task 4: "Chat" on ready Library rows

**Files:**
- Modify: `web/src/features/library/DocumentTable.tsx`, `web/src/features/library/LibraryPage.tsx` (only if wiring is needed)
- Test: `web/src/features/library/DocumentTable.test.tsx` (and `LibraryPage.test.tsx` for navigation if the table takes a callback)

**Interfaces:**
- Produces: `DocumentTable` prop `onChat?: (doc: DocumentResponse) => void`; `LibraryPage` passes `(d) => navigate(\`/chat?document=${d.document_id}\`)` using `useNavigate` from `react-router`.

- [ ] **Step 1: Write failing tests:** a ready row shows a button named "Chat about {title}" with text "Chat"; clicking it calls `onChat` with the row; archived-ready, processing, failed, awaiting_subjects, and uploading rows have no such button. In `LibraryPage.test.tsx`, clicking it lands on `/chat?document=<id>` (render with a `MemoryRouter` + a `/chat` route that shows the location's search, matching how the file renders today).
- [ ] **Step 2: Run** `cd web && npx vitest run src/features/library` — Expected: FAIL.
- [ ] **Step 3: Implement** in `Actions`: before the `RowMenu`, `{doc.state === "ready" && !uploading && onChat && <Button size="sm" icon={MessageSquare} aria-label={\`Chat about ${doc.title}\`} disabled={busy} onClick={() => onChat(doc)}>Chat</Button>}` (archived rows already return early). Wire `onChat` in `LibraryPage`.
- [ ] **Step 4: Run** `npx vitest run && npm run build` — Expected: PASS.
- [ ] **Step 5: Commit** — subject `Offer Chat on every ready Library row`.

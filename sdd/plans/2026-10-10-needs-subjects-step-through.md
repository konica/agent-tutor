# Needs-subjects count, nav badge, and picker step-through Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Library's needs-subjects chip and a new Library badge in the side nav count the learner's non-archived documents in *choose subjects*. With several waiting, the subject picker steps through them ("1 of 3", Skip, Save and next). Once the last is saved, the Library shows every document ready with "Ask a question".

**Architecture:** Web only; no API change. `GET /documents` (active by default) already returns every non-archived document with its state, so counts come from it. `useLibraryCounts` also returns the waiting documents and whether every active document is ready. A small context in `src/app/needsSubjects.tsx` holds the count for the side nav. The shell loads the count on every navigation, and the Library reports a fresh count whenever its own counts change. `SubjectPicker` takes an optional `step` and `onSkip`. `LibraryPage` owns the queue.

**Tech Stack:** React 19, TypeScript, react-router, Vitest + Testing Library, CSS modules.

**Spec:** GitHub issue #80 (parent US-2b #10; PRD §8 US-2b, §9.5); mockup round v0.10 (`design-v0.10`), states `library-first-choose`, `library-choose-subjects`, `picker-step-through`, `library-first-ready`; prototype `sdd/design/prototype/js/documents.js` at that tag (lines 238, 358–464).

## Global Constraints

- Copy: chip and badge label "1 needs subjects" / "N need subjects"; picker kicker "Document 1 of 3"; footer "1 of 3", "Skip", "Save and next" (last step: "Save"); banner "**Your documents are ready.** Ask anything about them; answers cite the document and page." with button "Ask a question".
- No "needs subjects" banner (brief N1, M10).
- Counts include only the caller's **non-archived** documents in `awaiting_subjects`; the chip and the badge disappear at 0.
- Queue order (prototype `choose-one`): the clicked document first, then every other non-archived waiting document in list order.
- Skip leaves a document in *choose subjects*. Skip on the last step closes the picker.
- "Ask a question" navigates to `/chat`.
- UI uses `web/src/components/` and design tokens only (DESIGN.md); no prototype HTML/CSS.
- Checks: `cd web && npx vitest run && npm run build`.

## Review Focus

1. The learner filtered the table (subject or state) and then clicks "Choose subjects". The queue still holds every waiting document, because it comes from the unfiltered counts. Test: Task 2, "queues waiting documents hidden by a filter".
2. The chip filter "N need subjects" is on and the last document is saved. The state filter drops, so the table shows every document ready rather than "No documents match". Test: Task 3.
3. A document moves processing → choose subjects during polling. The chip and badge counts update without a reload. Test: Task 1, "recounts when polling sees a state change".
4. A save fails mid-step. The picker stays on that document with its error and does not advance. Test: Task 2.
5. Skip on the last step with nothing saved closes the picker quietly, with no "saved" message. Test: Task 2.

---

### Task 1: Counts from the whole active library, chip uses them, nav badge

**Files:**
- Modify: `web/src/features/library/useLibraryCounts.ts`
- Create: `web/src/app/needsSubjects.tsx`
- Modify: `web/src/components/AppShell/AppShell.tsx`
- Modify: `web/src/components/SideNav/SideNav.tsx`, `SideNav.module.css`, `SideNav.test.tsx`
- Modify: `web/src/features/library/LibraryPage.tsx` (chip count, report count, recount on poll change)
- Modify: `web/src/features/library/LibraryFilters.tsx` (chip hides at 0 even when pressed)
- Test: `web/src/features/library/LibraryPage.test.tsx`, `web/src/features/library/LibraryFilters.test.tsx`, `web/src/app/routes.test.tsx`

**Interfaces:**
- Produces:
  - `LibraryCounts = { active: number | null; archived: number | null; waiting: DocumentResponse[] | null; allReady: boolean; refresh: () => Promise<void> }`. `waiting` holds the active documents with `state === "awaiting_subjects"`, in list order. `allReady` is true when there is at least one active document and every one is `ready`.
  - `src/app/needsSubjects.tsx`:
    ```tsx
    export type NeedsSubjects = { count: number | null; report: (count: number) => void };
    export const NeedsSubjectsContext: React.Context<NeedsSubjects>; // default { count: null, report: () => {} }
    export function useNeedsSubjects(): NeedsSubjects;
    // Loads load({ state: "awaiting_subjects" }).length on mount and whenever `key` changes; a failure keeps the previous count.
    export function useNeedsSubjectsState(load: (f: DocumentFilters) => Promise<DocumentResponse[]>, key: string): NeedsSubjects;
    export function needsSubjectsLabel(count: number): string; // "1 needs subjects" | "N need subjects"
    ```
  - `SideNav` gains the prop `badges?: Partial<Record<string, { count: number; label: string }>>`, keyed by nav path.

- [ ] **Step 1: Failing tests.** In `LibraryPage.test.tsx`, add a `describe("needs subjects")` block with these cases:
  - "counts waiting documents across the whole active library, not the filtered list". `load` returns two `awaiting_subjects` documents and one ready for `{}`, and only the ready one for `{ subject_ids: ["s1"] }`. Choose the subject filter, then expect the button `"2 need subjects"`.
  - "hides the chip when nothing waits". All documents are ready, so no button matches `/need(s)? subjects/`.
  - "recounts when polling sees a state change". `load` first returns one processing document, then the same document as `awaiting_subjects`; `pollMs={20}`. Expect `findByRole("button", { name: "1 needs subjects" })`.
  - "reports the count to the shell". Render inside `<NeedsSubjectsContext.Provider value={{ count: null, report }}>` and expect `report` to have been called with `2`.
  In `SideNav.test.tsx`, add "shows a badge on Library with its label". Render with `badges={{ "/library": { count: 3, label: "3 need subjects" } }}`, expect link name `"Library, 3 need subjects"` and visible text `3`. When collapsed, the link `aria-label` and `data-tip` are `"Library, 3 need subjects"`. Without badges the name stays `"Library"`.
  In `routes.test.tsx`, add "shows the needs-subjects badge on Library from any page". Mock `loadDocuments` to return one awaiting document for `{ state: "awaiting_subjects" }`, render at `/chat`, and expect the Library link name `"Library, 1 needs subjects"`. Restore the default mock afterwards with `vi.mocked(loadDocuments).mockImplementation(async () => [])`.
  In `LibraryFilters.test.tsx`, change the existing case that shows the pressed chip at 0 (if there is one) so that `needsSubjects={0}` with `state: "awaiting_subjects"` renders no chip.

- [ ] **Step 2: Run** `cd web && npx vitest run src/features/library src/components/SideNav src/app` and confirm the new cases fail.

- [ ] **Step 3: Implement.**
  `useLibraryCounts.ts`: keep the two loads, then derive the new fields:
  ```ts
  const [counts, setCounts] = useState<Omit<LibraryCounts, "refresh">>({ active: null, archived: null, waiting: null, allReady: false });
  // in refresh, after both loads:
  setCounts({ active: active.length, archived: archived.length, waiting: active.filter((d) => d.state === "awaiting_subjects"), allReady: active.length > 0 && active.every((d) => d.state === "ready") });
  ```
  `src/app/needsSubjects.tsx`:
  ```tsx
  import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
  import type { DocumentFilters, DocumentResponse } from "../api/documents";

  export type NeedsSubjects = { count: number | null; report: (count: number) => void };
  export const NeedsSubjectsContext = createContext<NeedsSubjects>({ count: null, report: () => {} });
  export const useNeedsSubjects = () => useContext(NeedsSubjectsContext);
  export const needsSubjectsLabel = (count: number) => (count === 1 ? "1 needs subjects" : `${count} need subjects`);

  // The side nav's Library badge: the learner's non-archived documents waiting for subjects (PRD US-2b).
  // The shell reloads it on every navigation; the Library reports fresher counts as it polls.
  export function useNeedsSubjectsState(load: (filters: DocumentFilters) => Promise<DocumentResponse[]>, key: string): NeedsSubjects {
    const [count, setCount] = useState<number | null>(null);
    const loadRef = useRef(load);
    useEffect(() => { loadRef.current = load; }, [load]);
    useEffect(() => {
      let alive = true;
      loadRef.current({ state: "awaiting_subjects" }).then((docs) => { if (alive) setCount(docs.length); }, () => {}); // a failure keeps the count
      return () => { alive = false; };
    }, [key]);
    const report = useCallback((n: number) => setCount(n), []);
    return { count, report };
  }
  ```
  `AppShell.tsx`: add the prop `loadDocuments?: typeof loadDocuments` (default from `../../api/documents`). Call `const needs = useNeedsSubjectsState(load, pathname)` and wrap the returned tree in `<NeedsSubjectsContext.Provider value={needs}>`. Pass `badges={needs.count ? { "/library": { count: needs.count, label: needsSubjectsLabel(needs.count) } } : undefined}` to `SideNav`.
  `SideNav.tsx`: for an item with `const badge = badges?.[path]`, set `aria-label={badge ? `${label}, ${badge.label}` : collapsed ? label : undefined}` and `data-tip={collapsed ? (badge ? `${label}, ${badge.label}` : label) : undefined}`. After the text, render `{badge && <span className={styles.badge} aria-hidden="true">{badge.count}</span>}`. On the rail, the badge shows as well, with the class `styles.badge` and the rail rule below.
  `SideNav.module.css`:
  ```css
  /* The Library badge counts documents waiting for subjects (brief v0.10). */
  .badge {
    margin-left: auto; min-width: 18px; height: 18px; padding: 0 5px; border-radius: var(--r-pill);
    background: var(--attn-soft); color: var(--attn); font-size: var(--fs-12); font-weight: 650; line-height: 18px; text-align: center; font-variant-numeric: tabular-nums;
  }
  .collapsed .badge { position: absolute; top: 0; right: 2px; min-width: 14px; height: 14px; padding: 0 3px; font-size: 10px; line-height: 14px; margin: 0; }
  ```
  `LibraryPage.tsx`:
  - `const { report } = useNeedsSubjects();`
  - `const waitingCount = counts.waiting?.length ?? 0;`
  - `useEffect(() => { if (counts.waiting) report(counts.waiting.length); }, [counts.waiting, report]);`
  - Pass `needsSubjects={waitingCount}` to `LibraryFilters` instead of the filtered-list count.
  - In the live-region effect on `documents`, run `void counts.refresh()` when any document's state changed since the previous load. Compute this before the `justSaved` filtering, from `before` and `documents`.
  `LibraryFilters.tsx`: show the chip only when `showState && needsSubjects > 0`, and use `needsSubjectsLabel(needsSubjects)` for its text.

- [ ] **Step 4: Run** `cd web && npx vitest run` and confirm all tests pass.
- [ ] **Step 5: Commit** "Count documents that need subjects across the Library and badge the nav".

### Task 2: The picker steps through waiting documents

**Files:**
- Modify: `web/src/features/library/SubjectPicker.tsx`, `SubjectPicker.module.css`, `SubjectPicker.test.tsx`
- Modify: `web/src/features/library/LibraryPage.tsx`
- Test: `web/src/features/library/LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `counts.waiting` (Task 1).
- Produces: new `SubjectPicker` props `step?: { index: number; total: number }` (0-based index) and `onSkip?: () => void`. In step mode, a successful save calls `onSaved(updated)` and shows **no** saved screen; the parent advances or closes.

- [ ] **Step 1: Failing tests.**
  In `SubjectPicker.test.tsx`:
  - "shows its place in a step-through". With `step={{ index: 0, total: 3 }}`, the dialog shows kicker "Document 1 of 3", footer text "1 of 3", buttons "Skip" and "Save and next", and no "Cancel".
  - "says Save on the last step". With `step={{ index: 2, total: 3 }}`, the button reads "Save".
  - "calls onSaved without a saved screen in a step-through". After clicking Save and next, `onSaved` is called and "Subjects saved." is absent.
  - "Skip calls onSkip".
  - "stays on the document when a save fails in a step-through". `save` rejects, so the alert shows "Couldn't save subjects" and `onSaved` is not called.
  In `LibraryPage.test.tsx` (`describe("needs subjects")`), use three awaiting documents a, b, c, a `loadSuggestions` returning one shared suggestion, and a `saveSubjects` that returns the document as ready and updates a mutable fixture so later loads see it ready:
  - "steps through every waiting document, starting with the clicked one". Click "Choose subjects for b". Expect dialog text "Document 1 of 3" and title b. Save and next, then expect "Document 2 of 3" with title a. Skip, then expect "Document 3 of 3" with title c. Save, and the dialog closes. Expect `saveSubjects` called for b and c only, and the status to read "Subjects saved for 2 documents. They're ready to use."
  - "queues waiting documents hidden by a filter". `load` returns a, b, and c (all waiting) for `{}`, but only a for `{ subject_ids: ["s1"] }` (a already has subject s1 in this fixture). Choose the subject filter, click "Choose subjects for a", and the kicker still says "Document 1 of 3".
  - "Skip on the last step closes quietly when nothing was saved". With two waiting documents, Skip twice. The dialog is gone and the status does not contain "saved".
  - "a single waiting document keeps the plain picker". With one waiting document, the dialog shows "Processing finished", Cancel and Save, and after Save the "Subjects saved." screen with Done (unchanged behavior).

- [ ] **Step 2: Run** `cd web && npx vitest run src/features/library` and confirm the new cases fail.

- [ ] **Step 3: Implement.**
  `SubjectPicker.tsx`:
  - Add `step` and `onSkip` to `Props`. Compute `const last = !step || step.index === step.total - 1;` and `const kicker = step ? `Document ${step.index + 1} of ${step.total}` : document.state === "ready" ? "Ready document" : "Processing finished";`
  - In `onSave` on success: `if (step) { onSaved(updated); return; }`. The parent remounts the picker with a new `key` or closes it, so leave `saving` alone. Otherwise keep the current `setSavedDoc(updated); onSaved(updated);`.
  - Footer:
    ```tsx
    {step ? (
      <>
        <span className={styles.step}>{step.index + 1} of {step.total}</span>
        <Button variant="quiet" onClick={onSkip}>Skip</Button>
      </>
    ) : (
      <Button onClick={onClose}>Cancel</Button>
    )}
    <Button variant="primary" …>{last ? "Save" : "Save and next"}</Button>
    ```
  - `SubjectPicker.module.css`: `.step { margin-right: auto; align-self: center; font-size: var(--fs-13); color: var(--text-2); font-variant-numeric: tabular-nums; }`
  `LibraryPage.tsx`:
  - Replace `picking: DocumentResponse | null` with
    ```ts
    type Picking = { queue: DocumentResponse[]; index: number; saved: number };
    const [picking, setPicking] = useState<Picking | null>(null);
    ```
  - Open: when a row's Choose subjects is clicked (prototype `choose-one`):
    ```ts
    function choose(doc: DocumentResponse) {
      const others = (counts.waiting ?? list ?? []).filter((d) => d.state === "awaiting_subjects" && !d.archived && d.document_id !== doc.document_id);
      setPicking({ queue: [doc, ...others], index: 0, saved: 0 });
    }
    ```
  - Advance after a save or a skip:
    ```ts
    // Reads `picking` from render, not an updater: setStatus must not run twice under StrictMode.
    function advance(saved: boolean) {
      const p = picking;
      if (!p) return;
      const done = p.saved + (saved ? 1 : 0);
      if (p.index < p.queue.length - 1) {
        if (saved) setStatus(`Saved. Document ${p.index + 2} of ${p.queue.length}.`);
        setPicking({ ...p, index: p.index + 1, saved: done });
        return;
      }
      if (done) setStatus(`Subjects saved for ${done} ${done === 1 ? "document" : "documents"}. They're ready to use.`);
      setPicking(null);
    }
    ```
  - `onSaved(doc)` keeps its bookkeeping (`justSaved`, `seen`, refresh). It sets the "Subjects saved. X is ready to use." status only when the picker is not stepping (queue length 1).
  - Render:
    ```tsx
    {picking && (() => {
      const doc = picking.queue[picking.index]!;
      const multi = picking.queue.length > 1;
      return (
        <SubjectPicker
          key={doc.document_id}
          document={doc}
          step={multi ? { index: picking.index, total: picking.queue.length } : undefined}
          onSkip={() => advance(false)}
          load={loadSuggestions}
          save={saveSubjects}
          onClose={() => setPicking(null)}
          onSaved={(d) => { void onSaved(d, !multi); if (multi) advance(true); }}
        />
      );
    })()}
    ```
  - `usePageDrop` guard and `DropOverlay` keep working with `picking` truthy, so no change is needed there.

- [ ] **Step 4: Run** `cd web && npx vitest run` and confirm all tests pass.
- [ ] **Step 5: Commit** "Step through the documents that need subjects in the picker".

### Task 3: All ready: banner with "Ask a question", PRD

**Files:**
- Modify: `web/src/components/Banner/Banner.tsx`, `Banner.module.css` (optional `action`)
- Modify: `web/src/features/library/LibraryPage.tsx`, `LibraryPage.module.css`
- Modify: `sdd/prd.md` (status v2.29, changes row, a US-2b bullet)
- Test: `web/src/features/library/LibraryPage.test.tsx`

**Interfaces:**
- Consumes: `counts.allReady` (Task 1), the step-through (Task 2).
- Produces: `Banner` prop `action?: ReactNode`, rendered after the body and pushed right.

- [ ] **Step 1: Failing tests** in `describe("needs subjects")`:
  - "shows every document ready with Ask a question after the last save". There are two waiting documents and one ready, and the chip filter "2 need subjects" is pressed. Step through and save both. Expect the status text "Your documents are ready." (inside the banner), the state filter cleared (the State select reads "All states"), every row "Ready", and no chip. Click "Ask a question" and expect the ChatStub to show `/chat`.
  - "no ready banner while a document still waits or processes". Save one of two waiting documents and Skip the other. There is no "Your documents are ready." and the chip shows "1 needs subjects".
  - "no ready banner on load". A library that is already all ready shows no banner, because the banner follows a save in this visit.

- [ ] **Step 2: Run** and confirm the new cases fail.

- [ ] **Step 3: Implement.**
  `Banner.tsx`: add `action?: ReactNode` to Props and render `{action && <div className={styles.action}>{action}</div>}` after `.body`. In `Banner.module.css`, add `.action { margin-left: auto; flex: none; align-self: center; }`.
  `LibraryPage.tsx`:
  - `const [finished, setFinished] = useState(false);`. In `onSaved`, `setFinished(true)`.
  - `const allReadyNow = finished && counts.allReady && !archivedView;`
  - Effect, so the Library shows every document once none waits:
    ```ts
    useEffect(() => {
      if (finished && counts.allReady) setFilters((f) => { if (f.state !== "awaiting_subjects") return f; const { state: _state, ...rest } = f; return rest; });
    }, [finished, counts.allReady]);
    ```
  - Render above the toolbar, below the status/upload notices:
    ```tsx
    {allReadyNow && (
      <div role="status" className={styles.ready}>
        <Banner variant="success" inline title="Your documents are ready." action={<Button variant="primary" size="sm" icon={MessageSquare} onClick={() => navigate("/chat")}>Ask a question</Button>}>
          Ask anything about them; answers cite the document and page.
        </Banner>
      </div>
    )}
    ```
    Add `.ready { margin-bottom: var(--sp-2); }` to `LibraryPage.module.css`. Import `MessageSquare` from lucide-react and `Banner` from `../../components/Banner/Banner`.
  `sdd/prd.md`:
  - Status line: `Draft v2.28` → `Draft v2.29`.
  - Insert a changes row above v2.27's: `| **Changes from v2.28** | Documents that need subjects (#80, US-2b): the Library toolbar chip "N need subjects" and a badge on the side nav's Library entry count the learner's non-archived documents in *choose subjects* and disappear at none; the chip filters the table to them (no banner). With several waiting, the picker steps through them (the chosen one first, then the others in list order): "1 of 3", Skip (the document stays in *choose subjects*), Save and next. When a save leaves every active document ready, the Library says so with "Ask a question", which opens the chat. |`
  - US-2b: add a bullet after the 1–3 subjects bullet: `- Documents waiting in *choose subjects* are highlighted in the Library; the toolbar chip "N need subjects" filters to them and the side nav's Library entry shows the count. With several waiting, the picker steps through them ("1 of 3", **Skip**, **Save and next**); a skipped document stays in *choose subjects*. When the last is saved and every document is ready, the Library offers **Ask a question**.`
  - Also update `AGENTS.md`'s "`sdd/prd.md` (v2.28)" to v2.29.

- [ ] **Step 4: Run** `cd web && npx vitest run && npm run build` and confirm both pass.
- [ ] **Step 5: Commit** "Show the Library ready with Ask a question once subjects are chosen".

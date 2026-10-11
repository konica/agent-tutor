# Open a Document from the Library Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Library opens a document in the overlay viewer: a ready or *choose subjects* row's title opens it, and document details gets **Open** (ready, *choose subjects*, archived read-only with Restore). Ticket #209.

**Architecture:** Web only. The overlay (`ViewerDialog` → `DocumentViewer`) and its API already exist (#123). `DocumentTable` gains `onView` for the title of a viewable row; `DocumentDetailsPanel` gains an **Open** button; `LibraryPage` holds `viewing` state and renders `ViewerDialog`. Following prototype v0.10 (`dp-open`), Open from details **replaces** the panel, and closing the viewer reopens details with focus on Open. `DocumentViewer` gains `onRestored` so a restore in the viewer re-lists the Library.

**Tech Stack:** React 19 + TypeScript, Vite, Vitest + Testing Library, CSS modules.

**Spec:** GitHub issue #209; PRD `sdd/prd.md` §8 US-3, US-4b, US-10, §13 Q60; prototype `sdd/design/prototype/` at tag `design-v0.10` (`js/documents.js` `dp-open`, `canOpen`; `js/viewer.js` `openViewer`).

## Global Constraints

- Web only: no API, backend, or generated-client changes.
- Viewable = `state` is `"ready"` or `"awaiting_subjects"` (archived or not). Processing and failed documents never offer Open.
- A row title opens the viewer only for a viewable, **non-archived** row that is not still uploading. Archived, processing, failed rows keep opening details; uploading rows keep a plain title.
- Details stays reachable from a row's More menu (`Details` item, unchanged).
- The viewer opens at page 1 with no passage; `closeLabel="Close"`.
- Rebuild with `web/src/components/`; never copy prototype HTML/CSS. Visual rules in `DESIGN.md`.
- Match surrounding code: one-line comments that say why, no new abstractions.
- Commit subjects in the imperative mood; body says why; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Checks: `cd web && npx vitest run <files>` per task; at the end `cd web && npm run build`.

## Review Focus

1. Archived document restored in the viewer while on the Archived tab: the row leaves the list, the viewer stays open showing the document as active, and closing it doesn't drop focus to `<body>` with nothing focused (details reopens and focuses Open). — Task 3 test "restores an archived document in the viewer…".
2. Open from details, then Escape: the viewer closes, details reopens, and focus lands on details' **Open** (not the row title, not `<body>`). — Task 3 test "opens from details, replacing the panel…".
3. The Library's `restore` test seam must reach the viewer (otherwise the real API is called in tests and in no-deps setups the wrong function runs). — Task 3 passes `restore` into `viewerDeps`.
4. Page drop while the viewer is open must not start an upload (the viewer is modal). — Task 3 test "ignores a page drop while the viewer is open".
5. Loading skeleton and the error card with Retry render inside the Library's overlay. — Task 3 test "shows the error card with Retry in the overlay".

---

### Task 1: `onRestored` from the viewer

**Files:**
- Modify: `web/src/features/viewer/DocumentViewer.tsx` (Props; `onRestore` success branch)
- Modify: `web/src/features/viewer/ViewerDialog.tsx` (Props; pass through)
- Test: `web/src/features/viewer/ViewerDialog.test.tsx`

**Interfaces:**
- Produces: `DocumentViewer` prop `onRestored?: (document: DocumentResponse) => void`; `ViewerDialog` prop `onRestored?: (document: DocumentResponse) => void` (not part of `ViewerDeps`; it is behavior, not a test seam).

- [ ] **Step 1: Write the failing test** (append inside `describe("ViewerDialog", …)` in `ViewerDialog.test.tsx`; add `import { fakeDocument, fakeFile, fakeViewerDeps } from "./testFakes";` and `waitFor` from Testing Library)

```tsx
  it("restores an archived document in place and reports it with onRestored", async () => {
    const deps = { ...fakeViewerDeps(), loadFile: vi.fn(async () => fakeFile({ archived: true })), restore: vi.fn(async () => fakeDocument()) };
    const onRestored = vi.fn();
    render(<ViewerDialog documentId="d1" closeLabel="Close" onClose={vi.fn()} onRestored={onRestored} viewerDeps={deps} />);
    expect(await screen.findByText("Archived · read-only")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    await waitFor(() => expect(onRestored).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ document_id: "d1", archived: false })));
    expect(deps.restore).toHaveBeenCalledWith("d1");
    expect(screen.queryByText("Archived · read-only")).toBeNull();
    expect(screen.getByRole("dialog", { name: "ReAct" })).toBeVisible();
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd web && npx vitest run src/features/viewer/ViewerDialog.test.tsx`
Expected: FAIL — TypeScript/vitest reports `onRestored` not called (prop doesn't exist yet).

- [ ] **Step 3: Implement**

In `DocumentViewer.tsx` Props, after `onPageChange`:

```ts
  onRestored?: (document: DocumentResponse) => void; // the Library re-lists (the row leaves the Archived tab)
```

Destructure `onRestored` in `Viewer` and call it in the restore success branch, after `setDocument(updated);`:

```ts
        onRestored?.(updated);
```

In `ViewerDialog.tsx` add to Props `onRestored?: (document: DocumentResponse) => void;` (import `type DocumentResponse` from `"../../api/documents"`), destructure it, and pass `onRestored={onRestored}` to `<DocumentViewer>` (before `{...viewerDeps}`).

- [ ] **Step 4: Run the viewer tests**

Run: `cd web && npx vitest run src/features/viewer`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/viewer/DocumentViewer.tsx web/src/features/viewer/ViewerDialog.tsx web/src/features/viewer/ViewerDialog.test.tsx
git commit -m "Report a restore from the viewer to its opener" -m "The Library opens the overlay for archived documents (#209) and must re-list when the learner restores one there."
```

---

### Task 2: Row title opens the viewer; details gets Open

**Files:**
- Modify: `web/src/features/library/DocumentTable.tsx` (Props, title cell)
- Modify: `web/src/features/library/DocumentDetails.tsx` (Props, footer, focus)
- Test: `web/src/features/library/DocumentTable.test.tsx`, `web/src/features/library/DocumentDetails.test.tsx`

**Interfaces:**
- Produces: `DocumentTable` prop `onView?: (doc: DocumentResponse) => void` — when set, the title button of a non-archived row in `ready` or `awaiting_subjects` (not uploading) calls it instead of `onOpen`.
- Produces: `DocumentDetailsPanel` props `onOpenDocument?: (details: DocumentDetails) => void` and `focusOpen?: boolean` (focus Open once loaded — used when the viewer closes back to details).

- [ ] **Step 1: Write the failing table tests** (in `describe("DocumentTable open details", …)`)

```tsx
  it("opens the viewer from a ready or choose-subjects title, and details from the others", async () => {
    const onOpen = vi.fn();
    const onView = vi.fn();
    const rows = [
      doc,
      { ...doc, document_id: "d2", title: "Waiting", state: "awaiting_subjects" as const },
      { ...doc, document_id: "d3", title: "Old", archived: true },
      { ...doc, document_id: "d4", title: "Broken", state: "failed" as const },
      { ...doc, document_id: "d5", title: "Busy", state: "processing" as const },
    ];
    render(<DocumentTable documents={rows} {...props} onOpen={onOpen} onView={onView} onRestore={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Toolformer" }));
    await userEvent.click(screen.getByRole("button", { name: "Waiting" }));
    expect(onView.mock.calls.map(([d]) => d.document_id)).toEqual(["d1", "d2"]);
    for (const name of ["Old", "Broken", "Busy"]) await userEvent.click(screen.getByRole("button", { name }));
    expect(onOpen.mock.calls.map(([d]) => d.document_id)).toEqual(["d3", "d4", "d5"]);
  });
```

Keep the existing test "opens details from the title button, for an active and an archived row" unchanged (it passes no `onView`, so titles still open details).

- [ ] **Step 2: Write the failing details tests** (in `DocumentDetails.test.tsx`)

```tsx
  it("offers Open for ready, choose-subjects, and archived documents, not processing or failed", async () => {
    for (const [over, shown] of [
      [{}, true],
      [{ state: "awaiting_subjects" as const }, true],
      [{ archived: true }, true],
      [{ state: "processing" as const }, false],
      [{ state: "failed" as const }, false],
    ] as const) {
      const onOpenDocument = vi.fn();
      const { unmount } = renderPanel(details(over), { onOpenDocument });
      await screen.findByRole("heading", { name: "ReAct" });
      const open = screen.queryByRole("button", { name: "Open" });
      if (!shown) expect(open).toBeNull();
      else {
        await userEvent.click(open!);
        expect(onOpenDocument).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ document_id: "d1" }));
      }
      unmount();
    }
  });

  it("makes Restore secondary beside Open for an archived document", async () => {
    setup(details({ archived: true }), { onOpenDocument: vi.fn() });
    const restore = await screen.findByRole("button", { name: "Restore" });
    const open = screen.getByRole("button", { name: "Open" });
    expect(restore.compareDocumentPosition(open) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy(); // Open last, the main action
    expect(open.className).toMatch(/primary/);
    expect(restore.className).not.toMatch(/primary/);
  });

  it("focuses Open once loaded when asked (the viewer closed back to details)", async () => {
    setup(details(), { onOpenDocument: vi.fn(), focusOpen: true });
    await waitFor(() => expect(screen.getByRole("button", { name: "Open" })).toHaveFocus());
  });
```

`renderPanel` is `setup` returning the render result. Change `setup` to return both:

```tsx
function renderPanel(first: DocumentDetails = details(), over: Partial<Parameters<typeof DocumentDetailsPanel>[0]> = {}) {
  const props = { /* the same object as today in setup */ };
  return { props, ...render(<DocumentDetailsPanel {...props} />) };
}
function setup(first: DocumentDetails = details(), over: Partial<Parameters<typeof DocumentDetailsPanel>[0]> = {}) {
  return renderPanel(first, over).props;
}
```

(Move the existing body of `setup` into `renderPanel`; `setup` keeps its signature and return value so existing tests don't change.)

- [ ] **Step 3: Run to verify they fail**

Run: `cd web && npx vitest run src/features/library/DocumentTable.test.tsx src/features/library/DocumentDetails.test.tsx`
Expected: the three new details tests and the new table test FAIL.

- [ ] **Step 4: Implement `DocumentTable`**

Props, after `onOpen`:

```ts
  onView?: (doc: DocumentResponse) => void; // a ready or choose-subjects title opens the document viewer (PRD US-3)
```

Add `onView` to the `DocumentTable` destructuring. In the title cell, replace `onClick={() => onOpen(doc)}` with:

```tsx
onClick={() => (onView && !doc.archived && viewable(doc) ? onView(doc) : onOpen(doc))}
```

and add near the top of the file:

```ts
// Ready and choose-subjects documents open in the viewer; processing and failed ones can't (PRD US-4b).
export const viewable = (doc: Pick<DocumentResponse, "state">) => doc.state === "ready" || doc.state === "awaiting_subjects";
```

- [ ] **Step 5: Implement `DocumentDetailsPanel`**

Props, after `onChangeSubjects`:

```ts
  onOpenDocument?: (details: DocumentDetails) => void; // the viewer; archived documents open read-only
  focusOpen?: boolean; // the viewer closed back to details: Open gets focus again
```

Import `FileText` from lucide-react and `viewable` from `./DocumentTable`. Add `const openRef = useRef<HTMLButtonElement>(null);` and, after the existing effects:

```ts
  // Back from the viewer: Open had focus when the panel made way for it.
  const loaded = details !== null;
  useEffect(() => {
    if (focusOpen && loaded) openRef.current?.focus();
  }, [focusOpen, loaded]);
```

`Button` (`web/src/components/Button/Button.tsx`) spreads `...rest` onto `<button>`, and React 19 passes `ref` as a prop, but its Props type (`ButtonHTMLAttributes<HTMLButtonElement> & …`) has no `ref`. Add it to the type: `ref?: Ref<HTMLButtonElement>;` (import `type Ref` from "react"). No other change.

Footer: replace the footer content with

```tsx
        <div className={styles.footer}>
          {details.archived ? (
            <Button variant={canOpen ? "secondary" : "primary"} icon={RotateCcw} disabled={busy || isEditing} onClick={() => void changeArchive(false)}>
              Restore
            </Button>
          ) : (
            <Button icon={Archive} disabled={busy || isEditing} onClick={() => void changeArchive(true)}>
              Archive
            </Button>
          )}
          {canOpen && (
            <Button ref={openRef} variant="primary" icon={FileText} disabled={busy || isEditing} onClick={() => onOpenDocument(details)}>
              Open
            </Button>
          )}
        </div>
```

with `const canOpen = onOpenDocument !== undefined && viewable(details);` computed after the `!details` early return (TypeScript narrowing: use `onOpenDocument && viewable(details)` inline or `onOpenDocument!` inside the click handler — keep it type-safe without `!` by writing `{onOpenDocument && viewable(details) && (…onClick={() => onOpenDocument(details)}…)}` and `variant={onOpenDocument && viewable(details) ? "secondary" : "primary"}`).

- [ ] **Step 6: Run the library component tests**

Run: `cd web && npx vitest run src/features/library/DocumentTable.test.tsx src/features/library/DocumentDetails.test.tsx`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/library/DocumentTable.tsx web/src/features/library/DocumentDetails.tsx web/src/features/library/*.test.tsx web/src/components/Button/Button.tsx
git commit -m "Offer Open in document details and a viewer link on ready rows" -m "PRD US-3 and US-10: a ready row's title opens the viewer, and details opens ready, choose-subjects, and archived documents (#209)."
```


---

### Task 3: Library opens the overlay; PRD

**Files:**
- Modify: `web/src/features/library/LibraryPage.tsx`
- Modify: `web/src/features/library/LibraryPage.test.tsx`
- Modify: `sdd/prd.md` (status v2.36 → v2.37, new "Changes from v2.36" row, US-10 bullet, v2.27 note)

**Interfaces:**
- Consumes: `ViewerDialog` (`documentId`, `closeLabel`, `onClose`, `onRestored`, `viewerDeps`), `ViewerDeps` from `../viewer/ViewerDialog`; `DocumentTable.onView`; `DocumentDetailsPanel.onOpenDocument`, `focusOpen`.
- Produces: `LibraryPage` prop `viewerDeps?: ViewerDeps` (test seam: file link and PDF loader).

- [ ] **Step 1: Update existing tests that click a ready title to get details**

In `describe("LibraryPage document details", …)`, a ready row's title now opens the viewer. Change those tests to open details from More → Details:

```tsx
  async function openDetails() {
    await userEvent.click(await screen.findByRole("button", { name: "More actions for Toolformer" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Details" }));
  }
```

- "opens a dialog from the row title and returns focus to it on close": make the row `state: "failed"` with `failure_reason: "Unreadable"` for this one test (failed titles still open details) — or rename it to "opens details from an archived row's title…" using `archived: true`. Use the failed variant: give `setup` an optional `over: Partial<DocumentResponse>` merged into `row` and `full()`.
- "re-lists after a title change" and "re-lists after archiving from the panel": replace the title click with `await openDetails();`. In "re-lists after a title change", the final assertion stays `findByRole("button", { name: "Tool use" })`.
- Search the whole file for other clicks on a ready/awaiting row's title expecting details (`grep -n 'findByRole("button", { name: "' LibraryPage.test.tsx`) — e.g. in `describe("LibraryPage change subjects", …)` — and switch them to More → Details.

- [ ] **Step 2: Write the failing Library tests** (new `describe("LibraryPage document viewer", …)` at the end of the file; imports: `fakeViewerDeps`, `fakeFile` from `../viewer/testFakes`)

```tsx
describe("LibraryPage document viewer", () => {
  const ready: DocumentResponse = { ...processing, document_id: "d1", title: "ReAct", state: "ready" };
  const old: DocumentResponse = { ...processing, document_id: "d7", title: "GPT-3", state: "awaiting_subjects", archived: true };
  const detailsOf = (doc: DocumentResponse) => ({ ...doc, extracted_title: doc.title, title_overridden: false, doi: null, file_name: "x.pdf", pages: 3, summary: null });

  function library(active: DocumentResponse[], archived: DocumentResponse[]) {
    const lists = { active: [...active], archived: [...archived] };
    const load = vi.fn(async (f: DocumentFilters) => (f.archived ? lists.archived : lists.active));
    const find = (id: string) => [...lists.active, ...lists.archived].find((d) => d.document_id === id)!;
    const restore = vi.fn(async (id: string) => {
      const doc = { ...find(id), archived: false };
      lists.archived = lists.archived.filter((d) => d.document_id !== id);
      lists.active = [doc, ...lists.active];
      return doc;
    });
    const loadDetails = vi.fn(async (id: string) => detailsOf(find(id)));
    const deps = { ...fakeViewerDeps(), loadFile: vi.fn(async (id: string) => fakeFile({ ...find(id) }, `url-${id}`)) };
    return { load, restore, loadDetails, deps };
  }
  const page = (l: ReturnType<typeof library>) =>
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={l.load} upload={vi.fn()} restore={l.restore} loadDetails={l.loadDetails} viewerDeps={l.deps} />);
  const tab = (name: "Active" | "Archived") => screen.getByRole("tab", { name: new RegExp(`^${name}`) });

  it("opens a ready row's title in the overlay at page 1 and returns focus to the title", async () => {
    const l = library([ready], []);
    page(l);
    const title = await screen.findByRole("button", { name: "ReAct" });
    await userEvent.click(title);
    const viewer = await screen.findByRole("dialog", { name: "ReAct" });
    expect(await within(viewer).findByText("p. 1 / 3")).toBeVisible();
    expect(screen.queryByText("Document details")).toBeNull();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(title).toHaveFocus();
  });

  it("opens from details, replacing the panel, and goes back to details with Open focused", async () => {
    const l = library([ready], []);
    page(l);
    await userEvent.click(await screen.findByRole("button", { name: "More actions for ReAct" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Details" }));
    await userEvent.click(await screen.findByRole("button", { name: "Open" }));
    expect(await screen.findByText("p. 1 / 3")).toBeVisible();
    expect(screen.queryByText("Document details")).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(await screen.findByText("Document details")).toBeVisible();
    await waitFor(() => expect(screen.getByRole("button", { name: "Open" })).toHaveFocus());
  });

  it("restores an archived document in the viewer: read-only first, then the row leaves Archived and the viewer stays", async () => {
    const l = library([], [old]);
    page(l);
    await waitFor(() => expect(tab("Archived")).toHaveTextContent("1"));
    await userEvent.click(tab("Archived"));
    await userEvent.click(await screen.findByRole("button", { name: "GPT-3" })); // an archived title opens details
    await userEvent.click(await screen.findByRole("button", { name: "Open" }));
    expect(await screen.findByText("Archived · read-only")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));
    expect(l.restore).toHaveBeenCalledExactlyOnceWith("d7");
    await waitFor(() => expect(screen.queryByText("Archived · read-only")).toBeNull());
    expect(screen.getByRole("dialog", { name: "GPT-3" })).toBeVisible();
    await waitFor(() => expect(tab("Archived")).toHaveTextContent("0"));
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(await screen.findByText("Document details")).toBeVisible();
    expect(screen.getByRole("button", { name: "Archive" })).toBeVisible(); // details reloaded as active
    await waitFor(() => expect(screen.getByRole("button", { name: "Open" })).toHaveFocus());
  });

  it("shows the error card with Retry in the overlay", async () => {
    const l = library([ready], []);
    l.deps.loadFile.mockRejectedValueOnce(new Error("offline"));
    page(l);
    await userEvent.click(await screen.findByRole("button", { name: "ReAct" }));
    expect(await screen.findByText("We couldn't open this document.")).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByText("p. 1 / 3")).toBeVisible();
  });

  it("ignores a page drop while the viewer is open", async () => {
    const l = library([ready], []);
    const upload = vi.fn();
    render(<LibraryPage loadSubjects={noSubjects} check={notInLibrary} loadLimits={limits} load={l.load} upload={upload} loadDetails={l.loadDetails} viewerDeps={l.deps} />);
    await userEvent.click(await screen.findByRole("button", { name: "ReAct" }));
    await screen.findByText("p. 1 / 3");
    const file = new File(["%PDF"], "a.pdf", { type: "application/pdf" });
    fireEvent.drop(document.body, { dataTransfer: { types: ["Files"], files: [file] } });
    expect(upload).not.toHaveBeenCalled();
  });
});
```

The drop shape matches the existing drop tests (`LibraryPage.test.tsx:271`); if they wait or flush before asserting no upload, do the same. If `useDocumentFile` reports a load failure differently than `"error"` for a plain `Error` (read `useDocumentFile.ts`), use an error that yields the Retry card.

- [ ] **Step 3: Run to verify they fail**

Run: `cd web && npx vitest run src/features/library/LibraryPage.test.tsx`
Expected: the new viewer tests FAIL (no `viewerDeps` prop, titles still open details); the updated details tests already PASS.

- [ ] **Step 4: Implement `LibraryPage`**

Imports: `import { ViewerDialog, type ViewerDeps } from "../viewer/ViewerDialog";`.

Props: add `viewerDeps?: ViewerDeps; // tests: the viewer's file link and PDF loader` and destructure `viewerDeps`.

State, after `details`:

```ts
  const [viewing, setViewing] = useState<{ id: string; fromDetails: boolean } | null>(null); // the document open in the viewer
```

Change the `details` state type to `{ id: string; editing: boolean; focusOpen?: boolean } | null`.

In the "panel gives focus back to its opener" effect, return early while the viewer is open (it took the panel's place and handles focus itself) — add `viewing` to the deps:

```ts
  useEffect(() => {
    if (details) {
      detailsOpener.current = details.id;
      return;
    }
    if (viewing) return; // the viewer replaced the panel and gives it back when it closes
    …unchanged…
  }, [details, viewing]);
```

Handlers, next to `changeFromDetails`:

```ts
  // Like the picker, the viewer replaces the details panel (both are modal) and gives it back, with Open focused, when it closes.
  function openFromDetails(doc: DocumentDetails) {
    setDetails(null);
    setViewing({ id: doc.document_id, fromDetails: true });
  }

  function closeViewer() {
    const v = viewing;
    setViewing(null);
    if (v?.fromDetails) setDetails({ id: v.id, editing: false, focusOpen: true });
  }

  function restoredInViewer(doc: DocumentResponse) {
    setStatus(`${doc.title} restored.`);
    void Promise.all([refresh(), counts.refresh(), refreshSubjects()]);
  }
```

Drop guard: `if (!picking && !details && !viewing && !limitedRef.current)` and `{dragging && !picking && !details && !viewing && !limited && <DropOverlay />}`.

`DocumentTable`: add `onView={(d) => setViewing({ id: d.document_id, fromDetails: false })}`.

`DocumentDetailsPanel`: add `focusOpen={details.focusOpen}` and `onOpenDocument={openFromDetails}`.

After the details panel:

```tsx
      {viewing && (
        <ViewerDialog
          key={viewing.id}
          documentId={viewing.id}
          closeLabel="Close"
          onClose={closeViewer}
          onRestored={restoredInViewer}
          viewerDeps={{ restore, ...viewerDeps }}
        />
      )}
```

(`restore` is the Library's own seam, so the viewer restores through the same function as the row and details.)

- [ ] **Step 5: Run the Library tests**

Run: `cd web && npx vitest run src/features/library`
Expected: all PASS.

- [ ] **Step 6: Update the PRD**

In `sdd/prd.md`:
- Status line: `Draft v2.36` → `Draft v2.37`.
- Insert a row above `| **Changes from v2.35** |`:

```
| **Changes from v2.36** | Open a document from the Library (#209, US-3, US-10): a ready or *choose subjects* row's title opens the document viewer as an overlay at page 1 (Details stays in the row's More menu; archived, processing, and failed rows' titles open details). Document details offers **Open** for ready, *choose subjects*, and archived documents; it replaces the panel, and closing the viewer returns to details. An archived document opens read-only with "Archived" and Restore; restoring there moves the row out of Archived and keeps the viewer open. Web only. |
```

- US-10, after the bullet ending "They can also **delete** a document (US-10c).", add:

```
- From the Library, a ready or *choose subjects* row's title opens the document viewer (an overlay, Q60); **document details** shows the facts, summary, and subjects and offers **Open** for ready, *choose subjects*, and archived documents (archived read-only, with Restore).
```

- In the v2.27 row, replace "Open, Ask about this, and Change subjects in details come with their own stories (#118, #123, #132)" with "Ask about this and Change subjects in details come with their own stories (#132); Open came with #209".

- [ ] **Step 7: Build**

Run: `cd web && npm run build`
Expected: exits 0.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/library/LibraryPage.tsx web/src/features/library/LibraryPage.test.tsx sdd/prd.md
git commit -m "Open a document from the Library in the overlay viewer" -m "Closes the US-3/US-10 gap left by #109 and #123: a document opened only from a conversation (#209)."
```

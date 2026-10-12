# Citation Markers Open Their Passage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Each `[n]` marker in a chat answer becomes a link-styled control that opens its cited passage beside the conversation, exactly as that source's Sources chip does (issue #215).

**Architecture:** First move a turn's answer paragraph and its Sources line out of `ChatPage.tsx` into a new `Answer` component, with no change in behavior. A pure function `splitMarkers` cuts the answer text into plain-text pieces and marker pieces, using the same marker forms the backend reads (`[1]`, `[1, 2]`, `[1-3]`, `[1–3]`). `Answer` renders a marker piece as a `<button>` only when the answer's citations have arrived, Show citations is on, and the number has a source in that answer. Everything is rendered as React text nodes, so model output is never read as HTML.

**Tech Stack:** React 19 + TypeScript, CSS modules with DESIGN.md tokens, Vitest + Testing Library (`web/`).

**Spec:** GitHub issue #215 (`gh issue view 215`); PRD `sdd/prd.md` US-4b; `DESIGN.md` → Chat, Split view, Accessibility.

## Global Constraints

- Answer text is still rendered as text: no HTML from the model is ever interpreted (no `dangerouslySetInnerHTML`, no HTML parsing).
- Marker grammar matches the backend exactly: `backend/src/smart_tutor/tutoring/application/answer.py` `_MARKER = r"\[(\d+(?:\s*[-–,]\s*\d+)*)\]"`.
- Accessible name for a marker: `Source <n>: <document title>, p. <page>` (or `, page unavailable`), plus `, archived` for an archived document; `aria-current="true"` while its passage is shown; visible `:focus-visible` outline.
- Styles use only the DESIGN.md tokens already used in `ChatPage.module.css` (`--accent-text`, `--accent-soft`, `--focus`, `--r-sm`, `--text-2`); never paste prototype CSS.
- Match the surrounding code: short "why" comments, the same naming and idioms as `ChatPage.tsx`.
- Commit subjects in the imperative mood, a body that says why, and end each message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run web commands from `web/`: `npx vitest run <path>` for one file, `npm test` for all, `npm run build` for type check and bundle.

## Decisions taken while planning

- **Single marker vs group.** A single marker `[2]` is one control whose text is the whole `[2]`. In a group (`[1, 2]`, `[1–3]`), each **number shown** is its own control and the brackets, commas, and dashes stay text. A range's middle numbers (the 2 in `[1–3]`) are not shown in the text, so they get no inline control; the Sources line still has their chips.
- **Title tooltip.** A marker button's `title` equals its accessible name (`Source 1: a.pdf, p. 3`), so sighted mouse users see the source too. This doesn't collide with the existing `getByTitle("a.pdf, p. 3")` tests, which match whole strings.
- **Streaming.** Citations always arrive after the last delta (`backend/src/smart_tutor/apps/agent/server.py` docstring), so "the answer has citations" is the signal for linking. While `citations` is empty, the answer renders as one text node, as it does today.

## Review Focus

1. The same chunk cited twice in one answer (`… [1] … [1].`): both markers show `aria-current`, and closing the pane returns focus to the marker that was clicked. Pinned in Task 3, Step 1 (ChatPage test "returns focus to the marker that opened it").
2. The same chunk id cited in two turns of a reopened conversation: only the clicked turn's marker and chip are `aria-current`. Pinned in Task 3, Step 1 (ChatPage test "marks only the clicked turn's marker").
3. Bracketed text that isn't a citation (`x[0]`, `[a]`, `[1,]`, `[ 1]`, `[7]` when the answer has no source 7) stays plain text. Pinned in Task 2 (parser) and Task 3 (`Answer` test "keeps a number with no source as text").
4. Leading zeros (`[01]`) name source 1, as the backend's `int("01")` does. Pinned in Task 2.
5. Markup in an answer (`<b>bold</b> <img src=x onerror=alert(1)>`) shows as literal text, with markers around it still linked. Pinned in Task 3 (`Answer` test "never renders the answer as HTML").

---

## File structure

| File | Responsibility |
|---|---|
| `web/src/features/chat/Answer.tsx` (create) | One turn's answer paragraph (text with inline markers) and its Sources line |
| `web/src/features/chat/Answer.module.css` (create) | Styles moved from `ChatPage.module.css` (`.answer`, `.sources` … `.sourceTitle`) plus `.marker` |
| `web/src/features/chat/Answer.test.tsx` (create) | Unit tests of the markers and the Sources line in isolation |
| `web/src/features/chat/citationMarkers.ts` (create) | `splitMarkers(text)`: pure parser of the marker forms |
| `web/src/features/chat/citationMarkers.test.ts` (create) | Parser tests |
| `web/src/features/chat/ChatPage.tsx` (modify) | Renders `<Answer>` in place of the inline answer and Sources markup |
| `web/src/features/chat/ChatPage.module.css` (modify) | Loses the moved styles |
| `web/src/features/chat/ChatPage.test.tsx` (modify) | Answer-text matcher; integration tests of markers in the split view |
| `DESIGN.md`, `sdd/prd.md`, `sdd/design/brief.md` (modify) | Docs (Task 3) |

---

### Task 1: Move a turn's answer and Sources line into `Answer` (prefactor)

**Files:**
- Create: `web/src/features/chat/Answer.tsx`
- Create: `web/src/features/chat/Answer.module.css`
- Modify: `web/src/features/chat/ChatPage.tsx` (imports at lines 1–51; `sourcesId` at line 197; the turn rendering at lines 775–893)
- Modify: `web/src/features/chat/ChatPage.module.css` (remove lines 57–91)

**Interfaces:**
- Produces: `export function Answer(props: AnswerProps)` in `Answer.tsx`, where

```ts
type Props = {
  text: string;
  citations: ChatCitation[];
  showCitations: boolean;
  deletedIds: ReadonlySet<string>;
  shownChunkId: string | null;
  onOpenCitation: (citation: ChatCitation, from: HTMLElement) => void;
};
```

No new tests: behavior is unchanged and the existing `ChatPage.test.tsx` suite is the guard.

- [ ] **Step 1: Run the chat tests to record the baseline**

Run (from `web/`): `npx vitest run src/features/chat`
Expected: all pass. If any fail before you change anything, stop and report.

- [ ] **Step 2: Create `Answer.module.css`**

Move these rules **verbatim** from `ChatPage.module.css` (its lines 57–91: the `/* The tutor's words … */` comment and `.answer`, then the `/* One line of source chips … */` comment through `.sourceTitle`) into the new file, and delete them from `ChatPage.module.css`. Keep `.answerRegion` (line 56) in `ChatPage.module.css`. The new file starts with:

```css
/* A turn's answer and its Sources line (DESIGN.md → Chat). */
```

followed by the moved rules, unchanged.

- [ ] **Step 3: Create `Answer.tsx`**

```tsx
import { FileText } from "lucide-react";
import { useId } from "react";

import { formatCitation, type ChatCitation } from "../../api/chat";
import styles from "./Answer.module.css";

type Props = {
  /** The answer as the model wrote it: always rendered as text. */
  text: string;
  citations: ChatCitation[];
  /** The panel's Show citations switch. */
  showCitations: boolean;
  /** Documents the conversation's list marks deleted. */
  deletedIds: ReadonlySet<string>;
  /** This turn's chunk whose passage is open beside the conversation; null when none of its sources is. */
  shownChunkId: string | null;
  /** Opens the citation's document beside the conversation; focus goes back to `from` when it closes. */
  onOpenCitation: (citation: ChatCitation, from: HTMLElement) => void;
};

// A turn's answer and its Sources line (DESIGN.md → Chat). A declined turn has neither.
export function Answer({ text, citations, showCitations, deletedIds, shownChunkId, onOpenCitation }: Props) {
  const listId = useId();
  return (
    <>
      {text && <p className={styles.answer}>{text}</p>}
      {showCitations && citations.length > 0 && (
        <div className={styles.sources}>
          <span className={styles.sourcesLabel} id={listId}>
            Sources
          </span>
          {/* Each source shows the [n] the answer's text uses for it; an answer may cite [2] without [1]. */}
          <ul className={styles.sourceList} aria-labelledby={listId}>
            {citations.map((c) => {
              // A citation to a deleted document keeps its [n] but loses the title and page.
              if (c.deleted || deletedIds.has(c.document_id)) {
                return (
                  <li key={c.chunk_id}>
                    <span className={`${styles.source} ${styles.sourceDeleted}`} title="Deleted document">
                      <FileText className={styles.sourceIcon} strokeWidth={1.5} aria-hidden="true" />
                      <span className={styles.sourceMarker}>[{c.n}]</span> Deleted document
                    </span>
                  </li>
                );
              }
              // The chip whose passage is open beside the conversation; a panel row's open clears it.
              const isShown = shownChunkId === c.chunk_id;
              const pageText = c.page === null ? "page unavailable" : `p. ${c.page}`;
              const state = isShown ? "Shown beside the conversation" : "Open beside the conversation";
              return (
                <li key={c.chunk_id}>
                  <button
                    type="button"
                    className={isShown ? `${styles.source} ${styles.sourceShown}` : styles.source}
                    title={formatCitation(c)}
                    aria-label={`${c.document_title}, ${pageText}${c.archived ? ", archived" : ""}. ${state}`}
                    aria-current={isShown ? "true" : undefined}
                    data-chunk-id={c.chunk_id}
                    onClick={(event) => onOpenCitation(c, event.currentTarget)}
                  >
                    <FileText className={styles.sourceIcon} strokeWidth={1.5} aria-hidden="true" />
                    <span className={styles.sourceMarker}>[{c.n}]</span>{" "}
                    <span className={styles.sourceTitle}>{c.document_title}</span>{" "}
                    <span className={styles.sourcePage}>· {pageText}</span>
                    {/* An archived document's citation still opens it, marked as archived. */}
                    {c.archived && <span className={styles.sourceBadge}>Archived</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </>
  );
}
```

- [ ] **Step 4: Use `Answer` in `ChatPage.tsx`**

1. Add `import { Answer } from "./Answer";` on the line directly before `import styles from "./ChatPage.module.css";` (the `./` imports are alphabetical by path).
2. Remove `formatCitation` from the `../../api/chat` import; remove `useId` from the `react` import; remove `const sourcesId = useId();` (line 197). Keep `FileText` (the starting-document notice uses it).
3. In the `turns.map` callback, remove `const listId = …`.
4. Replace the final branch `t.answer && <p className={styles.answer}>{t.answer}</p>` **and** the whole following block `{t.decline === null && showCitations && t.citations.length > 0 && ( <div className={styles.sources}> … </div> )}` with:

```tsx
                      ) : (
                        <Answer
                          text={t.answer}
                          citations={t.citations}
                          showCitations={showCitations}
                          deletedIds={deletedIds}
                          shownChunkId={viewer?.turn === index ? (viewer.chunkId ?? null) : null}
                          onOpenCitation={(c, from) => openCitation(c, index, from)}
                        />
                      )}
```

The `{last && problem && …}` block stays after it, unchanged. The Sources line was shown only when `t.decline === null`; it now lives in the non-decline branch, which is the same condition.

5. Move the comment `// A citation to a deleted document keeps its [n] but loses the title and page: references read "Deleted document".` above `const deletedIds` as it is (it still describes `deletedIds`).

- [ ] **Step 5: Run the chat tests**

Run: `npx vitest run src/features/chat`
Expected: the same tests pass as in Step 1.

- [ ] **Step 6: Type check and build**

Run: `npm run build`
Expected: exits 0.

- [ ] **Step 7: Commit**

```bash
git add web/src/features/chat/Answer.tsx web/src/features/chat/Answer.module.css web/src/features/chat/ChatPage.tsx web/src/features/chat/ChatPage.module.css
git commit -m "Move a turn's answer and Sources line into their own component" -m "The chat page is about 900 lines and #211 and #213 also change it; the inline citation markers (#215) go into this component." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Parse citation markers out of the answer text

**Files:**
- Create: `web/src/features/chat/citationMarkers.ts`
- Test: `web/src/features/chat/citationMarkers.test.ts`

**Interfaces:**
- Produces:

```ts
/** A run of the answer's text; `n` is set when the run is one marker number a source may link. */
export type Piece = { text: string; n?: number };
export function splitMarkers(text: string): Piece[];
```

Contract: the pieces' `text` joined in order equals the input. A single marker `[2]` is one piece `{ text: "[2]", n: 2 }`. In a group, each number is its own piece `{ text: "1", n: 1 }` and the brackets, separators, and spaces are text pieces. Adjacent text pieces may or may not be merged (tests compare with merged text where noted below, so merge them).

- [ ] **Step 1: Write the failing tests**

```ts
import { describe, expect, it } from "vitest";

import { splitMarkers } from "./citationMarkers";

const joined = (text: string) =>
  splitMarkers(text)
    .map((p) => p.text)
    .join("");

describe("splitMarkers", () => {
  it("keeps text without markers as one piece", () => {
    expect(splitMarkers("No sources here.")).toEqual([{ text: "No sources here." }]);
  });

  it("makes a single marker one piece, brackets included", () => {
    expect(splitMarkers("It weighs tokens [1].")).toEqual([{ text: "It weighs tokens " }, { text: "[1]", n: 1 }, { text: "." }]);
  });

  it("splits a group into one piece per number", () => {
    expect(splitMarkers("A [1, 2] B")).toEqual([
      { text: "A [" },
      { text: "1", n: 1 },
      { text: ", " },
      { text: "2", n: 2 },
      { text: "] B" },
    ]);
  });

  it("reads ranges with a hyphen or an en dash, linking the numbers shown", () => {
    expect(splitMarkers("[1-3]")).toEqual([{ text: "[" }, { text: "1", n: 1 }, { text: "-" }, { text: "3", n: 3 }, { text: "]" }]);
    expect(splitMarkers("[1 – 3]")).toEqual([
      { text: "[" },
      { text: "1", n: 1 },
      { text: " – " },
      { text: "3", n: 3 },
      { text: "]" },
    ]);
  });

  it("reads adjacent markers separately", () => {
    expect(splitMarkers("[1][2]")).toEqual([
      { text: "[1]", n: 1 },
      { text: "[2]", n: 2 },
    ]);
  });

  it("reads a leading zero as the backend does", () => {
    expect(splitMarkers("[01]")).toEqual([{ text: "[01]", n: 1 }]);
  });

  it("leaves brackets that aren't the backend's marker forms as text", () => {
    for (const text of ["[a]", "[]", "[1,]", "[ 1]", "[1 ]", "[1;2]", "[-1]"]) {
      expect(splitMarkers(text)).toEqual([{ text }]);
    }
  });

  it("keeps the text unchanged when the pieces are joined", () => {
    const text = "x[0] then [2, 4-5] and [3–1] <b>[1]</b>\n[9]";
    expect(joined(text)).toBe(text);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/features/chat/citationMarkers.test.ts`
Expected: FAIL, cannot resolve `./citationMarkers`.

- [ ] **Step 3: Implement `citationMarkers.ts`**

```ts
/** A run of the answer's text; `n` is set when the run is one marker number a source may link. */
export type Piece = { text: string; n?: number };

// The backend's marker forms (tutoring/application/answer.py): [1], [1, 2], [1-3], and [1–3] with an en dash.
const MARKER = /\[(\d+(?:\s*[-–,]\s*\d+)*)\]/g;
const NUMBER = /\d+/g;

function push(pieces: Piece[], text: string) {
  if (!text) return;
  const last = pieces[pieces.length - 1];
  if (last && last.n === undefined) last.text += text;
  else pieces.push({ text });
}

// Cuts the answer into text and marker numbers, keeping every character. A single marker is one piece with its
// brackets; in a group each number shown is its own piece, so a range's middle numbers get none.
export function splitMarkers(text: string): Piece[] {
  const pieces: Piece[] = [];
  let at = 0;
  for (const match of text.matchAll(MARKER)) {
    push(pieces, text.slice(at, match.index));
    const group = match[1]!;
    const numbers = [...group.matchAll(NUMBER)];
    if (numbers.length === 1) {
      pieces.push({ text: match[0], n: Number(group) });
    } else {
      let inner = 0;
      push(pieces, "[");
      for (const number of numbers) {
        push(pieces, group.slice(inner, number.index));
        pieces.push({ text: number[0], n: Number(number[0]) });
        inner = number.index + number[0].length;
      }
      push(pieces, "]");
    }
    at = match.index + match[0].length;
  }
  push(pieces, text.slice(at));
  return pieces;
}
```

Note: the "]" after a group goes through `push`, so it merges with the text that follows (the test "splits a group" expects `"] B"`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run src/features/chat/citationMarkers.test.ts`
Expected: PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/features/chat/citationMarkers.ts web/src/features/chat/citationMarkers.test.ts
git commit -m "Read citation markers in an answer's text as the backend does" -m "The inline markers (#215) link each number the answer shows; the forms must match the ones the backend reads when it picks the cited chunks." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Markers in the answer open their passage, with docs

**Files:**
- Modify: `web/src/features/chat/Answer.tsx`
- Modify: `web/src/features/chat/Answer.module.css`
- Create: `web/src/features/chat/Answer.test.tsx`
- Modify: `web/src/features/chat/ChatPage.test.tsx`
- Modify: `DESIGN.md` (→ Chat paragraph at line 104, Split view paragraph at line 110)
- Modify: `sdd/prd.md` (status line at line 5, a new "Changes from v2.45" row above line 6, US-4b at line 240)
- Modify: `sdd/design/brief.md` (Feedback log: a new last row after round 17)

**Interfaces:**
- Consumes: `Answer` props from Task 1 (unchanged); `splitMarkers`, `Piece` from Task 2.
- Produces: marker buttons with class `styles.marker`, `aria-label`/`title` = `Source <n>: <formatCitation(c)>[, archived]`, `data-chunk-id`, `aria-current="true"` when shown. A deleted document's marker is `<span title="Deleted document">`.

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/chat/Answer.test.tsx`:

```tsx
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { ChatCitation } from "../../api/chat";
import { Answer } from "./Answer";

const cite = (n: number, over: Partial<ChatCitation> = {}): ChatCitation => ({
  n,
  chunk_id: `c${n}`,
  document_id: `d${n}`,
  document_title: `Doc ${n}`,
  page: n + 1,
  ...over,
});

function renderAnswer(props: Partial<ComponentProps<typeof Answer>> = {}) {
  const onOpenCitation = vi.fn();
  render(
    <Answer
      text="It weighs tokens [1]."
      citations={[cite(1)]}
      showCitations
      deletedIds={new Set()}
      shownChunkId={null}
      onOpenCitation={onOpenCitation}
      {...props}
    />,
  );
  return onOpenCitation;
}

const paragraph = () => document.querySelector("p")!;
const markers = () => within(paragraph()).queryAllByRole("button");

describe("Answer", () => {
  it("links a marker to its source and keeps the text as written", async () => {
    const onOpen = renderAnswer();
    const marker = within(paragraph()).getByRole("button", { name: "Source 1: Doc 1, p. 2" });
    expect(marker).toHaveTextContent("[1]");
    expect(marker).toHaveAttribute("title", "Source 1: Doc 1, p. 2");
    expect(paragraph()).toHaveTextContent("It weighs tokens [1].");
    await userEvent.click(marker);
    expect(onOpen).toHaveBeenCalledWith(cite(1), marker);
  });

  it("is reachable by keyboard and opens with Enter", async () => {
    const onOpen = renderAnswer();
    await userEvent.tab();
    expect(within(paragraph()).getByRole("button")).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("links each number of a group", () => {
    renderAnswer({ text: "Both [1, 2].", citations: [cite(1), cite(2)] });
    expect(markers().map((m) => m.textContent)).toEqual(["1", "2"]);
    expect(markers().map((m) => m.getAttribute("aria-label"))).toEqual(["Source 1: Doc 1, p. 2", "Source 2: Doc 2, p. 3"]);
    expect(paragraph()).toHaveTextContent("Both [1, 2].");
  });

  it("links the numbers a range shows, with a hyphen or an en dash", () => {
    renderAnswer({ text: "All [1-3] and [1–3].", citations: [cite(1), cite(2), cite(3)] });
    expect(markers().map((m) => m.textContent)).toEqual(["1", "3", "1", "3"]);
  });

  it("keeps a number with no source as text", () => {
    renderAnswer({ text: "See [2] and [7] and x[0] and [1, 7].", citations: [cite(2), cite(1)] });
    expect(markers().map((m) => m.getAttribute("aria-label"))).toEqual(["Source 2: Doc 2, p. 3", "Source 1: Doc 1, p. 2"]);
  });

  it("says page unavailable for a citation without a page", () => {
    renderAnswer({ citations: [cite(1, { page: null })] });
    expect(within(paragraph()).getByRole("button", { name: "Source 1: Doc 1, page unavailable" })).toBeInTheDocument();
  });

  it("shows a deleted document's marker as text with Deleted document", () => {
    renderAnswer({ text: "A [1] B [2].", citations: [cite(1, { deleted: true }), cite(2)], deletedIds: new Set(["d2"]) });
    expect(markers()).toHaveLength(0);
    expect(within(paragraph()).getAllByTitle("Deleted document").map((m) => m.textContent)).toEqual(["[1]", "[2]"]);
  });

  it("opens an archived document's marker, saying it is archived", () => {
    renderAnswer({ citations: [cite(1, { archived: true })] });
    expect(within(paragraph()).getByRole("button", { name: "Source 1: Doc 1, p. 2, archived" })).toBeInTheDocument();
  });

  it("marks the shown passage's markers as current", () => {
    renderAnswer({ text: "A [1] B [2] C [1].", citations: [cite(1), cite(2)], shownChunkId: "c1" });
    expect(markers().map((m) => m.getAttribute("aria-current"))).toEqual(["true", null, "true"]);
  });

  it("keeps markers as text until the citations arrive", () => {
    renderAnswer({ citations: [] });
    expect(markers()).toHaveLength(0);
    expect(paragraph()).toHaveTextContent("It weighs tokens [1].");
  });

  it("keeps markers as text with Show citations off", () => {
    renderAnswer({ showCitations: false });
    expect(markers()).toHaveLength(0);
    expect(screen.queryByRole("list", { name: "Sources" })).not.toBeInTheDocument();
  });

  it("never renders the answer as HTML", () => {
    const text = "<b>bold</b> [1] <img src=x onerror=alert(1)>";
    renderAnswer({ text });
    expect(paragraph().querySelector("b, img")).toBeNull();
    expect(paragraph()).toHaveTextContent(text);
    expect(markers()).toHaveLength(1);
  });
});
```

In `web/src/features/chat/ChatPage.test.tsx`:

(a) Add after `const askButton = …` (line 68):

```ts
// An answer's paragraph by its whole text: once its citations arrive, its [n] markers are buttons inside it.
const answerText = (text: string) => (_: string, element: Element | null) => element?.tagName === "P" && element.textContent === text;
```

and replace every `ByText("It weighs tokens [1].")` in the file with `ByText(answerText("It weighs tokens [1]."))` (covers `findByText`, `getByText`, `getAllByText`, `queryByText`):

```bash
sed -i 's/ByText("It weighs tokens \[1\]\.")/ByText(answerText("It weighs tokens [1]."))/g' web/src/features/chat/ChatPage.test.tsx
```

(b) Inside `describe("document viewer", …)`, after the `describe("Sources chips", …)` block (it ends at line 987), add:

```tsx
    describe("citation markers", () => {
      const cited = (text = "It weighs tokens [1] and keys [2], see [3].") =>
        events(
          { type: "thread", thread_id: "t1" },
          { type: "delta", text },
          {
            type: "citations",
            citations: [
              { n: 1, chunk_id: "c1", document_id: "d1", document_title: "ReAct", page: 2 },
              { n: 2, chunk_id: "c2", document_id: "d1", document_title: "ReAct", page: 3 },
              { n: 3, chunk_id: "c3", document_id: "d2", document_title: "PPO", page: 1 },
            ],
          },
          { type: "done" },
        );
      const marker = (n: number) => screen.findByRole("button", { name: new RegExp(`^Source ${n}: `) });
      const close = () => fireEvent.keyDown(within(pane("ReAct")!).getByRole("heading", { level: 2, name: "ReAct" }), { key: "Escape" });

      async function cite(text?: string) {
        const viewerDeps = fakeViewerDeps();
        await answer({ ask: vi.fn().mockImplementation(() => cited(text)), viewerDeps });
        return viewerDeps;
      }

      it("opens the document beside the conversation at the cited passage and marks its chip shown", async () => {
        const deps = await cite();
        const first = await marker(1);
        expect(first).toHaveAccessibleName("Source 1: ReAct, p. 2");
        await userEvent.click(first);
        expect(await screen.findByText("p. 2 / 3", {}, { timeout: 3000 })).toBeInTheDocument();
        expect(pane("ReAct")).toBeInTheDocument();
        expect(deps.loadChunk).toHaveBeenCalledWith("c1");
        expect(first).toHaveAttribute("aria-current", "true");
        const chip = within(screen.getByRole("list", { name: "Sources" })).getByRole("button", { name: /^ReAct, p\. 2\./ });
        expect(chip).toHaveAccessibleName(/Shown beside the conversation$/);
        expect(chip).toHaveAttribute("aria-current", "true");
      });

      it("swaps the document in place when another marker is clicked", async () => {
        await cite();
        const react = await marker(1);
        await userEvent.click(react);
        await screen.findByText("p. 2 / 3", {}, { timeout: 3000 });
        const ppo = await marker(3);
        await userEvent.click(ppo);
        expect(await screen.findByRole("region", { name: "PPO" })).toBeInTheDocument();
        expect(pane("ReAct")).not.toBeInTheDocument();
        expect(react).not.toHaveAttribute("aria-current");
        expect(ppo).toHaveAttribute("aria-current", "true");
      });

      it("returns focus to the marker that opened it, on Escape and on Close", async () => {
        await cite("Twice [1] and again [1].");
        const [, second] = await screen.findAllByRole("button", { name: /^Source 1: / });
        await userEvent.click(second!);
        await screen.findByText("p. 2 / 3", {}, { timeout: 3000 });
        close();
        expect(pane("ReAct")).not.toBeInTheDocument();
        await waitFor(() => expect(second).toHaveFocus());

        await userEvent.click(second!);
        await screen.findByText("p. 2 / 3", {}, { timeout: 3000 });
        await userEvent.click(within(pane("ReAct")!).getByRole("button", { name: "Close" }));
        await waitFor(() => expect(second).toHaveFocus());
      });

      it("keeps markers as text while the answer streams, linking them once the citations arrive", async () => {
        const live = controlledStream();
        renderChat({ ask: vi.fn(() => live.stream()), viewerDeps: fakeViewerDeps() });
        await userEvent.type(await question(), "How does ReAct work?");
        await userEvent.click(askButton());
        act(() => live.push({ type: "thread", thread_id: "t1" }));
        act(() => live.push({ type: "delta", text: "It weighs tokens [1]." }));
        expect(await screen.findByText(answerText("It weighs tokens [1]."))).toBeInTheDocument();
        expect(screen.queryByRole("button", { name: /^Source 1: / })).not.toBeInTheDocument();
        act(() =>
          live.push({ type: "citations", citations: [{ n: 1, chunk_id: "c1", document_id: "d1", document_title: "ReAct", page: 2 }] }),
        );
        expect(await marker(1)).toBeInTheDocument();
        act(() => live.push({ type: "done" }));
        act(() => live.push(null));
      });

      it("keeps markers as text with Show citations off", async () => {
        await cite();
        await marker(1);
        await userEvent.click(screen.getByRole("switch", { name: "Show citations" }));
        expect(screen.queryByRole("button", { name: /^Source \d: / })).not.toBeInTheDocument();
        expect(screen.getByText(answerText("It weighs tokens [1] and keys [2], see [3]."))).toBeInTheDocument();
      });
    });
```

If `act` pushes on `controlledStream` need `await act(async () => …)` to flush (check how existing tests in the file use `controlledStream`, e.g. `grep -n "controlledStream()" -A12 web/src/features/chat/ChatPage.test.tsx`, and copy their pattern exactly).

(c) Inside `describe("a conversation at its URL", …)`, after the test "an archived document's history citation says Archived and still opens" (ends at line 1356), add:

```tsx
    it("a history answer's marker opens its passage", async () => {
      const deps = fakeViewerDeps();
      renderChat({ loadConversation: conversation([cited({ document_title: "ReAct", page: 2 })]), viewerDeps: deps }, "/chat/t1");
      const marker = await screen.findByRole("button", { name: "Source 1: ReAct, p. 2" });
      await userEvent.click(marker);
      expect(await screen.findByText("p. 2 / 3", {}, { timeout: 3000 })).toBeInTheDocument();
      expect(deps.loadChunk).toHaveBeenCalledWith("c1");
      expect(marker).toHaveAttribute("aria-current", "true");
    });

    it("marks only the clicked turn's marker when two turns cite the same passage", async () => {
      const both = conversation([cited({ document_title: "ReAct", page: 2 }), cited({ document_title: "ReAct", page: 2 })]);
      renderChat({ loadConversation: both, viewerDeps: fakeViewerDeps() }, "/chat/t1");
      await screen.findAllByRole("button", { name: "Source 1: ReAct, p. 2" });
      const [first, second] = screen.getAllByRole("button", { name: "Source 1: ReAct, p. 2" });
      await userEvent.click(second!);
      expect(await screen.findByText("p. 2 / 3", {}, { timeout: 3000 })).toBeInTheDocument();
      expect(second).toHaveAttribute("aria-current", "true");
      expect(first).not.toHaveAttribute("aria-current");
    });

    it("a deleted document's history marker is text with Deleted document", async () => {
      renderChat({ loadConversation: conversation([cited({ document_title: "Deleted document", deleted: true })]) }, "/chat/t1");
      await screen.findByRole("list", { name: "Sources" });
      expect(screen.queryByRole("button", { name: /^Source 1: / })).not.toBeInTheDocument();
      const answer = screen.getByText(answerText("It weighs tokens [1]."));
      expect(within(answer).getByTitle("Deleted document")).toHaveTextContent("[1]");
    });

    it("an archived document's history marker still opens it", async () => {
      renderChat(
        { loadConversation: conversation([cited({ document_title: "ReAct", page: 2, archived: true })]), viewerDeps: fakeViewerDeps() },
        "/chat/t1",
      );
      await userEvent.click(await screen.findByRole("button", { name: "Source 1: ReAct, p. 2, archived" }));
      expect(await screen.findByRole("region", { name: "ReAct" })).toBeInTheDocument();
    });
```

- [ ] **Step 2: Run the tests to verify the new ones fail**

Run: `npx vitest run src/features/chat`
Expected: the new `Answer.test.tsx` tests that look for marker buttons FAIL ("Unable to find role button"); the tests "keeps markers as text …" and "never renders the answer as HTML" may already pass. The new ChatPage marker tests FAIL. Every pre-existing test still PASSES (the matcher change is safe before links exist).

- [ ] **Step 3: Render markers in `Answer.tsx`**

Add the import and replace the answer paragraph:

```tsx
import { splitMarkers, type Piece } from "./citationMarkers";
```

Inside `Answer`, before `return`:

```tsx
  // Markers link once the answer's citations have arrived (they follow its last words) and while citations are shown.
  const linked = showCitations && citations.length > 0;
  const byNumber = new Map(citations.map((c) => [c.n, c]));

  // A marker number with a source in this answer opens it, as its Sources chip does; any other piece stays text.
  function piece(p: Piece, index: number) {
    const c = p.n === undefined ? undefined : byNumber.get(p.n);
    if (!c) return p.text;
    if (c.deleted || deletedIds.has(c.document_id)) {
      return (
        <span key={index} title="Deleted document">
          {p.text}
        </span>
      );
    }
    const name = `Source ${c.n}: ${formatCitation(c)}${c.archived ? ", archived" : ""}`;
    return (
      <button
        key={index}
        type="button"
        className={styles.marker}
        title={name}
        aria-label={name}
        aria-current={shownChunkId === c.chunk_id ? "true" : undefined}
        data-chunk-id={c.chunk_id}
        onClick={(event) => onOpenCitation(c, event.currentTarget)}
      >
        {p.text}
      </button>
    );
  }
```

and the paragraph becomes:

```tsx
      {/* Text nodes only: the model's words are never read as HTML. */}
      {text && <p className={styles.answer}>{linked ? splitMarkers(text).map(piece) : text}</p>}
```

- [ ] **Step 4: Style the marker in `Answer.module.css`**

Append after `.answer`:

```css
/* An inline citation marker: a link to its source in the answer's text. Inline in a sentence, so the 24px target
   minimum doesn't apply (WCAG 2.5.8 inline exception). */
.marker {
  padding: 0; border: 0; border-radius: var(--r-sm); background: none;
  color: var(--accent-text); font: inherit; text-decoration: underline; text-underline-offset: 2px; cursor: pointer;
}
.marker:hover { text-decoration-thickness: 2px; }
.marker:focus-visible { outline: 2px solid var(--focus); outline-offset: 2px; }
/* Its passage is open beside the conversation, as for its chip (--accent-soft marks the selected item). */
.marker[aria-current="true"] { background: var(--accent-soft); }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `npx vitest run src/features/chat`
Expected: all PASS. If a pre-existing test fails because a `getByRole("button", { name: /…/ })` now also matches a marker, scope that query to the Sources list (`within(screen.getByRole("list", { name: "Sources" }))`) rather than changing the marker's name.

- [ ] **Step 6: Update `DESIGN.md`**

In `## Chat` (line 104), after the sentence ending `each opening the document viewer.` insert:

```markdown
Each `[n]` in the answer's text is also a link to its source: `--accent-text`, underlined, a `:focus-visible` ring, `--accent-soft` and `aria-current` while its passage is shown, and the accessible name and tooltip "Source 2: *title*, p. 3". `[1, 2]` and `[1–3]` link each number shown. A number with no source in that answer stays text, as does a deleted document's marker (tooltip "Deleted document"); markers stay text while the answer streams and while Show citations is off. Markers sit inside a sentence, so the 24px target minimum doesn't apply to them (WCAG 2.5.8 inline exception).
```

In `**Split view.**` (line 110): change `One click on a document in the panel or on a Sources chip opens` to `One click on a document in the panel, on a Sources chip, or on an answer's \`[n]\` marker opens`; change `Esc or Close returns focus to the chip or row that opened it; the chip whose passage is shown stays highlighted in the conversation. Another chip or row swaps the document in place.` to `Esc or Close returns focus to the chip, marker, or row that opened it; the chip and markers whose passage is shown stay highlighted in the conversation. Another chip, marker, or row swaps the document in place.`

- [ ] **Step 7: Update `sdd/prd.md`**

1. Status line (line 5): `Draft v2.45` → `Draft v2.46`.
2. Insert a new row directly above the `| **Changes from v2.44** |` row (line 6):

```markdown
| **Changes from v2.45** | Citation markers in an answer open their passage (#215, US-4b): each `[n]` in an answer's text, live or from history, is a citation the learner can select, the same as its Sources chip; `[1, 2]` and `[1–3]` give each number shown. Markers are plain text while the answer streams, while citations are hidden, for a number with no source in that answer, and for a deleted document. Client feedback; no design round shows it yet (design brief feedback log, round 18). |
```

3. In US-4b, after the bullet that starts `- *When* the learner opens a document from the list, *then* the **document viewer** shows its PDF from the first page.`, append to the end of that same bullet: ` Each citation marker in an answer's text (\`[2]\`, \`[1, 2]\`, \`[1–3]\`) is also a citation the learner can select, once the answer's citations have arrived and while citations are shown; a marker for a deleted document can't be selected.`

- [ ] **Step 8: Update `sdd/design/brief.md` Feedback log**

Append this row after the round 17 row (the last row of the `### Feedback log` table, just before the `---` and `## Appendix A`):

```markdown
| 18 (client, owner) | v0.11 | Client: every chunk an answer cites should be a link inside the answer text, opened from the sentence that relies on it, not only from the Sources line (#215). Takes up round 10's "no inline numbers in the answer text" later option; the agent already writes `[n]` markers. | Each `[n]` marker opens its passage as its Sources chip does; `[1, 2]` and `[1–3]` link each number shown; markers stay text while streaming, with citations off, and for a deleted document. A design addition made in code: no accepted round shows clickable markers (`DESIGN.md` → Chat, PRD v2.46 US-4b). | Code (#215); next round |
```

- [ ] **Step 9: Full web check**

Run (from `web/`): `npm test && npm run build`
Expected: all tests pass; build exits 0.

- [ ] **Step 10: Commit**

```bash
git add web/src/features/chat DESIGN.md sdd/prd.md sdd/design/brief.md
git commit -m "Open a citation's passage from its marker in the answer" -m "Client feedback (#215): the learner wants to open a cited chunk straight from the sentence that relies on it, not only from the Sources line. Markers link once the answer's citations arrive and stay text with citations off, for a deleted document, and for a number with no source. No accepted round shows this, so DESIGN.md, PRD US-4b (v2.46), and the brief's feedback log record it." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## After the tasks (controller)

- Check by hand in installed Chrome (`channel: "chrome"`) and the bundled Playwright Chromium: markers link, focus ring shows, Esc returns focus, light and dark themes.
- Open a PR into `main` that closes #215 and records the design addition (no accepted round shows clickable markers).

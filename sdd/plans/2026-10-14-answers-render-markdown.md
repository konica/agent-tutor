# Answers Render as Markdown Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chat renders each answer, live and from history, as Markdown (CommonMark + GFM) while every `[n]` citation marker keeps linking to its source.

**Architecture:** `Answer.tsx` renders the answer text with `react-markdown` + `remark-gfm` on their defaults. A small remark plugin (`remarkCitationMarkers.ts`) reuses `splitMarkers` to cut each marker in prose into a `span` with `data-marker`; a module-level `span` component turns those into the existing marker buttons through a React context, so component identities stay stable across renders (no remounts, focus survives). Model headings shift down to h3–h6 and tables get a scroll wrapper.

**Tech Stack:** React 19, TypeScript, Vite, Vitest + Testing Library, `react-markdown` 10, `remark-gfm` 4, CSS modules with DESIGN.md tokens.

**Spec:** GitHub issue #303 "Answers render as Markdown" (`gh issue view 303`). PRD §8 US-4; DESIGN.md → Chat. Hardening against untrusted output (raw HTML, images, link schemes, new tab) is **#307, out of scope here**.

## Global Constraints

- Dependencies: `react-markdown@^10.1.0` and `remark-gfm@^4.0.1` in `web/package.json` `dependencies` (already installed in the worktree, uncommitted). No `rehype-raw`, no other new packages.
- `react-markdown` defaults stay: raw HTML is escaped to text, images and links render as the library does (#307 changes that).
- Markers keep #215's rules: plain text while the answer streams (no citations yet), while Show citations is off, for a number with no source, and for a deleted document (tooltip "Deleted document").
- Markers inside inline code, fenced code, and link text stay literal text.
- Model headings render at h3 and below (`#` → h3, `##` → h4, `###` → h5, `####`–`######` → h6); the page has h1 (title) and h2 (panel headings).
- Styles use DESIGN.md tokens only (`--fs-*`, `--lh-*`, `--sp-*`, `--r-*`, `--font-mono`, `--surface-2`, `--border`, `--border-strong`, `--text-2`, `--accent-text`); prose stays `--fs-16` / `--lh-read`; quoted blocks are 13px with a 2px left rule; wide tables and code blocks scroll inside the answer, never the page.
- No backend, prompt, or API change.
- Comments follow the file's style: one sentence saying why, referencing DESIGN.md/PRD where relevant.
- Commits: imperative subject, body says why, ending with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Checks: `cd web && npm run build && npm test` must pass.

## Review Focus

1. **A marker button keeps its DOM node across re-renders** (e.g. clicking a hidden source's marker expands the Sources line): ChatPage returns focus to that node when the viewer closes, so a remount would drop focus. Pinned in Task 2, Step 1 ("keeps the same marker button after it expands the line").
2. **A marker inside link text** (`[see [1]](https://x.y)`) must not put a button inside an `<a>`. Pinned in Task 1, Step 1.
3. **A references line the model writes as `[1]: Doc 1, p. 2`** isn't a valid link definition (no URL), so it must stay visible with its marker linked. Pinned in Task 1, Step 1.
4. **A partial answer mid-stream** (`**open`, an unclosed fence) renders without throwing, its text visible. Pinned in Task 2, Step 1.
5. **A long code line or wide table at 360px** scrolls inside the answer, not the page. Pinned by CSS in Task 2, Step 3 and checked in the browser in Task 3, Step 6.

---

### Task 1: Remark plugin that marks citation markers

**Files:**
- Create: `web/src/features/chat/remarkCitationMarkers.ts`
- Test: `web/src/features/chat/remarkCitationMarkers.test.tsx`

**Interfaces:**
- Consumes: `splitMarkers(text: string): Piece[]` and `type Piece = { text: string; n?: number }` from `web/src/features/chat/citationMarkers.ts` (unchanged).
- Produces: `export function remarkCitationMarkers(): (tree: MdNode) => void`, a remark plugin. Each marker number in prose becomes a hast `span` element with property `dataMarker: number` (DOM attribute `data-marker="<n>"`) whose only child is the marker's text (`"[1]"` for a single marker, `"1"` for a number in a group). Everything else is unchanged.

- [ ] **Step 1: Write the failing test**

Create `web/src/features/chat/remarkCitationMarkers.test.tsx`:

```tsx
import { render } from "@testing-library/react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { describe, expect, it } from "vitest";

import { remarkCitationMarkers } from "./remarkCitationMarkers";

function renderMarkdown(text: string) {
  const { container } = render(<Markdown remarkPlugins={[remarkGfm, remarkCitationMarkers]}>{text}</Markdown>);
  return container;
}

const marks = (root: ParentNode) =>
  [...root.querySelectorAll("span[data-marker]")].map((s) => [s.getAttribute("data-marker"), s.textContent]);

describe("remarkCitationMarkers", () => {
  it("marks a single marker with its brackets and keeps the text", () => {
    const root = renderMarkdown("It weighs tokens [1].");
    expect(marks(root)).toEqual([["1", "[1]"]]);
    expect(root).toHaveTextContent("It weighs tokens [1].");
  });

  it("marks each number of a group or range", () => {
    const root = renderMarkdown("Both [1, 2] and [1–3].");
    expect(marks(root)).toEqual([["1", "1"], ["2", "2"], ["1", "1"], ["3", "3"]]);
    expect(root).toHaveTextContent("Both [1, 2] and [1–3].");
  });

  it("marks markers in emphasis, list items, headings, and table cells", () => {
    const root = renderMarkdown("**Bold [1]**\n\n- item [2]\n\n## Head [3]\n\n| a | b |\n|---|---|\n| cell [4] | x |");
    expect(marks(root).map(([n]) => n)).toEqual(["1", "2", "3", "4"]);
    expect(root.querySelector("strong span[data-marker]")).not.toBeNull();
    expect(root.querySelector("li span[data-marker]")).not.toBeNull();
    expect(root.querySelector("td span[data-marker]")).not.toBeNull();
  });

  it("leaves markers in inline code, fenced code, and link text as text", () => {
    const root = renderMarkdown("Use `x[1]` and [see [2]](https://example.com).\n\n```\nlist[3]\n```");
    expect(marks(root)).toEqual([]);
    expect(root.querySelector("code")).toHaveTextContent("x[1]");
    expect(root.querySelector("a")).toHaveTextContent("see [2]");
    expect(root.querySelector("pre")).toHaveTextContent("list[3]");
  });

  it("keeps a references line without a URL visible, with its marker", () => {
    const root = renderMarkdown("Sources:\n\n[1]: Doc 1, p. 2");
    expect(root).toHaveTextContent("[1]: Doc 1, p. 2");
    expect(marks(root)).toEqual([["1", "[1]"]]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/features/chat/remarkCitationMarkers.test.tsx`
Expected: FAIL, "Failed to resolve import ./remarkCitationMarkers".

- [ ] **Step 3: Write minimal implementation**

Create `web/src/features/chat/remarkCitationMarkers.ts`:

```ts
import { splitMarkers } from "./citationMarkers";

/** The part of an mdast node this plugin reads and writes. */
type MdNode = { type: string; value?: string; children?: MdNode[]; data?: Record<string, unknown> };

// Text inside a link stays text: a marker's button can't sit inside a link. Code is its own node type, never `text`.
const KEEP = new Set(["link", "linkReference"]);

function split(text: MdNode): MdNode[] {
  return splitMarkers(text.value ?? "").map((p) =>
    p.n === undefined
      ? { type: "text", value: p.text }
      : {
          type: "citationMarker",
          data: { hName: "span", hProperties: { dataMarker: p.n } },
          children: [{ type: "text", value: p.text }],
        },
  );
}

function walk(node: MdNode) {
  if (!node.children || KEEP.has(node.type)) return;
  node.children = node.children.flatMap((child) => {
    if (child.type === "text") return split(child);
    walk(child);
    return [child];
  });
}

// A remark plugin: each marker number in the answer's prose becomes a `span` with `data-marker`, which Answer renders as
// a link to its source (DESIGN.md → Chat). The rest of the text is kept as written. The tree is typed `object` so the
// plugin fits react-markdown's plugin list without importing unified's types.
export function remarkCitationMarkers() {
  return (tree: object) => walk(tree as MdNode);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd web && npx vitest run src/features/chat/remarkCitationMarkers.test.tsx`
Expected: PASS, 5 tests. Then `cd web && npx tsc -b` must report no errors in the new files (don't import `unified` or `mdast` types: they aren't direct dependencies).

- [ ] **Step 5: Commit**

```bash
git add web/package.json web/package-lock.json web/src/features/chat/remarkCitationMarkers.ts web/src/features/chat/remarkCitationMarkers.test.tsx
git commit -m "Mark citation markers in Markdown answers with a remark plugin (#303)" -m "Answers will render as Markdown; the plugin finds each [n] in the answer's prose so Answer can keep linking it to its source. Markers in code and link text stay text, since a button can't sit inside a link." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Answer renders Markdown

**Files:**
- Modify: `web/src/features/chat/Answer.tsx` (the `piece` function and the `<p className={styles.answer}>` render)
- Modify: `web/src/features/chat/Answer.module.css` (`.answer` and new Markdown element rules)
- Test: `web/src/features/chat/Answer.test.tsx`, `web/src/features/chat/ChatPage.test.tsx`

**Interfaces:**
- Consumes: `remarkCitationMarkers` from Task 1 (spans with hast property `dataMarker: number`, child text = the marker's text); `Piece` from `./citationMarkers`.
- Produces: `Answer` props unchanged. The answer renders inside `<div className={styles.answer}>`; a one-paragraph answer still has exactly one `<p>` (existing tests use `document.querySelector("p")`).

- [ ] **Step 1: Write the failing tests**

Append inside the top-level `describe("Answer", ...)` in `web/src/features/chat/Answer.test.tsx`, before its closing `});`:

```tsx
  describe("Markdown", () => {
    const answer = () => paragraph().parentElement!;

    it("renders emphasis, lists, code, quotes, strikethrough, and links", () => {
      renderAnswer({
        text: "**Bold** and *italic* and ~~old~~ and `code` and [site](https://example.com).\n\n- one\n- two\n\n1. first\n\n> quoted\n\n```\nconst x = 1;\n```",
      });
      const root = answer();
      expect(root.querySelector("strong")).toHaveTextContent("Bold");
      expect(root.querySelector("em")).toHaveTextContent("italic");
      expect(root.querySelector("del")).toHaveTextContent("old");
      expect(root.querySelector("p code")).toHaveTextContent("code");
      expect(root.querySelector("a")).toHaveAttribute("href", "https://example.com");
      expect(within(root).getAllByRole("list")).toHaveLength(2);
      expect(root.querySelector("blockquote")).toHaveTextContent("quoted");
      expect(root.querySelector("pre code")).toHaveTextContent("const x = 1;");
    });

    it("renders the model's headings below the page's", () => {
      renderAnswer({ text: "# One\n\n## Two\n\n### Three\n\n#### Four\n\nBody [1]." });
      expect(screen.getAllByRole("heading").map((h) => [h.tagName, h.textContent])).toEqual([
        ["H3", "One"],
        ["H4", "Two"],
        ["H5", "Three"],
        ["H6", "Four"],
      ]);
    });

    it("puts a table in a scroll box and links its markers", () => {
      renderAnswer({ text: "| Term | Meaning |\n|---|---|\n| Attention | Weighs tokens [1] |" });
      const table = screen.getByRole("table");
      expect(table.parentElement).toHaveClass(/tableScroll/);
      expect(within(table).getByRole("button", { name: "Source 1: Doc 1, p. 2" })).toBeInTheDocument();
    });

    it("links markers in list items and headings, not in code", () => {
      renderAnswer({ text: "## Why [1]\n\n- because [1]\n\nSee `x[1]`.", citations: [cite(1)] });
      expect(screen.getAllByRole("button", { name: "Source 1: Doc 1, p. 2" })).toHaveLength(2);
      expect(screen.getByText("x[1]").tagName).toBe("CODE");
    });

    it("renders a partial answer mid-stream", () => {
      renderAnswer({ text: "It **weighs\n\n```\nconst x", citations: [] });
      expect(answer()).toHaveTextContent("It **weighs");
      expect(document.querySelector("pre")).toHaveTextContent("const x");
    });

    it("keeps the same marker button after it expands the line", async () => {
      const five = [cite(2), cite(1), cite(3), cite(5), cite(4)];
      renderAnswer({ text: "A [2] B [4].", citations: five });
      const marker = screen.getByRole("button", { name: "Source 4: Doc 4, p. 5" });
      await userEvent.click(marker);
      expect(screen.getByRole("button", { name: /^Show less$/ })).toBeInTheDocument();
      // ChatPage gives focus back to this node when the document closes, so it must not be remounted.
      expect(marker.isConnected).toBe(true);
    });
  });
```

Add to `web/src/features/chat/ChatPage.test.tsx`, right after the test "shows a generic message when the stream ends without done or error, keeping the partial answer" (same `describe`, same helpers):

```tsx
  it("renders the streamed answer as Markdown", async () => {
    const ask = vi.fn(() =>
      events({ type: "thread", thread_id: "t1", run_id: "r1" }, { type: "delta", text: "It **weighs** tokens" }),
    );
    renderChat({ ask });
    await userEvent.type(await question(), "What is attention?");
    await userEvent.click(askButton());
    expect((await screen.findByText("weighs")).tagName).toBe("STRONG");
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd web && npx vitest run src/features/chat/Answer.test.tsx src/features/chat/ChatPage.test.tsx`
Expected: FAIL in the new tests (no `strong`/`h3`/`table` elements; raw `**` shown). The "keeps the same marker button" test may pass already; that's fine, it guards the refactor.

- [ ] **Step 3: Implement**

In `web/src/features/chat/Answer.tsx`:

1. Replace the imports with:

```tsx
import { FileText } from "lucide-react";
import { createContext, useContext, useId, useState, type ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { formatCitation, type ChatCitation } from "../../api/chat";
import { Button } from "../../components/Button/Button";
import styles from "./Answer.module.css";
import type { Piece } from "./citationMarkers";
import { remarkCitationMarkers } from "./remarkCitationMarkers";
```

2. Change the `text` prop's doc comment to `/** The answer as the model wrote it, rendered as Markdown. */`.

3. Add, after `const COLLAPSED = 3;`:

```tsx
// Renders one marker piece; each Answer provides its own. Read through context so the Markdown components below keep
// one identity: new component functions on every render would remount the answer, and a marker that opened the viewer
// would lose the focus ChatPage gives back to it.
const MarkerContext = createContext<(p: Piece) => ReactNode>((p) => p.text);

function Marker({ n, children }: { n: number; children: ReactNode }) {
  return useContext(MarkerContext)({ text: String(children), n });
}

const remarkPlugins = [remarkGfm, remarkCitationMarkers];

// The model's headings sit under the page's h1 (title) and h2 (panel headings).
const components: Components = {
  h1: ({ node: _node, ...props }) => <h3 {...props} />,
  h2: ({ node: _node, ...props }) => <h4 {...props} />,
  h3: ({ node: _node, ...props }) => <h5 {...props} />,
  h4: ({ node: _node, ...props }) => <h6 {...props} />,
  h5: ({ node: _node, ...props }) => <h6 {...props} />,
  h6: ({ node: _node, ...props }) => <h6 {...props} />,
  // A wide table scrolls inside the answer, not the page.
  table: ({ node: _node, ...props }) => (
    <div className={styles.tableScroll}>
      <table {...props} />
    </div>
  ),
  // remarkCitationMarkers' spans; the answer's own HTML never reaches here (react-markdown shows it as text).
  span: ({ node, ...props }) => {
    const n = node?.properties?.dataMarker;
    return typeof n === "number" ? <Marker n={n}>{props.children}</Marker> : <span {...props} />;
  },
};
```

The `node: _node` destructuring stops react-markdown's `node` prop reaching the DOM. If `tsc` reports `_node` as unused, write each as `({ node, ...props }) => { void node; return <h3 {...props} />; }` instead.

4. Replace the `piece` function (signature `function piece(p: Piece, index: number)`) with one that takes no index and has no `key`s, keeping its body otherwise identical:

```tsx
  // A marker number with a source in this answer opens it, as its Sources chip does; any other marker stays text.
  // Markers render even while they stay text, so toggling citations keeps the live answer's text nodes.
  function marker(p: Piece): ReactNode {
    const c = !linked || p.n === undefined ? undefined : byNumber.get(p.n);
    if (!c) return p.text;
    if (c.deleted || deletedIds.has(c.document_id)) return <span title="Deleted document">{p.text}</span>;
    const name = `Source ${c.n}: ${formatCitation(c)}${c.archived ? ", archived" : ""}`;
    return (
      <button
        type="button"
        className={styles.marker}
        title={name}
        aria-label={name}
        aria-current={shownChunkId === c.chunk_id ? "true" : undefined}
        data-chunk-id={c.chunk_id}
        onClick={(event) => {
          // A hidden source's chip shows, so the learner sees which one is open.
          if (citations.indexOf(c) >= COLLAPSED) setExpandedFor(citations);
          onOpenCitation(c, event.currentTarget);
        }}
      >
        {p.text}
      </button>
    );
  }
```

Note: `<span title="Deleted document">` must not be turned back into a marker: it's rendered by `Marker`, not by the Markdown `span` component, so it isn't.

5. Replace the answer render:

```tsx
      {/* Text nodes only: the model's words are never read as HTML. */}
      {text && <p className={styles.answer}>{splitMarkers(text).map(piece)}</p>}
```

with:

```tsx
      {/* Markdown (DESIGN.md → Chat); react-markdown shows any HTML in the model's words as text. */}
      {text && (
        <div className={styles.answer}>
          <MarkerContext.Provider value={marker}>
            <Markdown remarkPlugins={remarkPlugins} components={components}>
              {text}
            </Markdown>
          </MarkerContext.Provider>
        </div>
      )}
```

6. Remove the now-unused `splitMarkers` import (it's replaced by `type Piece` above).

In `web/src/features/chat/Answer.module.css`, replace the `.answer` rule (and its comment) with:

```css
/* The tutor's words, rendered as Markdown: prose never smaller than --fs-16 (DESIGN.md → Density). min-width: 0 lets
   a wide table or code block scroll inside the answer instead of widening the page. */
.answer {
  max-width: var(--chat-w); min-width: 0; color: var(--text);
  font-size: var(--fs-16); line-height: var(--lh-read); overflow-wrap: anywhere;
}
.answer > :first-child { margin-top: 0; }
.answer > :last-child { margin-bottom: 0; }
.answer p, .answer ul, .answer ol, .answer pre, .answer blockquote, .answer .tableScroll { margin: 0 0 var(--sp-3); }
.answer ul, .answer ol { padding-left: var(--sp-6); }
.answer li + li { margin-top: var(--sp-1); }
.answer li > p { margin: 0; }
/* The model's headings: h3 for its top level, the rest at prose size (DESIGN.md → Type). */
.answer h3, .answer h4, .answer h5, .answer h6 { margin: var(--sp-4) 0 var(--sp-2); font-size: var(--fs-16); font-weight: 650; line-height: var(--lh-head); }
.answer h3 { font-size: var(--fs-18); }
.answer code { padding: 0 var(--sp-1); border-radius: var(--r-sm); background: var(--surface-2); font-family: var(--font-mono); font-size: .875em; }
.answer pre { overflow-x: auto; padding: var(--sp-3); border-radius: var(--r-md); background: var(--surface-2); line-height: var(--lh-body); }
.answer pre code { padding: 0; background: none; font-size: var(--fs-13); white-space: pre; overflow-wrap: normal; }
/* Quoted material is set apart from the tutor's prose: DESIGN.md's quoted passage, 13px with a 2px left rule. */
.answer blockquote { padding-left: var(--sp-3); border-left: 2px solid var(--border-strong); color: var(--text-2); font-size: var(--fs-13); }
.tableScroll { max-width: 100%; overflow-x: auto; }
.answer table { border-collapse: collapse; font-size: var(--fs-14); overflow-wrap: normal; }
.answer th, .answer td { padding: var(--sp-1) var(--sp-2); border: 1px solid var(--border); text-align: left; vertical-align: top; }
.answer th { background: var(--surface-2); font-weight: 600; }
.answer hr { margin: var(--sp-4) 0; border: 0; border-top: 1px solid var(--border); }
.answer a { color: var(--accent-text); text-underline-offset: 2px; }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd web && npx vitest run src/features/chat`
Expected: PASS, all chat tests, including every pre-existing `Answer` test (they read the first `<p>`, which one-paragraph answers still have) and "never renders the answer as HTML".

Then: `cd web && npm run build`
Expected: no TypeScript errors.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/chat/Answer.tsx web/src/features/chat/Answer.module.css web/src/features/chat/Answer.test.tsx web/src/features/chat/ChatPage.test.tsx
git commit -m "Render answers as Markdown (#303)" -m "Product owner feedback: the model writes Markdown, and chat showed its asterisks, hashes, and pipes as text. Answers now render with react-markdown and remark-gfm, live and from history. Markers keep linking to their sources through a context, so the Markdown components keep one identity and a marker isn't remounted when the Sources line expands. Model headings sit below the page's h1 and h2; tables and code scroll inside the answer." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Docs and browser check

**Files:**
- Modify: `sdd/prd.md` (status line, new change row, US-4)
- Modify: `AGENTS.md` (PRD version in the sources-of-truth table)
- Modify: `DESIGN.md` (→ Chat paragraph, line starting "The tutor's words, the learner's words")
- Modify: `sdd/design/brief.md` (Feedback log: new row 24 after row 23)

**Interfaces:**
- Consumes: the behavior of Tasks 1–2.
- Produces: docs only.

- [ ] **Step 1: PRD status and change row**

In `sdd/prd.md`, change `Draft v2.60` to `Draft v2.61` in the **Status** row, and insert this row directly after the **Status** row (before `| **Changes from v2.59** |`):

```markdown
| **Changes from v2.60** | Answers render as Markdown (#303, US-4): each answer, live and from history, renders the model's Markdown (CommonMark and GFM: emphasis, lists, code, headings, quotes, tables, links) instead of plain text. Citation markers keep #215's rules; markers in code and link text stay text. The model's headings sit below the page's; wide tables and code scroll inside the answer. Hardening the rendered output (raw HTML, images, link schemes) is #307; #198 is closed as not planned. Product owner feedback; no design round shows it yet (design brief feedback log, round 24). |
```

- [ ] **Step 2: PRD US-4**

In `sdd/prd.md` under `**US-4 Ask a grounded question**`, append to the end of the first bullet (after "Selecting a citation opens the document viewer at that passage (US-4b)."):

```markdown
 The answer renders as Markdown (emphasis, lists, code, headings, quotes, tables, links), live as it streams and in a reopened conversation.
```

- [ ] **Step 3: AGENTS.md**

In `AGENTS.md`, change `` `sdd/prd.md` (v2.60) `` to `` `sdd/prd.md` (v2.61) ``.

- [ ] **Step 4: DESIGN.md → Chat**

In `DESIGN.md`, in the `## Chat` paragraph that begins "The tutor's words, the learner's words, quoted document text, and system notices", insert after its first sentence (ending "notices are centered dashed pills (the maximum warning uses `--info-soft`).") this sentence:

```markdown
The tutor's answer renders as Markdown at `--fs-16` / `--lh-read`: paragraphs and lists with `--sp-3` between blocks, the model's headings at h3 (18px) and below (16px, weight 650) so they never outrank the page, inline code and code blocks in `--font-mono` on `--surface-2` (blocks 13px, scrolling sideways), quotes as the quoted-passage block, and tables with 1px `--border` cells and a `--surface-2` header row that scroll inside the answer at narrow widths.
```

- [ ] **Step 5: Brief feedback log row 24**

In `sdd/design/brief.md`, insert after the row starting `| 23 (client, Claude, #216) |`:

```markdown
| 24 (owner, Claude, #303) | v0.11 | Product owner: the model's answers look like Markdown source; every agent renders Markdown so the learner can read the output effectively. | Built in code: answers render as Markdown with react-markdown and remark-gfm (emphasis, lists, code, headings at h3 and below, quotes as the quoted-passage block, tables that scroll inside the answer); `[n]` markers keep linking to their sources. Hardening of rendered output is #307; #198 closed as not planned (`DESIGN.md` → Chat, PRD v2.61 US-4). Pending the owner; a design round should draw a formatted answer in `chat-answer-citations`. | Code (#303); next round |
```

- [ ] **Step 6: Browser check (controller, not committed)**

Render a sample answer in the installed Chrome (`channel: "chrome"`, see memory "Verify web fixes in installed Chrome"), light and dark, at 1280px and 360px wide, with a heading, a list, a code block with a 200-character line, a 5-column table, a quote, and markers. Use a scratch Vite entry that renders `Answer` with that text and fake citations, screenshot it with Playwright, then delete the scratch files. Expected: formatting visible, markers styled as links, table and code scroll inside the answer at 360px, no horizontal page scroll.

- [ ] **Step 7: Full checks and commit**

Run: `cd web && npm run build && npm test`
Expected: PASS.

```bash
git add sdd/prd.md AGENTS.md DESIGN.md sdd/design/brief.md
git commit -m "Record Markdown answers in the PRD, DESIGN.md, and the brief (#303)" -m "A product behavior change updates the PRD in the same PR (v2.61, US-4). No accepted design round shows formatted answers, so DESIGN.md → Chat and the brief's feedback log record the addition." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

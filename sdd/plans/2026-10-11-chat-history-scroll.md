# Chat History Scrolls Like a Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The chat's messages pane manages its scroll position like a chat: asking scrolls the question into view, a streaming answer is followed only while the learner is at the bottom, "Jump to latest" returns them there, and a reopened conversation lands on its newest turn.

**Architecture:** One hook, `useChatScroll`, owns the messages pane's scroll: it tracks whether the learner is *following* (at or near the bottom), sticks to the bottom after content renders or the pane resizes while following, and exposes `toLatest()` (follow again and scroll down, smoothly unless reduced motion) and `land()` (follow from the bottom, instantly, for a conversation that starts over). `ChatPage` attaches it to `.messages`, calls `land()` in `reset()` and `toLatest()` when asking, and renders a floating "Jump to latest" button above the composer while the learner is away. When not following, the hook never touches `scrollTop`; the browser's scroll anchoring keeps the pane in place when the split view reflows it.

**Tech Stack:** React 19, TypeScript, CSS modules, Vitest + Testing Library + jsdom (no `Element.scrollTo`, no `ResizeObserver`, `scrollTop` is a plain stored property).

**Spec:** GitHub issue #211 "Chat history scrolls like a conversation" (parent #23, US-13 "open with history"); `DESIGN.md` → Chat.

## Global Constraints

- Visible copy, verbatim: button text and accessible name **"Jump to latest"**.
- Scrolling is instant under `prefers-reduced-motion: reduce`; when `window.matchMedia` is missing (jsdom), treat it as reduced (instant).
- Only the newest turn's answer region carries `aria-live="polite"`; the Jump button and the scroll code add no live region.
- Release 1 loads the whole history: no "load earlier" paging.
- Icons: `lucide-react`, `strokeWidth={1.5}`, `aria-hidden`. Use the shared `Button` (`web/src/components/Button/Button.tsx`); never paste prototype CSS.
- Match the surrounding code: short "why" comments, no semicolon-free style changes, CSS one-line rules like `ChatPage.module.css`.
- Checks: `cd web && npm test && npm run build`.

## Review Focus

1. **Scrolling down without reaching the bottom** must not resume the follow; only reaching near the bottom (≤ 40px) does → hook test "scrolling down short of the bottom keeps the pane still".
2. **The pane shrinking while following** (the split view opens, the composer grows) must keep the newest text in view → hook test with a fake `ResizeObserver`.
3. **Activating Jump to latest by keyboard** removes the focused button; focus must land somewhere sensible (the question box, or the messages pane while answering) → page tests for both.
4. **Switching conversations after scrolling up** must land the new one on its newest turn, not keep the old "away" state → page test "reopening lands on the newest turn" plus hook test for `land()`.
5. **A new thread asked while scrolled up** (unlimited ask resets the turns) must show the question and hide Jump → covered by the page test "asking scrolls the question into view" (limited) and `land()` + `toLatest()` order in `answer()`.

---

### Task 1: `useChatScroll` hook

**Files:**
- Create: `web/src/features/chat/useChatScroll.ts`
- Test: `web/src/features/chat/useChatScroll.test.tsx`

**Interfaces:**
- Produces:
  ```ts
  export const NEAR_BOTTOM_PX = 40;
  export function useChatScroll(content: readonly unknown[]): {
    ref: (element: HTMLElement | null) => void; // callback ref for the scrolling element
    element: HTMLElement | null;                 // the attached element, for focus
    away: boolean;                               // the learner scrolled up away from the bottom
    toLatest: () => void;                        // follow again and scroll to the bottom (smooth unless reduced motion)
    land: () => void;                            // follow from the bottom, instantly (a conversation that starts over)
  };
  ```
  `content` is a fixed-length list of values whose change means "the pane's content may have grown" (ChatPage passes `[turns, answering, problem]`).

- [ ] **Step 1: Write the failing tests**

Create `web/src/features/chat/useChatScroll.test.tsx`:

```tsx
import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useChatScroll } from "./useChatScroll";

// A pane over a list of items, with the page's Jump button.
function Harness({ items, onLand }: { items: string[]; onLand?: (land: () => void) => void }) {
  const scroll = useChatScroll([items]);
  onLand?.(scroll.land);
  return (
    <>
      <div ref={scroll.ref} role="region" aria-label="Messages">
        <div>
          {items.map((text, i) => (
            <p key={i}>{text}</p>
          ))}
        </div>
      </div>
      {scroll.away && <button onClick={scroll.toLatest}>Jump to latest</button>}
    </>
  );
}

// The pane as the learner scrolls it: a `view`-px window over `content` px of messages.
function geometry(content = 2000, view = 600) {
  const g = { content, view };
  const isPane = (el: Element) => el.getAttribute("aria-label") === "Messages";
  vi.spyOn(Element.prototype, "clientHeight", "get").mockImplementation(function (this: Element) {
    return isPane(this) ? g.view : 0;
  });
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockImplementation(function (this: Element) {
    return isPane(this) ? g.content : 0;
  });
  return g;
}
const pane = () => screen.getByRole("region", { name: "Messages" });
function scrollTo(top: number) {
  pane().scrollTop = top;
  fireEvent.scroll(pane());
}
const jump = () => screen.queryByRole("button", { name: "Jump to latest" });
function motion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: reduce && query.includes("reduce"), media: query }));
}

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("useChatScroll", () => {
  it("starts at the bottom and follows content that grows while there", () => {
    const g = geometry();
    const { rerender } = render(<Harness items={["a"]} />);
    expect(pane().scrollTop).toBe(1400);
    g.content = 2400;
    rerender(<Harness items={["a", "b"]} />);
    expect(pane().scrollTop).toBe(1800);
    expect(jump()).toBeNull();
  });

  it("stops following once the learner scrolls up, and shows Jump to latest", () => {
    const g = geometry();
    const { rerender } = render(<Harness items={["a"]} />);
    scrollTo(500);
    expect(jump()).toBeInTheDocument();
    g.content = 2400;
    rerender(<Harness items={["a", "b"]} />);
    expect(pane().scrollTop).toBe(500);
  });

  it("scrolling down short of the bottom keeps the pane still", () => {
    const g = geometry();
    const { rerender } = render(<Harness items={["a"]} />);
    scrollTo(500);
    scrollTo(900); // 500px above the bottom
    g.content = 2400;
    rerender(<Harness items={["a", "b"]} />);
    expect(pane().scrollTop).toBe(900);
    expect(jump()).toBeInTheDocument();
  });

  it("resumes following once the learner scrolls back near the bottom", () => {
    const g = geometry();
    const { rerender } = render(<Harness items={["a"]} />);
    scrollTo(500);
    scrollTo(1370); // 30px above the bottom counts as there
    expect(jump()).toBeNull();
    g.content = 2400;
    rerender(<Harness items={["a", "b"]} />);
    expect(pane().scrollTop).toBe(1800);
  });

  it("Jump to latest scrolls smoothly to the bottom and hides", async () => {
    motion(false);
    geometry();
    const scrollToSpy = vi.fn(function (this: HTMLElement, options: ScrollToOptions) {
      this.scrollTop = options.top ?? 0;
    });
    HTMLElement.prototype.scrollTo = scrollToSpy as unknown as HTMLElement["scrollTo"];
    render(<Harness items={["a"]} />);
    scrollTo(500);
    await userEvent.click(jump()!);
    expect(scrollToSpy).toHaveBeenLastCalledWith({ top: 1400, behavior: "smooth" });
    expect(jump()).toBeNull();
    delete (HTMLElement.prototype as Partial<HTMLElement>).scrollTo;
  });

  it("scrolls instantly under reduced motion", async () => {
    motion(true);
    geometry();
    const scrollToSpy = vi.fn();
    HTMLElement.prototype.scrollTo = scrollToSpy as unknown as HTMLElement["scrollTo"];
    render(<Harness items={["a"]} />);
    scrollTo(500);
    await userEvent.click(jump()!);
    expect(scrollToSpy).not.toHaveBeenCalled();
    expect(pane().scrollTop).toBe(1400);
    delete (HTMLElement.prototype as Partial<HTMLElement>).scrollTo;
  });

  it("land() follows again from the bottom, instantly", () => {
    const g = geometry();
    let land = () => {};
    const { rerender } = render(<Harness items={["a"]} onLand={(l) => (land = l)} />);
    scrollTo(500);
    act(() => land());
    expect(jump()).toBeNull();
    g.content = 3000;
    rerender(<Harness items={["other"]} onLand={(l) => (land = l)} />);
    expect(pane().scrollTop).toBe(2400);
  });

  it("stays at the bottom when the pane resizes while following", () => {
    const callbacks: (() => void)[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          callbacks.push(callback);
        }
        observe() {}
        disconnect() {}
      },
    );
    const g = geometry();
    render(<Harness items={["a"]} />);
    expect(pane().scrollTop).toBe(1400);
    g.view = 400; // the split view opens and the text reflows taller
    g.content = 2600;
    act(() => callbacks.forEach((c) => c()));
    expect(pane().scrollTop).toBe(2200);
  });

  it("leaves the pane alone on resize while the learner reads earlier turns", () => {
    const callbacks: (() => void)[] = [];
    vi.stubGlobal(
      "ResizeObserver",
      class {
        constructor(callback: () => void) {
          callbacks.push(callback);
        }
        observe() {}
        disconnect() {}
      },
    );
    const g = geometry();
    render(<Harness items={["a"]} />);
    scrollTo(300);
    g.content = 2600;
    act(() => callbacks.forEach((c) => c()));
    expect(pane().scrollTop).toBe(300);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest run src/features/chat/useChatScroll.test.tsx`
Expected: FAIL — `Failed to resolve import "./useChatScroll"`.

- [ ] **Step 3: Write the hook**

Create `web/src/features/chat/useChatScroll.ts`:

```ts
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** How far above the bottom still counts as at the bottom: the pane follows a streaming answer from there. */
export const NEAR_BOTTOM_PX = 40;

// No matchMedia (tests, very old browsers): scroll instantly, the safe choice.
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? true;

const gap = (el: HTMLElement) => el.scrollHeight - el.clientHeight - el.scrollTop;

/**
 * The chat's messages pane scrolls like a conversation (DESIGN.md → Chat): while the learner is at (or near) the bottom
 * it follows new content; scrolling up stops the follow and `away` turns on, scrolling back near the bottom resumes it.
 * `content` lists what makes the pane grow; after each change the pane sticks to the bottom if following. While the
 * learner reads earlier turns the hook never moves the pane: the browser's scroll anchoring keeps it in place when the
 * layout reflows (the split view opening or closing).
 */
export function useChatScroll(content: readonly unknown[]) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [away, setAway] = useState(false);
  const following = useRef(true);
  // On the way down after toLatest(): keep scrolling smoothly until the bottom is reached.
  const catchingUp = useRef(false);
  const lastTop = useRef(0);

  const stick = useCallback(() => {
    if (!element || !following.current || gap(element) <= 0) return;
    const top = element.scrollHeight - element.clientHeight;
    if (catchingUp.current && !reducedMotion() && element.scrollTo) element.scrollTo({ top, behavior: "smooth" });
    else {
      element.scrollTop = top;
      // Recorded now, so the learner's next scroll up is measured from here even before the scroll event arrives.
      lastTop.current = element.scrollTop;
    }
  }, [element]);

  useLayoutEffect(stick, [stick, ...content]);

  useEffect(() => {
    if (!element) return;
    // Near the bottom follows; moving up away from it stops. Programmatic scrolls only ever move down, so they never stop it.
    const onScroll = () => {
      const top = element.scrollTop;
      if (gap(element) <= NEAR_BOTTOM_PX) {
        following.current = true;
        catchingUp.current = false;
      } else if (top < lastTop.current) {
        following.current = false;
        catchingUp.current = false;
      }
      lastTop.current = top;
      setAway(!following.current);
    };
    element.addEventListener("scroll", onScroll, { passive: true });
    // The pane or its content changed size (the split view, a taller composer): stay at the bottom if following.
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(stick);
    observer?.observe(element);
    if (element.firstElementChild) observer?.observe(element.firstElementChild);
    return () => {
      element.removeEventListener("scroll", onScroll);
      observer?.disconnect();
    };
  }, [element, stick]);

  const toLatest = useCallback(() => {
    following.current = true;
    catchingUp.current = true;
    setAway(false);
    stick();
  }, [stick]);

  const land = useCallback(() => {
    following.current = true;
    catchingUp.current = false;
    lastTop.current = 0;
    setAway(false);
  }, []);

  return { ref: setElement, element, away, toLatest, land };
}
```

Note: the "land()" test expects `scrollTop` 2400 after the rerender — `stick` runs in the layout effect because `items` changed. In `stick`, `scrollTop` is set unclamped in jsdom, which is why tests compute `content - view`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npx vitest run src/features/chat/useChatScroll.test.tsx`
Expected: PASS (9 tests). If `tsc` complains that `element.scrollTo` is always defined, keep the runtime guard and write it as `typeof element.scrollTo === "function"`.

- [ ] **Step 5: Commit**

```bash
git add web/src/features/chat/useChatScroll.ts web/src/features/chat/useChatScroll.test.tsx
git commit -m "Add a scroll hook that follows the chat only while at the bottom" -m "Issue #211: the messages pane didn't manage its scroll. The hook follows new content from the bottom, stops when the learner scrolls up, and jumps back on request."
```

---

### Task 2: Wire the hook into ChatPage, add Jump to latest, document it

**Files:**
- Modify: `web/src/features/chat/ChatPage.tsx` (imports ~1-54; `reset()` ~348; `answer()` ~404; messages pane ~790; form ~942)
- Modify: `web/src/features/chat/ChatPage.module.css` (`.messages`, `.form`, new `.jump`)
- Modify: `DESIGN.md` (Chat section, after the Split view paragraph)
- Test: `web/src/features/chat/ChatPage.test.tsx` (new `describe("scrolling the conversation")` at the end of the top-level `describe("ChatPage")`)

**Interfaces:**
- Consumes: `useChatScroll(content)` → `{ ref, element, away, toLatest, land }` from Task 1.

- [ ] **Step 1: Write the failing page tests**

Read the existing helpers in `ChatPage.test.tsx` first: `renderChat`, `controlledStream`, `question()`, `askButton()`, and inside `describe("a conversation at its URL")` the fixtures `conversation(turns, threadOverrides)`, `turn(overrides)`, `cited(...)`, `usedDoc`. If those fixtures are local to that `describe`, put the new `describe` inside it (or hoist the fixtures to module level without changing them). Add:

```tsx
  describe("scrolling the conversation", () => {
    // The messages pane as the learner scrolls it: a 600px window over `content` px of turns.
    function geometry(content = 2000) {
      const g = { content };
      const isPane = (el: Element) => el.getAttribute("aria-label") === "Messages";
      vi.spyOn(Element.prototype, "clientHeight", "get").mockImplementation(function (this: Element) {
        return isPane(this) ? 600 : 0;
      });
      vi.spyOn(Element.prototype, "scrollHeight", "get").mockImplementation(function (this: Element) {
        return isPane(this) ? g.content : 0;
      });
      return g;
    }
    const pane = () => screen.getByRole("region", { name: "Messages" });
    function scrollPane(top: number) {
      pane().scrollTop = top;
      fireEvent.scroll(pane());
    }
    const jump = () => screen.queryByRole("button", { name: "Jump to latest" });
    const many = (n: number) => Array.from({ length: n }, (_, i) => turn({ question: `Question ${i + 1}?`, answer: `Answer ${i + 1}.` }));

    it("reopening lands on the newest turn, with every earlier turn above it", async () => {
      geometry(9000);
      renderChat({ loadConversation: conversation(many(30)) }, "/chat/t1");
      expect(await screen.findByText("Answer 30.")).toBeInTheDocument();
      expect(screen.getAllByText("You asked:")).toHaveLength(30);
      expect(pane().scrollTop).toBe(9000 - 600);
      expect(jump()).toBeNull();
    });

    it("asking scrolls the question into view", async () => {
      const g = geometry();
      const askIn = vi.fn(() => events({ type: "thread", thread_id: "t1", run_id: "r2" }, { type: "delta", text: "More." }, { type: "done" }));
      renderChat({ loadConversation: conversation(many(5), { search_scope: "listed" }), loadUsed: async () => [usedDoc], askIn }, "/chat/t1");
      await screen.findByText("Answer 5.");
      scrollPane(200);
      expect(jump()).toBeInTheDocument();
      g.content = 2400;
      await userEvent.type(await question(), "Next?{Enter}");
      expect(await screen.findByText("More.")).toBeInTheDocument();
      expect(pane().scrollTop).toBe(2400 - 600);
      expect(jump()).toBeNull();
    });

    it("follows a streaming answer only while at the bottom", async () => {
      const g = geometry(600);
      const control = controlledStream();
      renderChat({ ask: vi.fn(() => control.stream()) });
      await userEvent.type(await question(), "What is attention?{Enter}");
      control.push({ type: "thread", thread_id: "t1", run_id: "r1" });
      g.content = 1000;
      control.push({ type: "delta", text: "It weighs " });
      await screen.findByText("It weighs");
      expect(pane().scrollTop).toBe(400); // follows

      scrollPane(100); // the learner scrolls up to read
      expect(jump()).toBeInTheDocument();
      g.content = 1400;
      control.push({ type: "delta", text: "tokens." });
      await screen.findByText("It weighs tokens.");
      expect(pane().scrollTop).toBe(100); // stays put

      scrollPane(800); // back at the bottom
      expect(jump()).toBeNull();
      g.content = 1800;
      control.push({ type: "delta", text: " More." });
      await screen.findByText("It weighs tokens. More.");
      expect(pane().scrollTop).toBe(1200); // follows again
      control.push({ type: "done" });
      control.push(null);
    });

    it("Jump to latest works from the keyboard and moves focus to the question box", async () => {
      geometry();
      renderChat({ loadConversation: conversation(many(5)) }, "/chat/t1");
      await screen.findByText("Answer 5.");
      scrollPane(200);
      const button = jump()!;
      expect(button).toHaveAccessibleName("Jump to latest");
      button.focus();
      await userEvent.keyboard("{Enter}");
      expect(pane().scrollTop).toBe(1400);
      expect(jump()).toBeNull();
      expect(await question()).toHaveFocus();
    });

    it("while answering, Jump to latest moves focus to the messages", async () => {
      const g = geometry(600);
      const control = controlledStream();
      renderChat({ ask: vi.fn(() => control.stream()) });
      await userEvent.type(await question(), "What is attention?{Enter}");
      control.push({ type: "thread", thread_id: "t1", run_id: "r1" });
      g.content = 2000;
      control.push({ type: "delta", text: "It weighs" });
      await screen.findByText("It weighs");
      scrollPane(100);
      await userEvent.click(jump()!);
      expect(pane()).toHaveFocus();
      control.push({ type: "done" });
      control.push(null);
    });

    it("only the newest turn's answer is a live region", async () => {
      renderChat({ loadConversation: conversation(many(3)) }, "/chat/t1");
      const newest = await screen.findByText("Answer 3.");
      const live = document.querySelectorAll('[aria-live="polite"]');
      expect(live).toHaveLength(1);
      expect(live[0]).toContainElement(newest);
      expect(screen.getByText("Answer 1.").closest("[aria-live]")).toBeNull();
    });

    it("opening and closing a document leaves the messages where they were", async () => {
      geometry();
      renderChat(
        { loadConversation: conversation([cited({ document_title: "ReAct", page: 2 }), ...many(4)]), viewerDeps: fakeViewerDeps() },
        "/chat/t1",
      );
      const chip = await screen.findByRole("button", { name: /^ReAct, p\. 2/ });
      scrollPane(300);
      await userEvent.click(chip);
      await userEvent.click(await screen.findByRole("button", { name: /close/i }));
      expect(pane().scrollTop).toBe(300);
    });
  });
```

Adjust only fixture names to match the file (e.g. if `cited()` returns a `TurnResponse` with citations, use it as shown; if the Close button's name differs, copy it from the existing "document viewer" tests).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest run src/features/chat/ChatPage.test.tsx -t "scrolling the conversation"`
Expected: FAIL — no region named "Messages".

- [ ] **Step 3: Wire the hook into ChatPage**

In `web/src/features/chat/ChatPage.tsx`:

1. Imports: add `ArrowDown` to the lucide import list (alphabetical, before `ArrowUp`) and `import { useChatScroll } from "./useChatScroll";` after `import { usePanelOpen } from "./usePanelOpen";`.

2. After `const [problem, setProblem] = ...` and the other state (place it right after `const turn = useRef(0);` block, before the route effect is fine), add:

```tsx
  // The messages pane follows new text only while the learner is at the bottom (DESIGN.md → Chat).
  const scroll = useChatScroll([turns, answering, problem]);
```

3. In `reset()`, after `setTurns([]);`, add:

```tsx
    // The next conversation opens on its newest turn.
    scroll.land();
```

4. In `answer()`, after `setTurns((list) => [...list, asked]);`, add:

```tsx
    // The question scrolls into view, and the answer is followed from the bottom.
    scroll.toLatest();
```

5. Add a handler next to `onSubmit`:

```tsx
  // The button goes once the pane is at the bottom, so focus moves on: to the question box, or while it is disabled
  // during an answer, to the messages.
  function jumpToLatest() {
    scroll.toLatest();
    if (answering) scroll.element?.focus();
    else input.current?.focus();
  }
```

6. Replace `<div className={styles.messages}>` with:

```tsx
          <div ref={scroll.ref} className={styles.messages} role="region" aria-label="Messages" tabIndex={-1}>
```

(`tabIndex={-1}`: focusable from Jump to latest, not a tab stop.)

7. In the `<form>`, as its first child (before the visually hidden label):

```tsx
            {/* Floats above the composer while the learner reads earlier turns; not a live region. */}
            {scroll.away && turns.length > 0 && (
              <Button size="sm" icon={ArrowDown} className={styles.jump} onClick={jumpToLatest}>
                Jump to latest
              </Button>
            )}
```

- [ ] **Step 4: Style it**

In `web/src/features/chat/ChatPage.module.css`:

- After the `.messages` rule add:
```css
/* Focused only by Jump to latest during an answer; the ring sits inside the pane so it isn't clipped. */
.messages:focus-visible { outline-offset: -2px; }
```
- Add `position: relative;` to the `.form` rule (first declaration line) and update its comment's end with "; Jump to latest floats above it".
- After the `.form` rule add (check `web/src/styles/tokens.css` for a pill radius token; use `999px` if there is none):
```css
/* Jump to latest: a small pill centred above the composer, over the bottom of the messages. */
.jump {
  position: absolute; bottom: 100%; left: 50%; transform: translateX(-50%); margin-bottom: var(--sp-2);
  border-radius: 999px; box-shadow: var(--shadow-sm);
}
```

- [ ] **Step 5: Run the page tests**

Run: `cd web && npx vitest run src/features/chat`
Expected: PASS, including every existing ChatPage test.

- [ ] **Step 6: Document it in DESIGN.md**

In `DESIGN.md` → `## Chat`, insert a new paragraph between the chat header paragraph and **Split view**:

```markdown
**Scrolling.** The messages scroll like a chat. Asking scrolls the new question into view at the bottom. While an answer streams, the pane follows the new text only when the learner is at the bottom (within 40px); scrolling up stops the follow, and scrolling back to the bottom resumes it. While they are away from the bottom, a small **Jump to latest** pill (secondary small button with a down arrow, centred above the composer) scrolls to the newest turn and moves focus to the question box (to the messages while an answer streams); it hides at the bottom. Reopening a conversation lands on its newest turn, with every earlier turn above it (no "load earlier" paging in Release 1). Opening or closing a document beside the conversation leaves the messages where they were. Scrolling is instant under `prefers-reduced-motion`. Only the newest turn's answer region is `aria-live`.
```

- [ ] **Step 7: Full checks**

Run: `cd web && npm test && npm run build`
Expected: all tests pass; `tsc -b && vite build` succeeds.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/chat/ChatPage.tsx web/src/features/chat/ChatPage.module.css web/src/features/chat/ChatPage.test.tsx DESIGN.md
git commit -m "Scroll the chat like a conversation, with Jump to latest" -m "Issue #211: the learner wants to scroll through a conversation's history. Asking scrolls the question into view, a streaming answer is followed only from the bottom, Jump to latest returns there, and a reopened conversation lands on its newest turn."
```

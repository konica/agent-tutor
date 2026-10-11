# Flip at the Edge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the one-page document viewer, scrolling on past a page's bottom opens the next page at its top, and scrolling on past its top opens the previous page at its bottom (ticket #212).

**Architecture:** Web only. A new hook `usePageFlip(areaRef, flip)` listens to `wheel` and `touch*` events on the viewer's scrolling canvas area. Only those events count, so a scroll the code makes (the citation reveal sets `scrollTop`) can never flip. A gesture turns the page only if it **started** at the edge it scrolls towards and travelled `FLIP_DISTANCE` px past it; after a flip the rest of that gesture is swallowed (`preventDefault`), so trackpad momentum can't skip pages or scroll the new page away from its edge. `DocumentViewer` passes a `flip` that calls its existing `goTo` (so the readout, `onPageChange`, and the dialog's page sync follow) and remembers where the new page should land; the render effect scrolls there as soon as the new page's canvas has its size. Both the side pane and the dialog render `DocumentViewer`, so both get it.

**Tech Stack:** React 19 + TypeScript, Vite, Vitest + Testing Library (jsdom), CSS modules.

**Spec:** GitHub issue #212 (parent #118, US-4b); `DESIGN.md` → Chat, Split view. The PRD's US-4b line (`sdd/prd.md` §8, "the document viewer shows its PDF from the first page…") does not describe paging, so the PRD is unchanged (the ticket asks for a PRD edit only if it does).

## Global Constraints

- Web only: no API, backend, or generated-client changes.
- Keep the one-page viewer; no continuous scroll.
- PageUp/PageDown, the toolbar's Previous/Next, zoom, and the citation reveal behave exactly as before (existing tests in `DocumentViewer.test.tsx` and `ViewerDialog.test.tsx` stay green, unmodified).
- Nothing happens past the first or last page.
- Gesture rules (exact values): a new wheel gesture starts after a pause of more than `GESTURE_GAP_MS = 200` ms between wheel events; a flip needs `FLIP_DISTANCE = 50` px of travel past the edge within one gesture that started at that edge; edge test allows `EDGE_SLACK = 1` px; a `deltaMode` 1 (lines) step is `LINE_PX = 16` px, `deltaMode` 2 (pages) is the area's `clientHeight`; `ctrlKey` wheel (pinch zoom) and wheel events with `deltaY === 0` are ignored. A touch gesture is one `touchstart` … `touchend`.
- The hook reads time with `Date.now()` (tests stub it; React's scheduler uses `performance.now`, so stubbing `Date.now` is safe, and Testing Library's `waitFor` doesn't read it).
- Match surrounding code: one-line comments that say why, no new abstractions beyond the hook.
- Commit subjects in the imperative mood; body says why; end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Checks: `cd web && npx vitest run <files>` per task; at the end `cd web && npm run build` and the full `npx vitest run`. On Windows the first vitest run may time out starting its worker; run it again.

## Review Focus

1. Trackpad momentum after a flip keeps sending wheel events for a second or more: it must not flip again or scroll the new page off its top. — Task 1 test "swallows the rest of a gesture that flipped".
2. A mouse wheel spun continuously down a long page reaches the bottom and keeps spinning: no flip until the learner pauses and scrolls again. — Task 1 test "the gesture that reaches the edge doesn't flip".
3. Ctrl+wheel (browser zoom or trackpad pinch) and sideways-only wheel at an edge must not flip. — Task 1 test "ignores pinch zoom and sideways scrolling".
4. Firefox mouse wheels send `deltaMode` 1 (lines, `deltaY` 3): one notch must still reach `FLIP_DISTANCE`. — Task 1 test "counts a wheel in lines".
5. Flipping up must land at the new page's bottom even though its canvas is resized when it renders; flipping must not move the citation reveal or the PageDown scroll position. — Task 2 tests "scrolling up past the top opens the previous page at its bottom" and "the citation reveal's scroll never flips".

---

### Task 1: `usePageFlip` hook

**Files:**
- Create: `web/src/features/viewer/usePageFlip.ts`
- Test: `web/src/features/viewer/usePageFlip.test.tsx`

**Interfaces:**
- Produces: `export type FlipDirection = 1 | -1;` and `export function usePageFlip(areaRef: RefObject<HTMLElement | null>, flip: (dir: FlipDirection) => boolean): void` — `flip(1)` asks for the next page, `flip(-1)` the previous; it returns whether it turned the page (false on the last/first page). Also exports `GESTURE_GAP_MS` (200) and `FLIP_DISTANCE` (50).

- [ ] **Step 1: Write the failing tests**

`web/src/features/viewer/usePageFlip.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { useRef } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FLIP_DISTANCE, GESTURE_GAP_MS, usePageFlip, type FlipDirection } from "./usePageFlip";

function Area({ flip }: { flip: (dir: FlipDirection) => boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  usePageFlip(ref, flip);
  return <div ref={ref} data-testid="area" />;
}

let now = 0;
const pause = () => (now += GESTURE_GAP_MS + 100);
const tick = () => (now += 16); // one frame: the same gesture

// A 600px area over a page of `height` px, scrolled to `top`.
function setup(height = 2000, top = 0, flip = vi.fn((_dir: FlipDirection) => true)) {
  render(<Area flip={flip} />);
  const area = screen.getByTestId("area");
  Object.defineProperty(area, "clientHeight", { configurable: true, value: 600 });
  Object.defineProperty(area, "scrollHeight", { configurable: true, value: height });
  area.scrollTop = top;
  // fireEvent returns false when the handler called preventDefault (the step was swallowed).
  const wheel = (deltaY: number, init: WheelEventInit = {}) => {
    tick();
    return fireEvent.wheel(area, { deltaY, ...init });
  };
  return { area, flip, wheel };
}

beforeEach(() => {
  now = 1_000_000;
  vi.spyOn(Date, "now").mockImplementation(() => now);
});
afterEach(() => vi.restoreAllMocks());

describe("usePageFlip with a wheel", () => {
  it("flips down once a gesture that starts at the bottom goes FLIP_DISTANCE past it", () => {
    const { flip, wheel } = setup(2000, 1400);
    expect(wheel(FLIP_DISTANCE - 10)).toBe(true);
    expect(flip).not.toHaveBeenCalled();
    expect(wheel(10)).toBe(false);
    expect(flip).toHaveBeenCalledExactlyOnceWith(1);
  });

  it("flips up once a gesture that starts at the top goes FLIP_DISTANCE past it", () => {
    const { flip, wheel } = setup(2000, 0);
    wheel(-FLIP_DISTANCE);
    expect(flip).toHaveBeenCalledExactlyOnceWith(-1);
  });

  it("the gesture that reaches the edge doesn't flip; the next one does", () => {
    const { area, flip, wheel } = setup(2000, 1300);
    wheel(100);
    area.scrollTop = 1400; // the browser scrolled it to the bottom
    for (let i = 0; i < 10; i++) wheel(100);
    expect(flip).not.toHaveBeenCalled();
    pause();
    wheel(100);
    expect(flip).toHaveBeenCalledExactlyOnceWith(1);
  });

  it("swallows the rest of a gesture that flipped, so momentum flips at most one page", () => {
    const { area, flip, wheel } = setup(600, 0);
    wheel(100);
    expect(flip).toHaveBeenCalledTimes(1);
    area.scrollTop = 0; // the new page, at its top
    for (let i = 0; i < 30; i++) expect(wheel(40)).toBe(false);
    expect(flip).toHaveBeenCalledTimes(1);
    pause();
    wheel(100);
    expect(flip).toHaveBeenCalledTimes(2);
  });

  it("a page that fits flips on one gesture either way", () => {
    const { flip, wheel } = setup(600, 0);
    wheel(100);
    pause();
    wheel(-100);
    expect(flip.mock.calls).toEqual([[1], [-1]]);
  });

  it("scrolling away from an edge is a normal scroll", () => {
    const { flip, wheel } = setup(2000, 1400);
    expect(wheel(-200)).toBe(true);
    expect(flip).not.toHaveBeenCalled();
  });

  it("a gesture that reverses at the other edge counts from there", () => {
    const { flip, wheel } = setup(600, 0);
    wheel(-20); // up at the top: not far enough
    wheel(100); // down within the same gesture: a fresh start at the bottom
    expect(flip).toHaveBeenCalledExactlyOnceWith(1);
  });

  it("does nothing more on the first or last page, and doesn't swallow the scroll", () => {
    const flip = vi.fn((_dir: FlipDirection) => false);
    const { wheel } = setup(600, 0, flip);
    expect(wheel(100)).toBe(true);
    expect(wheel(100)).toBe(true);
    expect(flip).toHaveBeenCalledWith(1);
  });

  it("allows a pixel of slack at the edge", () => {
    const { flip, wheel } = setup(2000, 1399.5);
    wheel(100);
    expect(flip).toHaveBeenCalledExactlyOnceWith(1);
  });

  it("counts a wheel in lines (Firefox) and in pages", () => {
    const { flip, wheel } = setup(600, 0);
    wheel(3, { deltaMode: 1 }); // 48px: just short
    wheel(1, { deltaMode: 1 });
    expect(flip).toHaveBeenCalledExactlyOnceWith(1);
    pause();
    wheel(-1, { deltaMode: 2 });
    expect(flip).toHaveBeenLastCalledWith(-1);
  });

  it("ignores pinch zoom and sideways scrolling", () => {
    const { flip, wheel } = setup(600, 0);
    expect(wheel(100, { ctrlKey: true })).toBe(true);
    wheel(0, { deltaX: 100 });
    expect(flip).not.toHaveBeenCalled();
  });
});

describe("usePageFlip with touch", () => {
  const touch = (area: HTMLElement, type: "touchStart" | "touchMove" | "touchEnd", clientY?: number) =>
    fireEvent[type](area, { touches: clientY === undefined ? [] : [{ clientY }] });

  it("a swipe up that starts at the bottom flips to the next page once", () => {
    const { area, flip } = setup(2000, 1400);
    touch(area, "touchStart", 500);
    touch(area, "touchMove", 500 - FLIP_DISTANCE + 1);
    expect(flip).not.toHaveBeenCalled();
    touch(area, "touchMove", 500 - FLIP_DISTANCE);
    touch(area, "touchMove", 100);
    touch(area, "touchEnd");
    expect(flip).toHaveBeenCalledExactlyOnceWith(1);
  });

  it("a swipe down that starts at the top flips to the previous page", () => {
    const { area, flip } = setup(2000, 0);
    touch(area, "touchStart", 100);
    touch(area, "touchMove", 100 + FLIP_DISTANCE);
    expect(flip).toHaveBeenCalledExactlyOnceWith(-1);
  });

  it("a swipe that starts inside the page doesn't flip, even when it reaches the edge", () => {
    const { area, flip } = setup(2000, 1300);
    touch(area, "touchStart", 500);
    area.scrollTop = 1400;
    touch(area, "touchMove", 300);
    touch(area, "touchEnd");
    expect(flip).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest run src/features/viewer/usePageFlip.test.tsx`
Expected: FAIL — cannot resolve `./usePageFlip`.

- [ ] **Step 3: Write the hook**

`web/src/features/viewer/usePageFlip.ts`:

```ts
import { useEffect, useRef, type RefObject } from "react";

export type FlipDirection = 1 | -1; // 1: the next page, -1: the previous one

// A pause longer than this between wheel events starts a new gesture; trackpad momentum and a spun wheel send theirs closer.
export const GESTURE_GAP_MS = 200;
// How far (px) a gesture that starts at an edge must keep going past it before the page turns: one wheel notch is ~100.
export const FLIP_DISTANCE = 50;
const EDGE_SLACK = 1; // px: a zoomed or fractional scroll position stops just short of the edge
const LINE_PX = 16; // a wheel step in lines (Firefox), in px

type Gesture = { dir: FlipDirection; fromEdge: boolean; distance: number; done: boolean };

function atEdge(area: HTMLElement, dir: FlipDirection): boolean {
  return dir > 0 ? area.scrollTop + area.clientHeight >= area.scrollHeight - EDGE_SLACK : area.scrollTop <= EDGE_SLACK;
}

// Turns the page when the learner keeps scrolling past its edge (#212). Only wheel and touch gestures count, so a scroll
// the code makes (the citation reveal) never flips. A gesture flips only if it started at the edge it scrolls towards
// and went FLIP_DISTANCE past it, so the gesture that reaches the edge doesn't; a page with no scrollbar is at both
// edges, so one gesture flips it. The rest of a gesture that flipped is swallowed: momentum can't skip pages or scroll
// the new page away from its edge. `flip` returns whether the page turned (not past the first or last page).
export function usePageFlip(areaRef: RefObject<HTMLElement | null>, flip: (dir: FlipDirection) => boolean): void {
  const flipRef = useRef(flip);
  flipRef.current = flip;

  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    let gesture: Gesture | null = null;
    let lastWheel = -Infinity;
    let touchY: number | null = null;
    let touchEdges = { down: false, up: false }; // where the area was when the finger touched down

    // One step of the current gesture; true when the step must be swallowed. `fromEdge`: whether the gesture started at
    // the edge it now scrolls towards (a reversed gesture starts over in its new direction).
    const step = (dir: FlipDirection, distance: number, fromEdge: boolean): boolean => {
      if (gesture === null || gesture.dir !== dir) gesture = { dir, fromEdge, distance: 0, done: false };
      if (gesture.done) return true;
      if (!gesture.fromEdge) return false;
      gesture.distance += distance;
      if (gesture.distance < FLIP_DISTANCE || !flipRef.current(dir)) return false;
      gesture.done = true;
      return true;
    };

    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.deltaY === 0) return; // pinch zoom, or sideways
      const now = Date.now();
      if (now - lastWheel > GESTURE_GAP_MS) gesture = null;
      lastWheel = now;
      const px = event.deltaMode === 1 ? event.deltaY * LINE_PX : event.deltaMode === 2 ? event.deltaY * area.clientHeight : event.deltaY;
      const dir: FlipDirection = px > 0 ? 1 : -1;
      if (step(dir, Math.abs(px), atEdge(area, dir))) event.preventDefault();
    };

    const onTouchStart = (event: TouchEvent) => {
      gesture = null;
      touchY = event.touches[0]?.clientY ?? null;
      touchEdges = { down: atEdge(area, 1), up: atEdge(area, -1) };
    };
    // The finger's total travel since it touched down; moving it up scrolls down.
    const onTouchMove = (event: TouchEvent) => {
      const y = event.touches[0]?.clientY;
      if (touchY === null || y === undefined || y === touchY) return;
      const travel = touchY - y;
      const dir: FlipDirection = travel > 0 ? 1 : -1;
      const before = gesture?.dir === dir ? gesture.distance : 0;
      if (step(dir, Math.abs(travel) - before, dir > 0 ? touchEdges.down : touchEdges.up) && event.cancelable) event.preventDefault();
    };
    const onTouchEnd = () => {
      touchY = null;
    };

    area.addEventListener("wheel", onWheel, { passive: false });
    area.addEventListener("touchstart", onTouchStart, { passive: true });
    area.addEventListener("touchmove", onTouchMove, { passive: false });
    area.addEventListener("touchend", onTouchEnd);
    area.addEventListener("touchcancel", onTouchEnd);
    return () => {
      area.removeEventListener("wheel", onWheel);
      area.removeEventListener("touchstart", onTouchStart);
      area.removeEventListener("touchmove", onTouchMove);
      area.removeEventListener("touchend", onTouchEnd);
      area.removeEventListener("touchcancel", onTouchEnd);
    };
  }, [areaRef]);
}
```

Notes for the implementer:
- React's `onWheel` prop is passive, so `preventDefault` there does nothing; that is why the hook adds native listeners.
- In `onTouchMove`, `step` accumulates, so it is fed only the travel added since the last move (`Math.abs(travel) - before`). A gesture that is `done` keeps its distance, which is fine: it only swallows.
- A wheel gesture's `fromEdge` is read when the gesture starts (its first event, before the browser scrolls for it); a touch gesture's is read on `touchstart`, because by the first `touchmove` the browser may already have scrolled to the edge.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npx vitest run src/features/viewer/usePageFlip.test.tsx`
Expected: PASS (14 tests).

- [ ] **Step 5: Lint and commit**

Run: `cd web && npx tsc -b` and fix any type errors (the `build` script is `tsc -b && vite build`).

```bash
git add web/src/features/viewer/usePageFlip.ts web/src/features/viewer/usePageFlip.test.tsx
git commit -m "Add a hook that turns the viewer's page at a scroll edge

Client feedback (#212): scrolling past a page's edge should turn the page.
The hook counts only wheel and touch gestures, flips only on a gesture that
starts at the edge, and swallows the rest of it so momentum can't skip pages.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Flip the viewer's page at the edge, and document it

**Files:**
- Modify: `web/src/features/viewer/DocumentViewer.tsx` (imports; refs next to `canvasAreaRef`; the render effect at lines 126–144; a `flip` next to `goTo`)
- Modify: `web/src/features/viewer/DocumentViewer.module.css:33` (`.canvasArea`)
- Modify: `DESIGN.md:110` (Chat → **Split view** paragraph)
- Test: `web/src/features/viewer/DocumentViewer.test.tsx`, `web/src/features/viewer/ViewerDialog.test.tsx`

**Interfaces:**
- Consumes: `usePageFlip(areaRef, flip)` and `type FlipDirection` from `./usePageFlip` (Task 1); `GESTURE_GAP_MS` for tests.
- Produces: no new props; `DocumentViewer` behavior only.

- [ ] **Step 1: Write the failing viewer tests**

Append to `web/src/features/viewer/DocumentViewer.test.tsx` (add `afterEach`, `beforeEach` to the vitest import and `GESTURE_GAP_MS` from `./usePageFlip`):

```tsx
// The canvas area as the learner scrolls it: a 600px window over a 2000px page (or a page that fits), at `top`.
function scrollArea(height = 2000) {
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(600);
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockReturnValue(height);
}
const area = () => document.querySelector<HTMLElement>(".canvasArea")!;

describe("DocumentViewer flip at the edge", () => {
  let now = 1_000_000;
  const wheel = (deltaY: number) => {
    now += 16;
    fireEvent.wheel(area(), { deltaY });
  };
  const pause = () => (now += GESTURE_GAP_MS + 100);
  beforeEach(() => {
    vi.spyOn(Date, "now").mockImplementation(() => now);
  });
  afterEach(() => vi.restoreAllMocks());

  it("scrolling down past the bottom opens the next page at its top", async () => {
    scrollArea();
    const onPageChange = vi.fn();
    const onOpenInDialog = vi.fn();
    renderViewer({ onPageChange, onOpenInDialog });
    await ready();
    area().scrollTop = 1400;
    wheel(100);
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    expect(onPageChange).toHaveBeenLastCalledWith(2);
    await waitFor(() => expect(area().scrollTop).toBe(0));
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Open in dialog" }));
    expect(onOpenInDialog).toHaveBeenCalledWith(2);
  });

  it("scrolling up past the top opens the previous page at its bottom", async () => {
    scrollArea();
    renderViewer({ initialPage: 3 });
    expect(await screen.findByText("p. 3 / 3")).toBeInTheDocument();
    area().scrollTop = 0;
    wheel(-100);
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    await waitFor(() => expect(area().scrollTop).toBe(2000 - 600));
  });

  it("the gesture that reaches the bottom doesn't flip; one more gesture flips one page", async () => {
    scrollArea();
    renderViewer();
    await ready();
    area().scrollTop = 1300;
    wheel(100);
    area().scrollTop = 1400; // the browser scrolled to the bottom
    for (let i = 0; i < 20; i++) wheel(100);
    expect(screen.getByText("p. 1 / 3")).toBeInTheDocument();
    pause();
    for (let i = 0; i < 20; i++) wheel(100); // a flick with momentum
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
  });

  it("a page with no scrollbar flips on one gesture either way", async () => {
    scrollArea(600);
    renderViewer();
    await ready();
    wheel(100);
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
    pause();
    wheel(-100);
    expect(screen.getByText("p. 1 / 3")).toBeInTheDocument();
  });

  it("nothing happens past the first or last page", async () => {
    scrollArea(600);
    const onPageChange = vi.fn();
    renderViewer({ onPageChange });
    await ready();
    wheel(-100);
    expect(screen.getByText("p. 1 / 3")).toBeInTheDocument();
    for (let i = 0; i < 3; i++) {
      pause();
      wheel(100);
    }
    expect(screen.getByText("p. 3 / 3")).toBeInTheDocument();
    expect(onPageChange.mock.calls).toEqual([[2], [3]]);
  });

  it("PageDown keeps the scroll position (no landing)", async () => {
    scrollArea();
    renderViewer();
    await ready();
    area().scrollTop = 700;
    fireEvent.keyDown(screen.getByRole("heading", { level: 2 }), { key: "PageDown" });
    expect(await screen.findByText("Page 2 of 3")).toBeInTheDocument();
    expect(area().scrollTop).toBe(700);
  });

  it("the citation reveal's scroll never flips", async () => {
    // The reveal scrolls the passage to a third from the top: 40 + 300 - 600 / 3 = 140, the bottom of a 740px page.
    scrollArea(740);
    vi.spyOn(HTMLElement.prototype, "offsetTop", "get").mockReturnValue(40);
    renderCited([CITED]);
    await screen.findByTestId("passage-box");
    await waitFor(() => expect(area().scrollTop).toBe(140));
    fireEvent.scroll(area());
    await waitFor(() => expect(status()).toHaveTextContent("Opened page 2 of 3. Cited passage highlighted."));
    expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
  });
});
```

`renderCited`, `CITED`, and `status` are defined later in the same file (module scope, so usable from this `describe`); place the new `describe` block at the end of the file.

Append to `web/src/features/viewer/ViewerDialog.test.tsx` inside `describe("ViewerDialog", …)` (add `vi` usage as already imported):

```tsx
  it("flips at the edge and closes with the flipped page", async () => {
    vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(600);
    vi.spyOn(Element.prototype, "scrollHeight", "get").mockReturnValue(600);
    try {
      const { onClose } = open();
      await ready();
      fireEvent.wheel(document.querySelector(".canvasArea")!, { deltaY: 100 });
      expect(screen.getByText("p. 2 / 3")).toBeInTheDocument();
      fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
      expect(onClose).toHaveBeenCalledWith(2);
    } finally {
      vi.restoreAllMocks();
    }
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx vitest run src/features/viewer/DocumentViewer.test.tsx src/features/viewer/ViewerDialog.test.tsx`
Expected: the new flip tests FAIL (the page stays at "p. 1 / 3" / "p. 3 / 3"); "PageDown keeps the scroll position" and "the citation reveal's scroll never flips" may already pass (they guard against regressions); all existing tests PASS.

- [ ] **Step 3: Wire the hook into `DocumentViewer`**

In `web/src/features/viewer/DocumentViewer.tsx`:

Add the import after `./useDocumentFile`:

```ts
import { usePageFlip, type FlipDirection } from "./usePageFlip";
```

After `const renderChain = useRef<Promise<void>>(Promise.resolve());` add:

```ts
  // Where a page reached by flipping opens: its top going down, its bottom going up, so reading continues (#212).
  const landAt = useRef<FlipDirection | null>(null);
```

Replace the render effect's inner body so it lands as soon as the canvas has its new size (`PdfPage.render` sizes the canvas before it draws):

```ts
  // pdf.js can't render twice into one canvas at once, so each render waits for the one before it.
  useEffect(() => {
    if (!doc) return;
    let live = true;
    const run = renderChain.current.then(async () => {
      if (!live) return;
      const pdfPage = await doc.page(page);
      if (!live || !canvasRef.current) return;
      const drawn = pdfPage.render(canvasRef.current, zoom / 100);
      // A flipped-to page lands once the canvas has its size, which render sets before it draws.
      const area = canvasAreaRef.current;
      if (landAt.current !== null && area) {
        area.scrollTop = landAt.current > 0 ? 0 : Math.max(0, area.scrollHeight - area.clientHeight);
        landAt.current = null;
      }
      await drawn;
      if (live) setRendered(true);
    });
    renderChain.current = run.catch(() => {});
    run.catch(() => {
      if (live) setPdf({ status: "failed" });
    });
    return () => {
      live = false;
    };
  }, [doc, page, zoom]);
```

After `goTo`, add:

```ts
  const flip = (dir: FlipDirection) => {
    if (numPages === null || page + dir < 1 || page + dir > numPages) return false;
    landAt.current = dir;
    goTo(page + dir);
    return true;
  };
  usePageFlip(canvasAreaRef, flip);
```

`usePageFlip` must be called unconditionally on every render (it is a hook), so place it at the top level of `Viewer` right after `flip`, before `onKeyDown` — not inside any condition.

- [ ] **Step 4: Keep scrolling inside the canvas area**

In `web/src/features/viewer/DocumentViewer.module.css`, line 33, add `overscroll-behavior: contain` so a scroll past the page's edge never chains to the page or the dialog's backdrop, and no rubber-band bounce shows at the edge:

```css
.canvasArea { position: relative; flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; background: var(--surface-3); }
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd web && npx vitest run src/features/viewer`
Expected: PASS, all viewer tests (existing + new).

- [ ] **Step 6: Describe flip at the edge in DESIGN.md**

In `DESIGN.md` line 110 (Chat → **Split view**), after the sentence `The pane has one 40px toolbar (title, "p. 3 / 33", zoom, **Open in dialog**, Close) and is a labelled region, not a modal: …`, i.e. right after `… the chip whose passage is shown stays highlighted in the conversation.`, insert:

```markdown
The viewer shows one page at a time. Previous/Next and PageUp/PageDown turn the page; so does **flip at the edge**: scrolling on past a page's bottom opens the next page at its top, and past its top opens the previous page at its bottom. It takes a deliberate extra scroll (wheel, trackpad, or touch) that starts at the edge, so the scroll that reaches the edge, trackpad momentum, and the scroll to a cited passage never turn the page, and one gesture turns at most one page; a page that fits the pane turns on one gesture. Nothing happens past the first or last page.
```

- [ ] **Step 7: Full web checks**

Run: `cd web && npx vitest run && npm run build`
Expected: all tests PASS; build succeeds.

- [ ] **Step 8: Commit**

```bash
git add web/src/features/viewer/DocumentViewer.tsx web/src/features/viewer/DocumentViewer.module.css web/src/features/viewer/DocumentViewer.test.tsx web/src/features/viewer/ViewerDialog.test.tsx DESIGN.md
git commit -m "Turn the viewer's page when scrolling past its edge

Client feedback (#212): at a page's bottom, scrolling on should open the
next page, and at its top the previous one. The pane and the dialog share
DocumentViewer, so both flip; the flip goes through goTo, so the readout and
the dialog's page sync follow. Going up lands at the page's bottom so
reading continues.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3 (controller, not a subagent): check by hand and open the PR

- [ ] Run the app (`make web` against the Compose stack, or `docker compose --profile app up -d`), sign in as `learner@example.com`, open a multi-page document from the Library and from a citation in chat. In **installed Chrome** (Playwright channel `chrome`) and the **bundled Chromium**: wheel past the bottom/top of a long page, a page that fits (zoom 50%), the first and last pages, the dialog (Open in dialog, flip, Back to side by side lands on the flipped page), and a citation opening at its passage without flipping.
- [ ] Push the branch and open a PR closing #212; note in the description that the PRD is unchanged (its US-4b line doesn't describe paging).

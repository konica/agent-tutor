import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { GESTURE_GAP_MS, useChatScroll } from "./useChatScroll";

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
  delete (HTMLElement.prototype as Partial<HTMLElement>).scrollTo;
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

  // The learner scrolls up, then wheels back down while the answer streams.
  function wheelBackDown(waitBeforeLanding: number) {
    let now = 1_000_000;
    vi.spyOn(Date, "now").mockImplementation(() => now);
    const g = geometry();
    const { rerender } = render(<Harness items={["a"]} />);
    scrollTo(500);
    now += GESTURE_GAP_MS + 1;
    scrollTo(900); // the gesture begins; the bottom is at 1400
    g.content = 2100;
    rerender(<Harness items={["a", "b"]} />);
    expect(pane().scrollTop).toBe(900);
    now += waitBeforeLanding;
    scrollTo(1400); // 100px above the bottom as it is now
    return { g, rerender };
  }

  it("scrolling down to where the bottom was when the scroll began resumes following, though the answer grew meanwhile", () => {
    const { g, rerender } = wheelBackDown(16);
    expect(jump()).toBeNull();
    g.content = 2400;
    rerender(<Harness items={["a", "b", "c"]} />);
    expect(pane().scrollTop).toBe(1800);
  });

  it("a new scroll gesture measures from the bottom as it is now", () => {
    const { g, rerender } = wheelBackDown(GESTURE_GAP_MS + 1);
    expect(jump()).toBeInTheDocument();
    g.content = 2400;
    rerender(<Harness items={["a", "b", "c"]} />);
    expect(pane().scrollTop).toBe(1400);
  });
});

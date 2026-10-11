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
    expect(wheel(FLIP_DISTANCE - 10)).toBe(false); // swallowed from its first step: nothing to scroll past the edge
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

  it("does nothing more on the first or last page, and swallows the scroll there", () => {
    const flip = vi.fn((_dir: FlipDirection) => false);
    const { wheel } = setup(600, 0, flip);
    expect(wheel(100)).toBe(false);
    expect(wheel(100)).toBe(false);
    expect(flip).toHaveBeenCalledWith(1);
  });

  it("allows a pixel of slack at the edge", () => {
    const { flip, wheel } = setup(2000, 1399.5);
    wheel(100);
    expect(flip).toHaveBeenCalledExactlyOnceWith(1);
  });

  it("one 3-line notch (Firefox) or one page step flips", () => {
    const { flip, wheel } = setup(600, 0);
    wheel(3, { deltaMode: 1 });
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

  it("a mostly sideways wheel at an edge pans the zoomed page: not swallowed, no flip", () => {
    const { flip, wheel } = setup(600, 0);
    for (let i = 0; i < 5; i++) expect(wheel(10, { deltaX: 100 })).toBe(true);
    expect(flip).not.toHaveBeenCalled();
  });

  it("a Chrome wheel set to one line per notch (33px) flips on one notch", () => {
    const { flip, wheel } = setup(2000, 1400);
    expect(wheel(33)).toBe(false);
    expect(flip).toHaveBeenCalledExactlyOnceWith(1);
  });
});

describe("usePageFlip with touch", () => {
  // fireEvent returns false when the handler called preventDefault (the move was swallowed).
  const touch = (area: HTMLElement, type: "touchStart" | "touchMove" | "touchEnd", clientY?: number, init: { clientX?: number; cancelable?: boolean } = {}) =>
    fireEvent[type](area, {
      touches: clientY === undefined ? [] : [{ clientX: init.clientX ?? 0, clientY }],
      ...(init.cancelable === undefined ? {} : { cancelable: init.cancelable }),
    });
  const twoFingers = (area: HTMLElement, type: "touchStart" | "touchMove", clientY: number) =>
    fireEvent[type](area, { touches: [{ clientX: 0, clientY }, { clientX: 100, clientY }] });

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

  it("swallows a touch that starts at the edge from its first move, before it flips", () => {
    const { area, flip } = setup(2000, 1400);
    touch(area, "touchStart", 500);
    expect(touch(area, "touchMove", 495)).toBe(false);
    expect(flip).not.toHaveBeenCalled();
  });

  it("a second finger (a pinch) never flips and isn't swallowed", () => {
    const { area, flip } = setup(600, 0);
    twoFingers(area, "touchStart", 500);
    expect(twoFingers(area, "touchMove", 300)).toBe(true);
    expect(touch(area, "touchMove", 300)).toBe(true);
    touch(area, "touchEnd");
    touch(area, "touchStart", 500);
    expect(twoFingers(area, "touchMove", 300)).toBe(true);
    expect(touch(area, "touchMove", 200)).toBe(true);
    expect(flip).not.toHaveBeenCalled();
  });

  it("doesn't flip under a move the browser is already scrolling (not cancelable)", () => {
    const { area, flip } = setup(600, 0);
    touch(area, "touchStart", 500);
    touch(area, "touchMove", 300, { cancelable: false });
    touch(area, "touchMove", 200);
    expect(flip).not.toHaveBeenCalled();
  });

  it("a sideways swipe at an edge pans the zoomed page: not swallowed, no flip", () => {
    const { area, flip } = setup(600, 0);
    touch(area, "touchStart", 500, { clientX: 300 });
    expect(touch(area, "touchMove", 440, { clientX: 100 })).toBe(true);
    expect(flip).not.toHaveBeenCalled();
  });

  it("a touch that reverses counts from the other edge", () => {
    const { area, flip } = setup(600, 0);
    touch(area, "touchStart", 300);
    touch(area, "touchMove", 310); // down at the top: not far enough
    touch(area, "touchMove", 300 - FLIP_DISTANCE); // up past where it started: a fresh start at the bottom
    expect(flip).toHaveBeenCalledExactlyOnceWith(1);
  });

  it("a new touch after a flip flips again", () => {
    const { area, flip } = setup(600, 0);
    touch(area, "touchStart", 500);
    touch(area, "touchMove", 100);
    touch(area, "touchEnd");
    touch(area, "touchStart", 500);
    touch(area, "touchMove", 100);
    expect(flip.mock.calls).toEqual([[1], [1]]);
  });
});

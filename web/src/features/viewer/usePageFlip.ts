import { useEffect, useRef, type RefObject } from "react";

export type FlipDirection = 1 | -1; // 1: the next page, -1: the previous one

// A pause longer than this between wheel events starts a new gesture; trackpad momentum and a spun wheel send theirs closer.
export const GESTURE_GAP_MS = 200;
// How far (px) a gesture that starts at an edge must keep going past it before the page turns: one wheel notch is ~100,
// or ~33 in Chrome set to one line per notch.
export const FLIP_DISTANCE = 30;
const EDGE_SLACK = 1; // px: a zoomed or fractional scroll position stops just short of the edge
const LINE_PX = 16; // a wheel step in lines (Firefox), in px

type Gesture = { dir: FlipDirection; fromEdge: boolean; distance: number; done: boolean };

function atEdge(area: HTMLElement, dir: FlipDirection): boolean {
  return dir > 0 ? area.scrollTop + area.clientHeight >= area.scrollHeight - EDGE_SLACK : area.scrollTop <= EDGE_SLACK;
}

// Turns the page when the learner keeps scrolling past its edge (#212). Only wheel and touch gestures count, so a scroll
// the code makes (the citation reveal) never flips. A gesture flips only if it started at the edge it scrolls towards
// and went FLIP_DISTANCE past it, so the gesture that reaches the edge doesn't; a page with no scrollbar is at both
// edges, so one gesture flips it. Such a gesture is swallowed from its first step (there is nothing to scroll past the
// edge): a browser that scrolled its first steps would scroll the rest, and its momentum, uncancelably, moving the new
// page away from its edge; after a flip, momentum can't skip pages. `flip` returns whether the page turned (not past
// the first or last page).
export function usePageFlip(areaRef: RefObject<HTMLElement | null>, flip: (dir: FlipDirection) => boolean): void {
  const flipRef = useRef(flip);
  flipRef.current = flip;

  useEffect(() => {
    const area = areaRef.current;
    if (!area) return;
    let gesture: Gesture | null = null;
    let lastWheel = -Infinity;
    let touchStart: { x: number; y: number } | null = null;
    let touchEdges = { down: false, up: false }; // where the area was when the finger touched down

    // One step of the current gesture; true when the step must be swallowed. `fromEdge`: whether the gesture started at
    // the edge it now scrolls towards (a reversed gesture starts over in its new direction).
    const step = (dir: FlipDirection, distance: number, fromEdge: boolean): boolean => {
      if (gesture === null || gesture.dir !== dir) gesture = { dir, fromEdge, distance: 0, done: false };
      if (!gesture.fromEdge) return false;
      if (gesture.done) return true;
      gesture.distance += distance;
      if (gesture.distance >= FLIP_DISTANCE && flipRef.current(dir)) gesture.done = true;
      return true;
    };

    const onWheel = (event: WheelEvent) => {
      const mode = event.deltaMode; // read first: Firefox turns lines into pixels for a handler that reads a delta first
      if (event.ctrlKey || event.deltaY === 0 || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return; // pinch zoom, or sideways
      const now = Date.now();
      if (now - lastWheel > GESTURE_GAP_MS) gesture = null;
      lastWheel = now;
      // A wheel stepping in lines or pages turns the page on one notch, as one in pixels does.
      const unit = mode === 1 ? LINE_PX : mode === 2 ? area.clientHeight : 0;
      const distance = unit ? Math.max(FLIP_DISTANCE, Math.abs(event.deltaY) * unit) : Math.abs(event.deltaY);
      const dir: FlipDirection = event.deltaY > 0 ? 1 : -1;
      if (step(dir, distance, atEdge(area, dir))) event.preventDefault();
    };

    // A touch counts only while one finger moves it: a second finger (a pinch) drops it until the next touch.
    const onTouchStart = (event: TouchEvent) => {
      gesture = null;
      const finger = event.touches.length === 1 ? event.touches[0] : undefined;
      touchStart = finger ? { x: finger.clientX, y: finger.clientY } : null;
      touchEdges = { down: atEdge(area, 1), up: atEdge(area, -1) };
    };
    // The finger's total travel since it touched down; moving it up scrolls down.
    const onTouchMove = (event: TouchEvent) => {
      const finger = event.touches.length === 1 ? event.touches[0] : undefined;
      // Not cancelable: the browser is already scrolling this touch (it moved away first, or began in a fling), and
      // not flipping beats flipping under a running scroll.
      if (!finger || !event.cancelable) {
        touchStart = null;
        return;
      }
      if (touchStart === null) return;
      const dx = touchStart.x - finger.clientX;
      const travel = touchStart.y - finger.clientY;
      if (travel === 0 || Math.abs(dx) > Math.abs(travel)) return; // sideways: a pan of the zoomed page
      const dir: FlipDirection = travel > 0 ? 1 : -1;
      const before = gesture?.dir === dir ? gesture.distance : 0;
      if (step(dir, Math.abs(travel) - before, dir > 0 ? touchEdges.down : touchEdges.up)) event.preventDefault();
    };
    const onTouchEnd = () => {
      touchStart = null;
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

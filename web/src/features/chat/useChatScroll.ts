import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

/** How far above the bottom still counts as at the bottom: the pane follows a streaming answer from there. */
export const NEAR_BOTTOM_PX = 40;

/** Scroll events less than this far apart belong to one gesture (a wheel flick, a drag). */
export const GESTURE_GAP_MS = 150;

// No matchMedia (tests, very old browsers): scroll instantly, the safe choice.
const reducedMotion = () => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? true;

const gap = (el: HTMLElement) => el.scrollHeight - el.clientHeight - el.scrollTop;

/**
 * The chat's messages pane scrolls like a conversation (DESIGN.md → Chat): while the learner is at (or near) the bottom
 * it follows new content; scrolling up stops the follow and `away` turns on, scrolling back near the bottom resumes it.
 * `content` lists what makes the pane grow; after each change the pane sticks to the bottom if following. While the
 * learner reads earlier turns the hook never moves the pane: the browser's scroll anchoring keeps it in place when the
 * layout reflows (the split view opening or closing). Scrolling down to where the bottom was when that downward scroll
 * began also resumes it: a smooth wheel scroll lands there while a streaming answer keeps growing.
 */
export function useChatScroll(content: readonly unknown[]) {
  const [element, setElement] = useState<HTMLElement | null>(null);
  const [away, setAway] = useState(false);
  const following = useRef(true);
  // On the way down after toLatest(): keep scrolling smoothly until the bottom is reached.
  const catchingUp = useRef(false);
  const lastTop = useRef(0);
  // Where the bottom was when the current downward scroll began, and the direction of the last move.
  const movingDown = useRef(false);
  const lastScrollAt = useRef(0);
  const gestureBottom = useRef(0);

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
      const now = Date.now();
      const wasDown = movingDown.current;
      if (top > lastTop.current) movingDown.current = true;
      else if (top < lastTop.current) movingDown.current = false;
      // A downward scroll is measured from the bottom as it was when it began: a new gesture or a turn from up to down.
      if (now - lastScrollAt.current > GESTURE_GAP_MS || (movingDown.current && !wasDown)) {
        gestureBottom.current = element.scrollHeight - element.clientHeight;
      }
      lastScrollAt.current = now;
      // Any upward scroll stops the follow, even inside the near-bottom zone. A clamp from shrinking content leaves no gap.
      if (top < lastTop.current && gap(element) > 0) {
        following.current = false;
        catchingUp.current = false;
      } else if (gap(element) <= NEAR_BOTTOM_PX || (top > lastTop.current && gestureBottom.current - top <= NEAR_BOTTOM_PX)) {
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

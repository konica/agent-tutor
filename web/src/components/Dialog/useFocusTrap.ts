import { useEffect, useRef, type KeyboardEvent, type RefObject } from "react";

const FOCUSABLE = 'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

// A modal's focus rules (DESIGN.md → Accessibility): on mount focus moves in (to [data-autofocus], else the first
// focusable), Tab stays in, Escape closes without reaching the page beneath, and on unmount focus goes to `returnTo`
// when given, else back to what had it before.
export function useFocusTrap(onClose: () => void, returnTo?: RefObject<HTMLElement | null>) {
  const ref = useRef<HTMLDivElement>(null);
  const returnToRef = useRef(returnTo);
  returnToRef.current = returnTo;

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const root = ref.current!;
    (root.querySelector<HTMLElement>("[data-autofocus]") ?? root.querySelector<HTMLElement>(FOCUSABLE))?.focus();
    return () => (returnToRef.current?.current ?? previous)?.focus();
  }, []);

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const items = Array.from(ref.current!.querySelectorAll<HTMLElement>(FOCUSABLE));
    const first = items[0];
    const last = items[items.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return { ref, onKeyDown };
}

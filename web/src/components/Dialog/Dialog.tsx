import { X } from "lucide-react";
import { useEffect, useId, useRef, type KeyboardEvent, type ReactNode } from "react";

import { IconButton } from "../Button/IconButton";
import styles from "./Dialog.module.css";

const FOCUSABLE = 'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])';

type Props = { title: ReactNode; kicker?: string; wide?: boolean; onClose: () => void; children: ReactNode; footer: ReactNode };

// A modal over the page (DESIGN.md → Accessibility): focus moves in, Tab stays in, Escape closes, focus goes back.
export function Dialog({ title, kicker, wide, onClose, children, footer }: Props) {
  const titleId = useId();
  const panel = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const root = panel.current!;
    (root.querySelector<HTMLElement>("[data-autofocus]") ?? root.querySelector<HTMLElement>(FOCUSABLE))?.focus();
    return () => previous?.focus();
  }, []);

  function onKeyDown(event: KeyboardEvent) {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;
    const items = Array.from(panel.current!.querySelectorAll<HTMLElement>(FOCUSABLE));
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

  return (
    <div className={styles.scrim}>
      <div ref={panel} className={wide ? `${styles.dialog} ${styles.wide}` : styles.dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
        <header className={styles.header}>
          <div>
            {kicker && <p className={styles.kicker}>{kicker}</p>}
            <h2 id={titleId} className={styles.title}>
              {title}
            </h2>
          </div>
          <IconButton label="Close" icon={X} tip={false} onClick={onClose} />
        </header>
        <div className={styles.body}>{children}</div>
        <footer className={styles.footer}>{footer}</footer>
      </div>
    </div>
  );
}

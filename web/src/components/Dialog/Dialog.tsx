import { X } from "lucide-react";
import { useId, type ReactNode } from "react";

import { IconButton } from "../Button/IconButton";
import styles from "./Dialog.module.css";
import { useModal } from "./useModal";

type Props = { title: ReactNode; kicker?: string; wide?: boolean; onClose: () => void; children: ReactNode; footer: ReactNode };

// A modal over the page (DESIGN.md → Accessibility): focus moves in, Tab stays in, Escape closes, focus goes back.
export function Dialog({ title, kicker, wide, onClose, children, footer }: Props) {
  const titleId = useId();
  const { ref, onKeyDown } = useModal(onClose);

  return (
    <div className={styles.scrim}>
      <div ref={ref} className={wide ? `${styles.dialog} ${styles.wide}` : styles.dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} onKeyDown={onKeyDown}>
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

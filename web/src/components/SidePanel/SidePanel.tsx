import { X } from "lucide-react";
import type { ReactNode } from "react";

import { IconButton } from "../Button/IconButton";
import { useModal } from "../Dialog/useModal";
import styles from "./SidePanel.module.css";

type Props = { labelledBy: string; kicker: string; badge?: ReactNode; closeLabel: string; onClose: () => void; children: ReactNode; footer?: ReactNode };

// A right-hand modal drawer (DESIGN.md → Components): kicker and badge header, scrolling body, optional footer.
export function SidePanel({ labelledBy, kicker, badge, closeLabel, onClose, children, footer }: Props) {
  const { ref, onKeyDown } = useModal(onClose);
  return (
    <div className={styles.scrim} onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <aside ref={ref} className={styles.panel} role="dialog" aria-modal="true" aria-labelledby={labelledBy} onKeyDown={onKeyDown}>
        <header className={styles.header}>
          <div className={styles.heading}>
            <p className={styles.kicker}>{kicker}</p>
            {badge}
          </div>
          <IconButton label={closeLabel} icon={X} tip={false} onClick={onClose} />
        </header>
        <div className={styles.body}>{children}</div>
        {footer && <footer className={styles.footer}>{footer}</footer>}
      </aside>
    </div>
  );
}

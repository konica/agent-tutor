import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";

import styles from "./EmptyState.module.css";

type Props = {
  icon: LucideIcon;
  title: string;
  children?: ReactNode;
  actions?: ReactNode;
  // Small print below the actions (the drop hint).
  note?: ReactNode;
  // "dropzone" is the larger first-run card (library-empty); "default" is the dashed empty list.
  variant?: "default" | "dropzone";
};

export function EmptyState({ icon: Icon, title, children, actions, note, variant = "default" }: Props) {
  return (
    <div className={`${styles.empty} ${styles[variant]}`}>
      <span className={styles.iconWrap}>
        <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
      </span>
      <h2 className={styles.title}>{title}</h2>
      {children && <div className={styles.text}>{children}</div>}
      {actions && <div className={styles.actions}>{actions}</div>}
      {note && <p className={styles.note}>{note}</p>}
    </div>
  );
}

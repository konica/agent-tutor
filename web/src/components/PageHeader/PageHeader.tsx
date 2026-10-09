import { Info } from "lucide-react";
import type { ReactNode } from "react";

import styles from "./PageHeader.module.css";

type Props = {
  title: string;
  // Beside the title, e.g. "8 documents".
  count?: string;
  // Shown on hover/focus of an info button after the title.
  description?: string;
  actions?: ReactNode;
  // Lets one page restyle its title (the chat clamps a long question).
  titleClassName?: string;
};

// One 40px row: title, count, info button, then the actions on the right.
export function PageHeader({ title, count, description, actions, titleClassName }: Props) {
  return (
    <header className={styles.header}>
      <h1 className={[styles.title, titleClassName].filter(Boolean).join(" ")} title={title}>
        {title}
      </h1>
      {count && <span className={styles.count}>{count}</span>}
      {description && (
        <button type="button" className={styles.info} aria-label={`About ${title}`} data-tip={description}>
          <Info size={16} strokeWidth={1.5} aria-hidden="true" />
        </button>
      )}
      {actions && <div className={styles.actions}>{actions}</div>}
    </header>
  );
}

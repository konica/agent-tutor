import { Info } from "lucide-react";
import { useId, type ReactNode } from "react";

import styles from "./PageHeader.module.css";

type Props = {
  title: string;
  // Beside the title, e.g. "8 documents".
  count?: string;
  // Shown on hover/focus of an info button after the title.
  description?: string;
  actions?: ReactNode;
};

// One 40px row: title, count, info button, then the actions on the right.
export function PageHeader({ title, count, description, actions }: Props) {
  const descId = useId();
  return (
    <header className={styles.header}>
      <h1 className={styles.title} title={title}>
        {title}
      </h1>
      {count && <span className={styles.count}>{count}</span>}
      {description && (
        <>
          <button type="button" className={styles.info} aria-label={`About ${title}`} aria-describedby={descId} data-tip={description}>
            <Info size={16} strokeWidth={1.5} aria-hidden="true" />
          </button>
          <span id={descId} className="visually-hidden">{description}</span>
        </>
      )}
      {actions && <div className={styles.actions}>{actions}</div>}
    </header>
  );
}

import type { ReactNode } from "react";

import styles from "./PageHeader.module.css";

type Props = { title: string; description?: string; actions?: ReactNode };

export function PageHeader({ title, description, actions }: Props) {
  return (
    <header className={styles.header}>
      <div>
        <h1 className={styles.title}>{title}</h1>
        {description && <p className={styles.description}>{description}</p>}
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </header>
  );
}

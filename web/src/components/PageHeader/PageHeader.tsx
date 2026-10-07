import type { ReactNode } from "react";

import styles from "./PageHeader.module.css";

type Props = {
  title: string;
  description?: string;
  actions?: ReactNode;
  // Content under the title and description, e.g. the chat's subject chips.
  below?: ReactNode;
};

export function PageHeader({ title, description, actions, below }: Props) {
  return (
    <header className={styles.header}>
      <div>
        <h1 className={styles.title}>{title}</h1>
        {description && <p className={styles.description}>{description}</p>}
        {below}
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </header>
  );
}

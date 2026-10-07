import type { ReactNode } from "react";

import styles from "./PageHeader.module.css";

type Props = {
  title: string;
  description?: string;
  actions?: ReactNode;
  // Content under the title and description, e.g. the chat's subject chips.
  below?: ReactNode;
  // Lets one page restyle its title (the chat clamps a long question).
  titleClassName?: string;
};

export function PageHeader({ title, description, actions, below, titleClassName }: Props) {
  return (
    <header className={styles.header}>
      <div>
        <h1 className={[styles.title, titleClassName].filter(Boolean).join(" ")}>{title}</h1>
        {description && <p className={styles.description}>{description}</p>}
        {below}
      </div>
      {actions && <div className={styles.actions}>{actions}</div>}
    </header>
  );
}

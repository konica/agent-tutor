import { CircleCheck } from "lucide-react";
import type { ReactNode } from "react";

import styles from "./Banner.module.css";

// The caller sets role (status/alert) when the banner appears after load.
export function Banner({ variant, title, children }: { variant: "success"; title: string; children?: ReactNode }) {
  return (
    <div className={`${styles.banner} ${styles[variant]}`}>
      <CircleCheck className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
      <div className={styles.body}>
        <strong>{title}</strong>
        {children}
      </div>
    </div>
  );
}

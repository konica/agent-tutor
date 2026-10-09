import { CircleAlert, CircleCheck, Info } from "lucide-react";
import type { ReactNode } from "react";

import styles from "./Banner.module.css";

type Variant = "success" | "info" | "attn" | "danger";

const ICONS = { success: CircleCheck, info: Info, attn: CircleAlert, danger: CircleAlert } as const;

type Props = { variant: Variant; title?: string; children?: ReactNode; inline?: boolean };

// The caller sets role (status/alert) when the banner appears after load.
// inline is one 32px row with the title and text on the same line.
export function Banner({ variant, title, children, inline }: Props) {
  const Icon = ICONS[variant];
  return (
    <div className={[styles.banner, styles[variant], inline && styles.inline].filter(Boolean).join(" ")}>
      <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
      <div className={styles.body}>
        {title && <strong>{title}</strong>}
        {title && inline && " "}
        {children}
      </div>
    </div>
  );
}

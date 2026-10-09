import type { LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, Ref } from "react";

import styles from "./Button.module.css";

type Props = Omit<ButtonHTMLAttributes<HTMLButtonElement>, "children"> & { label: string; icon: LucideIcon; tip?: boolean; ref?: Ref<HTMLButtonElement> };

// A 28px icon-only button; its label is the accessible name and, unless tip is false, the tooltip (DESIGN.md → Components).
export function IconButton({ label, icon: Icon, tip = true, className, type = "button", ...rest }: Props) {
  return (
    <button type={type} className={[styles.iconButton, className].filter(Boolean).join(" ")} aria-label={label} data-tip={tip ? label : undefined} {...rest}>
      <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
    </button>
  );
}

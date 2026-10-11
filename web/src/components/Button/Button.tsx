import type { LucideIcon } from "lucide-react";
import type { ButtonHTMLAttributes, Ref } from "react";

import styles from "./Button.module.css";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "quiet" | "danger";
  size?: "sm" | "md" | "lg";
  icon?: LucideIcon;
  ref?: Ref<HTMLButtonElement>;
};

export function Button({ variant = "secondary", size = "md", icon: Icon, className, children, type = "button", ...rest }: Props) {
  const classes = [styles.button, styles[variant], styles[size], className].filter(Boolean).join(" ");
  return (
    <button type={type} className={classes} {...rest}>
      {Icon && <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />}
      {children}
    </button>
  );
}

import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import styles from "./Button.module.css";

type Props = {
  to: string;
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "quiet";
  size?: "sm" | "md" | "lg";
  icon?: LucideIcon;
};

// A navigation link that looks like a Button.
export function LinkButton({ to, variant = "secondary", size = "md", icon: Icon, children }: Props) {
  return (
    <Link to={to} className={[styles.button, styles[variant], styles[size]].join(" ")}>
      {Icon && <Icon className={styles.icon} strokeWidth={1.5} aria-hidden="true" />}
      {children}
    </Link>
  );
}

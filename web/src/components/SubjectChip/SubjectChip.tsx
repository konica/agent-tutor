import { Check } from "lucide-react";
import type { CSSProperties } from "react";

import styles from "./SubjectChip.module.css";

const HUES = ["llm", "agents", "rag", "rl", "tool", "other"] as const;
export type SubjectHue = (typeof HUES)[number];

// A stable hash of the subject id (or the name, for a new subject), so a subject keeps its colour everywhere.
export function subjectHue(hueKey: string): SubjectHue {
  let hash = 0;
  for (const ch of hueKey) hash = (hash * 31 + ch.codePointAt(0)!) >>> 0;
  return HUES[hash % HUES.length]!;
}

type Props = {
  name: string;
  hueKey: string;
  size?: "sm" | "md" | "lg"; // lg is the picker's 40px touch size
  origin?: string;
  pressed?: boolean;
  disabled?: boolean;
  onToggle?: () => void;
};

// The colour marks the dot only; the text keeps the main text colour (DESIGN.md → Tokens).
export function SubjectChip({ name, hueKey, size = "md", origin, pressed = false, disabled, onToggle }: Props) {
  const className = size === "md" ? styles.chip : `${styles.chip} ${styles[size]}`;
  const hue = { "--h": `var(--subj-${subjectHue(hueKey)})` } as CSSProperties;
  const dot = <span className={styles.dot} aria-hidden="true" />;
  if (!onToggle) {
    return (
      <span className={className} style={hue}>
        {dot}
        {name}
      </span>
    );
  }
  return (
    <button type="button" className={className} style={hue} aria-pressed={pressed} disabled={disabled} onClick={onToggle}>
      {pressed && <Check className={styles.check} strokeWidth={1.5} aria-hidden="true" />}
      {dot}
      {name}
      {origin && <span className={styles.origin}>· {origin}</span>}
    </button>
  );
}

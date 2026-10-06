import { Check } from "lucide-react";

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
  size?: "sm" | "md";
  origin?: string;
  pressed?: boolean;
  disabled?: boolean;
  onToggle?: () => void;
};

// The colour marks the dot only; the text keeps the main text colour (DESIGN.md → Tokens).
export function SubjectChip({ name, hueKey, size = "md", origin, pressed = false, disabled, onToggle }: Props) {
  const className = `${styles.chip} ${styles[size]}`;
  const dot = <span className={styles.dot} style={{ background: `var(--subj-${subjectHue(hueKey)})` }} aria-hidden="true" />;
  if (!onToggle) {
    return (
      <span className={className}>
        {dot}
        {name}
      </span>
    );
  }
  return (
    <button type="button" className={className} aria-pressed={pressed} disabled={disabled} onClick={onToggle}>
      {pressed && <Check className={styles.check} strokeWidth={1.5} aria-hidden="true" />}
      {dot}
      {name}
      {origin && <span className={styles.origin}>· {origin}</span>}
    </button>
  );
}

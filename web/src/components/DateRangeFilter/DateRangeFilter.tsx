import { CalendarDays, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";

import styles from "./DateRangeFilter.module.css";

type DateRange = { from?: string; to?: string }; // YYYY-MM-DD as the date inputs hold them; "" when cleared
type Props = { label: string; groupLabel: string; from?: string; to?: string; onChange: (range: DateRange) => void };

const describe = (from?: string, to?: string) => (from && to ? `${from} to ${to}` : from ? `from ${from}` : to ? `until ${to}` : "");

// A date range in one popover, so the toolbar stays one row (DESIGN.md → Layout → Toolbar).
export function DateRangeFilter({ label, groupLabel, from, to, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const popId = useId();
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const first = useRef<HTMLInputElement>(null);
  const range = describe(from, to);

  useEffect(() => {
    if (open) first.current?.focus();
  }, [open]);

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "Escape" || !open) return;
    e.stopPropagation();
    setOpen(false);
    button.current?.focus();
  };
  const onBlur = (e: FocusEvent) => {
    if (open && !root.current?.contains(e.relatedTarget as Node | null)) setOpen(false);
  };

  return (
    <div className={styles.root} ref={root} onKeyDown={onKeyDown} onBlur={onBlur}>
      <button ref={button} type="button" className={range ? `${styles.button} ${styles.on}` : styles.button} aria-expanded={open} aria-controls={popId} aria-label={range ? `${label}: ${range}` : label} onClick={() => setOpen((v) => !v)}>
        <CalendarDays className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
        {label}
        <ChevronDown className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
      </button>
      {open && (
        <div className={styles.pop} id={popId} tabIndex={-1} role="group" aria-label={groupLabel}>
          <label className={styles.field}>
            From
            <input ref={first} type="date" value={from ?? ""} max={to || undefined} onChange={(e) => onChange({ from: e.target.value })} />
          </label>
          <label className={styles.field}>
            To
            <input type="date" value={to ?? ""} min={from || undefined} onChange={(e) => onChange({ to: e.target.value })} />
          </label>
        </div>
      )}
    </div>
  );
}

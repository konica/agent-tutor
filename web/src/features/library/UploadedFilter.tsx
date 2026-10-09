import { CalendarDays, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";

import styles from "./UploadedFilter.module.css";

type Range = { uploaded_from?: string; uploaded_to?: string };
type Props = { from?: string; to?: string; onChange: (range: Range) => void };

const describe = (from?: string, to?: string) => (from && to ? `${from} to ${to}` : from ? `from ${from}` : to ? `until ${to}` : "");

// The upload-date range in one popover, so the toolbar stays one row (DESIGN.md → Layout → Toolbar).
export function UploadedFilter({ from, to, onChange }: Props) {
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
      <button ref={button} type="button" className={range ? `${styles.button} ${styles.on}` : styles.button} aria-expanded={open} aria-controls={popId} aria-label={range ? `Uploaded: ${range}` : "Uploaded"} onClick={() => setOpen((v) => !v)}>
        <CalendarDays className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
        Uploaded
        <ChevronDown className={styles.icon} strokeWidth={1.5} aria-hidden="true" />
      </button>
      {open && (
        <div className={styles.pop} id={popId} tabIndex={-1} role="group" aria-label="Upload dates">
          <label className={styles.field}>
            From
            <input ref={first} type="date" value={from ?? ""} max={to || undefined} onChange={(e) => onChange({ uploaded_from: e.target.value })} />
          </label>
          <label className={styles.field}>
            To
            <input type="date" value={to ?? ""} min={from || undefined} onChange={(e) => onChange({ uploaded_to: e.target.value })} />
          </label>
        </div>
      )}
    </div>
  );
}

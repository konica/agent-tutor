import { X } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "../Button/Button";
import styles from "./FilterBar.module.css";

type Props = {
  label: string; // accessible name of the search landmark, e.g. "Filter documents"
  noun: string; // singular, for the count: "document" -> "3 documents"
  count: number | null; // null while the first result is loading
  active: boolean; // any filter set; shows Clear filters
  onClear: () => void;
  children: ReactNode; // FilterField items
};

// Labelled filter fields, the live result count, and a Clear filters button that appears only while a filter is set.
export function FilterBar({ label, noun, count, active, onClear, children }: Props) {
  return (
    <div className={styles.bar} role="search" aria-label={label}>
      {children}
      <div className={styles.summary}>
        <span aria-live="polite">{count === null ? "" : count === 1 ? `1 ${noun}` : `${count} ${noun}s`}</span>
        {active && (
          <Button variant="ghost" size="sm" icon={X} onClick={onClear}>
            Clear filters
          </Button>
        )}
      </div>
    </div>
  );
}

// One native control (select or input) under its visible label.
export function FilterField({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className={styles.field}>
      <label htmlFor={id} className="visually-hidden">{label}</label>
      {children}
    </div>
  );
}

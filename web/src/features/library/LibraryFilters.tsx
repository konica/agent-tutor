import { X } from "lucide-react";
import { forwardRef } from "react";

import type { DocumentFilters } from "../../api/documents";
import type { SubjectResponse } from "../../api/generated/types.gen";
import { Button } from "../../components/Button/Button";
import styles from "./LibraryFilters.module.css";

// Same wording as StateBadge; the value is the API's state.
const STATES: { value: NonNullable<DocumentFilters["state"]>; label: string }[] = [
  { value: "processing", label: "Processing" },
  { value: "awaiting_subjects", label: "Choose subjects" },
  { value: "ready", label: "Ready" },
  { value: "failed", label: "Failed" },
];

export function hasFilters(filters: DocumentFilters): boolean {
  return Boolean(filters.subject_ids?.length || filters.state || filters.uploaded_from || filters.uploaded_to);
}

type Props = {
  filters: DocumentFilters;
  onChange: (filters: DocumentFilters) => void;
  subjects: SubjectResponse[];
  count: number | null;
  onClear: () => void;
};

// Single-select Subject and State, an inclusive From–To date range, and the result count. Every change reloads the list through the API.
export const LibraryFilters = forwardRef<HTMLSelectElement, Props>(function LibraryFilters({ filters, onChange, subjects, count, onClear }, subjectRef) {
  const set = (patch: Partial<DocumentFilters>) => {
    const next = { ...filters, ...patch };
    // Absent means unfiltered, so an emptied control drops its key.
    for (const key of Object.keys(next) as (keyof DocumentFilters)[]) {
      const value = next[key];
      if (value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) delete next[key];
    }
    onChange(next);
  };
  return (
    <div className={styles.bar} role="search" aria-label="Filter documents">
      <div className={styles.field}>
        <label htmlFor="filter-subject">Subject</label>
        <select id="filter-subject" ref={subjectRef} className={styles.control} value={filters.subject_ids?.[0] ?? ""} onChange={(e) => set({ subject_ids: e.target.value ? [e.target.value] : undefined })}>
          <option value="">All subjects</option>
          {subjects.map((s) => (
            <option key={s.subject_id} value={s.subject_id}>
              {s.name}
            </option>
          ))}
        </select>
      </div>
      <div className={styles.range}>
        <div className={styles.field}>
          <label htmlFor="filter-from">From</label>
          <input id="filter-from" type="date" className={styles.control} value={filters.uploaded_from ?? ""} max={filters.uploaded_to || undefined} onChange={(e) => set({ uploaded_from: e.target.value })} />
        </div>
        <span className={styles.dash} aria-hidden="true">
          –
        </span>
        <div className={styles.field}>
          <label htmlFor="filter-to">To</label>
          <input id="filter-to" type="date" className={styles.control} value={filters.uploaded_to ?? ""} min={filters.uploaded_from || undefined} onChange={(e) => set({ uploaded_to: e.target.value })} />
        </div>
      </div>
      <div className={styles.field}>
        <label htmlFor="filter-state">State</label>
        <select id="filter-state" className={styles.control} value={filters.state ?? ""} onChange={(e) => set({ state: (e.target.value || undefined) as DocumentFilters["state"] })}>
          <option value="">All states</option>
          {STATES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      <div className={styles.summary}>
        <span aria-live="polite">{count === null ? "" : count === 1 ? "1 document" : `${count} documents`}</span>
        {hasFilters(filters) && (
          <Button variant="ghost" size="sm" icon={X} onClick={onClear}>
            Clear filters
          </Button>
        )}
      </div>
    </div>
  );
});

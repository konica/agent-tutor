import { forwardRef } from "react";

import type { DocumentFilters } from "../../api/documents";
import type { SubjectResponse } from "../../api/generated/types.gen";
import { FilterBar, FilterField, FilterRange, FilterRangeDash } from "../../components/FilterBar/FilterBar";

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
    <FilterBar label="Filter documents" noun="document" count={count} active={hasFilters(filters)} onClear={onClear}>
      <FilterField id="filter-subject" label="Subject">
        <select id="filter-subject" ref={subjectRef} value={filters.subject_ids?.[0] ?? ""} onChange={(e) => set({ subject_ids: e.target.value ? [e.target.value] : undefined })}>
          <option value="">All subjects</option>
          {subjects.map((s) => (
            <option key={s.subject_id} value={s.subject_id}>
              {s.name}
            </option>
          ))}
        </select>
      </FilterField>
      <FilterRange>
        <FilterField id="filter-from" label="From">
          <input id="filter-from" type="date" value={filters.uploaded_from ?? ""} max={filters.uploaded_to || undefined} onChange={(e) => set({ uploaded_from: e.target.value })} />
        </FilterField>
        <FilterRangeDash />
        <FilterField id="filter-to" label="To">
          <input id="filter-to" type="date" value={filters.uploaded_to ?? ""} min={filters.uploaded_from || undefined} onChange={(e) => set({ uploaded_to: e.target.value })} />
        </FilterField>
      </FilterRange>
      <FilterField id="filter-state" label="State">
        <select id="filter-state" value={filters.state ?? ""} onChange={(e) => set({ state: (e.target.value || undefined) as DocumentFilters["state"] })}>
          <option value="">All states</option>
          {STATES.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
      </FilterField>
    </FilterBar>
  );
});

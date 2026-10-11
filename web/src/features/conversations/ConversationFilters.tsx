import { hasConversationFilters, type ConversationFilters as Filters } from "../../api/conversations";
import type { SubjectResponse } from "../../api/generated/types.gen";
import { DateRangeFilter } from "../../components/DateRangeFilter/DateRangeFilter";
import { FilterBar, FilterField } from "../../components/FilterBar/FilterBar";

type Props = { filters: Filters; onChange: (filters: Filters) => void; subjects: SubjectResponse[]; count: number | null; onClear: () => void };

// Search titles, a single-select Subject, and a last-activity date popover (PRD US-13), in the Library's filter bar.
export function ConversationFilters({ filters, onChange, subjects, count, onClear }: Props) {
  const set = (patch: Partial<Filters>) => {
    const next: Filters = { ...filters, ...patch };
    for (const key of Object.keys(next) as (keyof Filters)[]) if (!next[key]) delete next[key]; // absent means unfiltered; " " stays so the box shows what was typed
    onChange(next);
  };
  return (
    <FilterBar label="Filter conversations" noun="conversation" count={count} active={hasConversationFilters(filters)} onClear={onClear}>
      <FilterField id="filter-title" label="Search titles">
        <input id="filter-title" type="search" maxLength={120} placeholder="Search titles" value={filters.q ?? ""} onChange={(e) => set({ q: e.target.value })} />
      </FilterField>
      <FilterField id="filter-subject" label="Subject">
        <select id="filter-subject" value={filters.subject_id ?? ""} onChange={(e) => set({ subject_id: e.target.value })}>
          <option value="">All subjects</option>
          {subjects.map((s) => (
            <option key={s.subject_id} value={s.subject_id}>{s.name}</option>
          ))}
        </select>
      </FilterField>
      <DateRangeFilter
        label="Date"
        groupLabel="Last activity"
        from={filters.active_from}
        to={filters.active_to}
        onChange={(r) => set({ ...("from" in r ? { active_from: r.from } : {}), ...("to" in r ? { active_to: r.to } : {}) })}
      />
    </FilterBar>
  );
}

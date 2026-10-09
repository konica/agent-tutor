import { useCallback, useEffect, useRef, useState } from "react";

import type { DocumentFilters, DocumentResponse } from "../../api/documents";

export type LibraryCounts = { active: number | null; archived: number | null; refresh: () => Promise<void> };

// The tab counts are unfiltered totals, so both lists load without filters: on mount and whenever the caller refreshes.
// Only the latest answer is applied, and a failure keeps the previous counts.
export function useLibraryCounts(load: (filters: DocumentFilters) => Promise<DocumentResponse[]>): LibraryCounts {
  const [counts, setCounts] = useState<{ active: number | null; archived: number | null }>({ active: null, archived: null });
  const loadRef = useRef(load);
  const sequence = useRef(0);
  const alive = useRef(true);

  useEffect(() => {
    loadRef.current = load; // an inline `load` must not reload
  }, [load]);

  const refresh = useCallback(async () => {
    const mine = ++sequence.current;
    try {
      const [active, archived] = await Promise.all([loadRef.current({}), loadRef.current({ archived: true })]);
      if (alive.current && mine === sequence.current) setCounts({ active: active.length, archived: archived.length });
    } catch {
      // a 401 is handled by the API client; otherwise keep the previous counts
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void refresh();
    return () => {
      alive.current = false;
    };
  }, [refresh]);

  return { ...counts, refresh };
}

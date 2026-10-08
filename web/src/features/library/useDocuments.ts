import { useCallback, useEffect, useRef, useState } from "react";

import type { DocumentFilters, DocumentResponse } from "../../api/documents";

export type DocumentsState = { documents: DocumentResponse[] | null; applied: DocumentFilters; unavailable: boolean; refresh: () => Promise<void> };

const NO_FILTERS: DocumentFilters = {};

// Loads the library now and every `pollMs`, so processing states update without a reload.
// A change of `filters` reloads at once and polling continues with the new ones.
// Only the latest response is applied (so a slow response for old filters never overwrites newer ones), ticks skip while a load is running, and nothing is set after unmount.
export function useDocuments(load: (filters: DocumentFilters) => Promise<DocumentResponse[]>, pollMs: number, filters: DocumentFilters = NO_FILTERS): DocumentsState {
  const [documents, setDocuments] = useState<DocumentResponse[] | null>(null);
  const [applied, setApplied] = useState<DocumentFilters>(NO_FILTERS); // the filters `documents` was loaded with
  const [unavailable, setUnavailable] = useState(false);
  const loadRef = useRef(load);
  const filtersKey = JSON.stringify(filters); // callers may pass a fresh object every render
  const filtersRef = useRef(filters);
  const sequence = useRef(0);
  const inFlight = useRef(0);
  const alive = useRef(true);

  useEffect(() => {
    loadRef.current = load; // an inline `load` must not restart polling
  }, [load]);

  useEffect(() => {
    filtersRef.current = filters;
  }, [filters]);

  const run = useCallback(async () => {
    const mine = ++sequence.current;
    inFlight.current++;
    try {
      const asked = filtersRef.current;
      const result = await loadRef.current(asked);
      if (alive.current && mine === sequence.current) {
        setDocuments(result);
        setApplied(asked);
        setUnavailable(false);
      }
    } catch {
      // a 401 is handled by the API client (SessionProvider shows "Please sign in again")
      if (alive.current && mine === sequence.current) setUnavailable(true);
    } finally {
      inFlight.current--;
    }
  }, []);

  useEffect(() => {
    alive.current = true;
    void run();
    const timer = setInterval(() => {
      if (inFlight.current === 0) void run();
    }, pollMs);
    return () => {
      alive.current = false;
      clearInterval(timer);
    };
  }, [run, pollMs, filtersKey]);

  return { documents, applied, unavailable, refresh: run };
}

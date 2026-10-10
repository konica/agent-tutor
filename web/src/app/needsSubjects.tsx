import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import type { DocumentFilters, DocumentResponse } from "../api/documents";

export type NeedsSubjects = { count: number | null; report: (count: number) => void };
export const NeedsSubjectsContext = createContext<NeedsSubjects>({ count: null, report: () => {} });
export const useNeedsSubjects = () => useContext(NeedsSubjectsContext);
export const needsSubjectsLabel = (count: number) => (count === 1 ? "1 needs subjects" : `${count} need subjects`);

// The side nav's Library badge: the learner's non-archived documents waiting for subjects (PRD US-2b).
// The shell reloads it on every navigation; the Library reports fresher counts as it polls.
export function useNeedsSubjectsState(load: (filters: DocumentFilters) => Promise<DocumentResponse[]>, key: string): NeedsSubjects {
  const [count, setCount] = useState<number | null>(null);
  const loadRef = useRef(load);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);
  useEffect(() => {
    let alive = true;
    loadRef.current({ state: "awaiting_subjects" }).then(
      (docs) => {
        if (alive) setCount(docs.length);
      },
      () => {}, // a failure keeps the count
    );
    return () => {
      alive = false;
    };
  }, [key]);
  const report = useCallback((n: number) => setCount(n), []);
  return useMemo(() => ({ count, report }), [count, report]);
}

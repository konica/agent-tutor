import { useCallback, useEffect, useRef, useState } from "react";

import type { DocumentResponse } from "../../api/documents";

export type DocumentsState = { documents: DocumentResponse[] | null; unavailable: boolean; refresh: () => Promise<void> };

// Loads the library now and every `pollMs`, so processing states update without a reload.
// Only the latest response is applied, ticks skip while a load is running, and nothing is set after unmount.
export function useDocuments(load: () => Promise<DocumentResponse[]>, pollMs: number): DocumentsState {
  const [documents, setDocuments] = useState<DocumentResponse[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const loadRef = useRef(load);
  const sequence = useRef(0);
  const inFlight = useRef(0);
  const alive = useRef(true);

  useEffect(() => {
    loadRef.current = load; // an inline `load` must not restart polling
  }, [load]);

  const run = useCallback(async () => {
    const mine = ++sequence.current;
    inFlight.current++;
    try {
      const result = await loadRef.current();
      if (alive.current && mine === sequence.current) {
        setDocuments(result);
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
  }, [run, pollMs]);

  return { documents, unavailable, refresh: run };
}

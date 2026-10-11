import { useEffect, useRef, useState } from "react";

import { hasConversationFilters, type ConversationFilters, type ThreadSummaryResponse } from "../../api/conversations";

const DEBOUNCE_MS = 250;

// The conversations that match `filters`, loaded here so the shell's list (the side nav's recent ones) stays unfiltered.
// Loads only while a filter is set; a title search waits for a pause in typing, other filters load at once. A change of
// `reloadKey` (the shell reloaded: rename, answer, navigation) reloads too. Only the latest call's result is applied and
// nothing is set after unmount.
export function useFilteredConversations(
  load: (filters: ConversationFilters) => Promise<ThreadSummaryResponse[]>,
  filters: ConversationFilters,
  reloadKey: unknown,
): { list: ThreadSummaryResponse[] | null; failed: boolean } {
  const [list, setList] = useState<ThreadSummaryResponse[] | null>(null);
  const [failed, setFailed] = useState(false);
  const loadRef = useRef(load);
  const sequence = useRef(0);
  const alive = useRef(true);
  const filtering = hasConversationFilters(filters);
  const { q, ...rest } = filters;
  const restKey = JSON.stringify(rest);
  const query = q?.trim() ?? "";

  useEffect(() => {
    loadRef.current = load; // an inline `load` must not restart the effect
  }, [load]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  useEffect(() => {
    if (!filtering) {
      sequence.current++; // a response still in flight is stale now
      setList(null);
      setFailed(false);
      return;
    }
    const asked: ConversationFilters = { ...(JSON.parse(restKey) as ConversationFilters), ...(query ? { q: query } : {}) };
    const run = async () => {
      const mine = ++sequence.current;
      try {
        const result = await loadRef.current(asked);
        if (alive.current && mine === sequence.current) {
          setList(result);
          setFailed(false);
        }
      } catch {
        // a 401 is handled by the API client (SessionProvider shows "Please sign in again")
        if (alive.current && mine === sequence.current) setFailed(true);
      }
    };
    if (!query) {
      void run();
      return;
    }
    const timer = setTimeout(() => void run(), DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [filtering, restKey, query, reloadKey]);

  return filtering ? { list, failed } : { list: null, failed: false };
}

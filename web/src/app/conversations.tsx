import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import type { ThreadSummaryResponse } from "../api/conversations";
import type { RecentConversation } from "./nav";

export type ConversationsList = { list: ThreadSummaryResponse[] | null; failed: boolean; refresh: () => void };
export const ConversationsContext = createContext<ConversationsList>({ list: null, failed: false, refresh: () => {} });
export const useConversations = () => useContext(ConversationsContext);

export const conversationTitle = (t: ThreadSummaryResponse) => t.title ?? "Untitled conversation";

export const recentConversations = (list: ThreadSummaryResponse[] | null): RecentConversation[] =>
  (list ?? []).slice(0, 3).map((t) => ({ id: t.thread_id, title: conversationTitle(t), path: `/chat/${t.thread_id}` }));

// The learner's conversations (PRD US-13), for the side nav's recent ones and the Conversations page. The shell reloads
// it on every navigation; Chat refreshes it after a rename or an answer. Only the latest load's result is kept.
export function useConversationsState(load: () => Promise<ThreadSummaryResponse[]>, key: string): ConversationsList {
  const [list, setList] = useState<ThreadSummaryResponse[] | null>(null);
  const [failed, setFailed] = useState(false);
  const loadRef = useRef(load);
  const latest = useRef(0);
  useEffect(() => {
    loadRef.current = load;
  }, [load]);
  const refresh = useCallback(() => {
    const call = ++latest.current;
    loadRef.current().then(
      (items) => {
        if (call !== latest.current) return;
        setList(items);
        setFailed(false);
      },
      () => {
        if (call === latest.current) setFailed(true); // a failure keeps the last list
      },
    );
  }, []);
  useEffect(() => {
    refresh();
  }, [key, refresh]);
  useEffect(
    () => () => {
      latest.current++; // unmounted: ignore loads still running
    },
    [],
  );
  return useMemo(() => ({ list, failed, refresh }), [list, failed, refresh]);
}

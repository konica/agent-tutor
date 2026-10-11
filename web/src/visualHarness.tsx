// TEMPORARY visual harness for #190 — not committed.
import "./styles/tokens.css";
import "./styles/base.css";

import { createRoot } from "react-dom/client";
import { createMemoryRouter, RouterProvider } from "react-router";

import type { ConversationFilters, ThreadSummaryResponse } from "./api/conversations";
import { SessionContext } from "./auth/SessionProvider";
import { AppShell } from "./components/AppShell/AppShell";
import { ConversationsPage } from "./features/conversations/ConversationsPage";
import { followColorScheme } from "./styles/theme";

followColorScheme(document.documentElement, window.matchMedia("(prefers-color-scheme: dark)"));

const S = {
  agents: { subject_id: "agents", name: "AI Agents" },
  rag: { subject_id: "rag", name: "Retrieval-Augmented Generation" },
  rl: { subject_id: "rl", name: "Reinforcement Learning" },
  nlp: { subject_id: "nlp", name: "Natural Language Processing" },
};
const now = new Date();
const ago = (h: number) => new Date(now.getTime() - h * 3600_000).toISOString();
const all: ThreadSummaryResponse[] = [
  { thread_id: "1", title: "How does ReAct combine reasoning and acting?", subjects: [S.agents, S.rag, S.nlp], documents: 3, last_activity: ago(1) },
  { thread_id: "2", title: "What does chain-of-thought prompting change?", subjects: [S.nlp], documents: 1, last_activity: ago(30) },
  { thread_id: "3", title: "How does self-attention weigh tokens?", subjects: [S.nlp], documents: 2, last_activity: ago(80) },
  { thread_id: "4", title: "Why does retrieval reduce hallucination?", subjects: [S.rag], documents: 2, last_activity: ago(200) },
  { thread_id: "5", title: "What is policy gradient?", subjects: [], documents: 0, last_activity: ago(400) },
];
const load = async (f: ConversationFilters = {}) =>
  all.filter(
    (t) =>
      (!f.subject_id || t.subjects.some((s) => s.subject_id === f.subject_id)) &&
      (!f.q?.trim() || (t.title ?? "").toLowerCase().includes(f.q.trim().toLowerCase())) &&
      (!f.active_from || t.last_activity.slice(0, 10) >= f.active_from) &&
      (!f.active_to || t.last_activity.slice(0, 10) <= f.active_to),
  );
const subjects = async () => [S.agents, S.nlp, S.rl, S.rag];

const router = createMemoryRouter(
  [
    {
      path: "/",
      element: <AppShell loadDocuments={async () => []} loadConversations={() => load()} />,
      children: [{ path: "conversations", element: <ConversationsPage loadConversations={load} loadSubjects={subjects} />, handle: { wide: true } }],
    },
  ],
  { initialEntries: ["/conversations"] },
);

createRoot(document.getElementById("root")!).render(
  <SessionContext.Provider value={{ name: "Mai Nguyen", signOut: () => {} }}>
    <RouterProvider router={router} />
  </SessionContext.Provider>,
);

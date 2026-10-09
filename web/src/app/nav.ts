import { ChartColumn, FileText, Library, List, MessageSquare, Tag, type LucideIcon } from "lucide-react";

// `group` splits the nav into sections with a rule between them: the workspace, the history, the reference pages.
export type NavItem = { path: string; label: string; icon: LucideIcon; description: string; group: 0 | 1 | 2 };

export type RecentConversation = { id: string; title: string; path: string };

// Brief §6.1 order. Release 2 adds Research map after Library; Release 3 adds Quizzes and Reports after Notes.
export const NAV: readonly NavItem[] = [
  { path: "/library", label: "Library", icon: Library, group: 0, description: "Your documents. They're private to you, and the tutor answers only from them." },
  { path: "/chat", label: "Chat", icon: MessageSquare, group: 0, description: "Ask a question about your documents." },
  { path: "/conversations", label: "Conversations", icon: List, group: 1, description: "Your past conversations." },
  { path: "/notes", label: "Notes", icon: FileText, group: 1, description: "Lesson Notes from your conversations." },
  { path: "/subjects", label: "Subjects", icon: Tag, group: 2, description: "Subjects come from your documents." },
  { path: "/usage", label: "Usage", icon: ChartColumn, group: 2, description: "Tokens used by your conversations and documents." },
];

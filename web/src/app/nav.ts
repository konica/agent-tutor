import { ChartColumn, FileText, Library, List, MessageSquare, Tag, type LucideIcon } from "lucide-react";

export type NavItem = { path: string; label: string; icon: LucideIcon; description: string };

// Brief §6.1 order. Release 2 adds Research map after Library; Release 3 adds Quizzes and Reports after Notes.
export const NAV: readonly NavItem[] = [
  { path: "/library", label: "Library", icon: Library, description: "Your documents. They're private to you, and the tutor answers only from them." },
  { path: "/chat", label: "Chat", icon: MessageSquare, description: "Ask a question about your documents." },
  { path: "/conversations", label: "Conversations", icon: List, description: "Your past conversations." },
  { path: "/notes", label: "Notes", icon: FileText, description: "Lesson Notes from your conversations." },
  { path: "/subjects", label: "Subjects", icon: Tag, description: "Subjects come from your documents." },
  { path: "/usage", label: "Usage", icon: ChartColumn, description: "Tokens used by your conversations and documents." },
];

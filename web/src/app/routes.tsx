import type { ComponentType, ReactNode } from "react";
import { Navigate, type RouteObject } from "react-router";

import type { AuthClient } from "../auth/authClient";
import { AppShell } from "../components/AppShell/AppShell";
import { ChatPage } from "../features/chat/ChatPage";
import { ConversationsPage } from "../features/conversations/ConversationsPage";
import { LandingPage } from "../features/landing/LandingPage";
import { LibraryPage } from "../features/library/LibraryPage";
import { NAV } from "./nav";
import { PlaceholderPage } from "./PlaceholderPage";

export type RouteDeps = {
  auth: Pick<AuthClient, "signIn">;
  /** Wraps every app route; renders its children only for a live session. */
  RequireSession: ComponentType<{ children: ReactNode }>;
};

// `/` is the public landing page (US-1); every other path needs a session.
export function createRoutes({ auth, RequireSession }: RouteDeps): RouteObject[] {
  return [
    { path: "/", element: <LandingPage signIn={auth.signIn} /> },
    {
      element: (
        <RequireSession>
          <AppShell />
        </RequireSession>
      ),
      children: [
        { path: "library", element: <LibraryPage />, handle: { wide: true } },
        // One route for a new conversation and one at its URL, so moving from /chat to /chat/<id> while the answer
        // streams keeps the page mounted.
        { path: "chat/:threadId?", element: <ChatPage />, handle: { bleed: true } },
        { path: "conversations", element: <ConversationsPage />, handle: { wide: true } },
        ...NAV.filter((item) => item.path !== "/library" && item.path !== "/chat" && item.path !== "/conversations").map((item) => ({
          path: item.path.slice(1),
          element: <PlaceholderPage title={item.label} description={item.description} />,
        })),
        { path: "*", element: <Navigate to="/library" replace /> },
      ],
    },
  ];
}

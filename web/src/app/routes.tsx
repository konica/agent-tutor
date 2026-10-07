import { Navigate, type RouteObject } from "react-router";

import { AppShell } from "../components/AppShell/AppShell";
import { ChatPage } from "../features/chat/ChatPage";
import { LibraryPage } from "../features/library/LibraryPage";
import { NAV } from "./nav";
import { PlaceholderPage } from "./PlaceholderPage";

export const routes: RouteObject[] = [
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/library" replace /> },
      { path: "library", element: <LibraryPage />, handle: { wide: true } },
      { path: "chat", element: <ChatPage /> },
      ...NAV.filter((item) => item.path !== "/library" && item.path !== "/chat").map((item) => ({
        path: item.path.slice(1),
        element: <PlaceholderPage title={item.label} description={item.description} />,
      })),
      { path: "*", element: <Navigate to="/library" replace /> },
    ],
  },
];

// Screens live in src/features/<feature>; shared UI in src/components; Keycloak login (PKCE) in src/auth; API client in src/api.
import { useState } from "react";
import { createBrowserRouter, RouterProvider, type RouteObject } from "react-router";

export function App({ routes }: { routes: RouteObject[] }) {
  const [router] = useState(() => createBrowserRouter(routes));
  return <RouterProvider router={router} />;
}

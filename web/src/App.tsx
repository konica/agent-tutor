// Screens live in src/features/<feature>; shared UI in src/components; Keycloak login (PKCE) in src/auth; API client in src/api.
import { createBrowserRouter, RouterProvider } from "react-router";

import { routes } from "./app/routes";

const router = createBrowserRouter(routes);

export function App() {
  return <RouterProvider router={router} />;
}

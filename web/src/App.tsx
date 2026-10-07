// Screens live in src/features/<feature>; shared UI in src/components; Keycloak login (PKCE) in src/auth; API client in src/api.
import { RouterProvider, type createBrowserRouter } from "react-router";

export function App({ router }: { router: ReturnType<typeof createBrowserRouter> }) {
  return <RouterProvider router={router} />;
}

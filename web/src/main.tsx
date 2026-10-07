import "./styles/tokens.css";
import "./styles/base.css";

import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { createRoutes } from "./app/routes";
import { apiBaseUrl, configureApiClient } from "./api/client";
import { loadMe } from "./api/me";
import { sessionExpiry } from "./auth/authClient";
import { createKeycloakClient } from "./auth/keycloakClient";
import { SessionProvider } from "./auth/SessionProvider";
import { followColorScheme } from "./styles/theme";

followColorScheme(document.documentElement, window.matchMedia("(prefers-color-scheme: dark)"));

const auth = createKeycloakClient();
configureApiClient({ baseUrl: apiBaseUrl(), getToken: () => auth.getToken(), onUnauthorized: sessionExpiry.notify });

function RequireSession({ children }: { children: ReactNode }) {
  return (
    <SessionProvider auth={auth} loadMe={loadMe}>
      {children}
    </SessionProvider>
  );
}

const routes = createRoutes({ auth, RequireSession });

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App routes={routes} />
  </StrictMode>,
);

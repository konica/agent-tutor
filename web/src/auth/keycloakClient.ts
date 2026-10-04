import Keycloak from "keycloak-js";

import type { AuthClient } from "./authClient";

export type AuthConfig = { url: string; realm: string; clientId: string };

export function authConfig(): AuthConfig {
  return {
    url: import.meta.env.VITE_KEYCLOAK_URL ?? "http://localhost:10480",
    realm: import.meta.env.VITE_KEYCLOAK_REALM ?? "smart-tutor",
    clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID ?? "smart-tutor-web",
  };
}

// Authorization Code + PKCE on the public smart-tutor-web client (PRD §9.3).
export function createKeycloakClient(config: AuthConfig = authConfig()): AuthClient {
  const keycloak = new Keycloak(config);
  let initialized: Promise<void> | undefined; // keycloak-js throws if init runs twice (StrictMode)

  return {
    init() {
      initialized ??= keycloak
        .init({ onLoad: "login-required", pkceMethod: "S256", checkLoginIframe: false })
        .then(
          () => undefined,
          (error: unknown) => {
            initialized = undefined; // a failed init must not stay cached, so "Try again" can re-run it
            throw error;
          },
        );
      return initialized;
    },
    async getToken() {
      await keycloak.updateToken(60);
      if (!keycloak.token) throw new Error("Not signed in");
      return keycloak.token;
    },
    signIn: () => keycloak.login(),
    signOut: () => keycloak.logout({ redirectUri: `${window.location.origin}/` }),
  };
}

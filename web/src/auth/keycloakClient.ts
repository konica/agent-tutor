import Keycloak, { type KeycloakInitOptions } from "keycloak-js";

import { absoluteUrl } from "../api/absoluteUrl";
import type { AuthClient, SignInOptions } from "./authClient";

export type AuthConfig = { url: string; realm: string; clientId: string };

export function authConfig(): AuthConfig {
  return {
    url: absoluteUrl(import.meta.env.VITE_KEYCLOAK_URL || "http://localhost:10401"),
    realm: import.meta.env.VITE_KEYCLOAK_REALM || "smart-tutor",
    clientId: import.meta.env.VITE_KEYCLOAK_CLIENT_ID || "smart-tutor-web",
  };
}

// Authorization Code + PKCE on the public smart-tutor-web client (PRD §9.3).
export function createKeycloakClient(config: AuthConfig = authConfig()): AuthClient {
  const keycloak = new Keycloak(config);
  // keycloak-js throws if init runs twice (StrictMode), so every caller shares one init.
  let initialized: Promise<void> | undefined;

  // The init is shared and keeps the first caller's options: a lazy signIn init must always be followed by the
  // Keycloak redirect, never by in-app navigation to a guarded route, which would skip login-required.
  const start = (options: KeycloakInitOptions) => {
    initialized ??= keycloak.init({ ...options, pkceMethod: "S256", checkLoginIframe: false }).then(
      () => undefined,
      (error: unknown) => {
        initialized = undefined; // a failed init must not stay cached, so "Try again" can re-run it
        throw error;
      },
    );
    return initialized;
  };

  return {
    init: () => start({ onLoad: "login-required" }),
    async getToken() {
      await keycloak.updateToken(60);
      if (!keycloak.token) throw new Error("Not signed in");
      return keycloak.token;
    },
    // The landing page signs in without init(): init without onLoad sends no request.
    async signIn({ register, redirectTo }: SignInOptions = {}) {
      await start({});
      await keycloak.login({
        ...(register && { action: "register" }),
        ...(redirectTo && { redirectUri: `${window.location.origin}${redirectTo}` }),
      });
    },
    signOut: () => keycloak.logout({ redirectUri: `${window.location.origin}/` }),
  };
}

/// <reference types="vite/client" />

// Defaults match Docker Compose (AGENTS.md → Local development); set these at build time elsewhere.
interface ImportMetaEnv {
  readonly VITE_API_URL?: string;
  readonly VITE_KEYCLOAK_URL?: string;
  readonly VITE_KEYCLOAK_REALM?: string;
  readonly VITE_KEYCLOAK_CLIENT_ID?: string;
}
